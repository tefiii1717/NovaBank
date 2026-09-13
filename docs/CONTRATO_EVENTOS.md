# Contrato de Eventos y API — Saga Bancaria NovaBank

Este documento es la fuente de verdad que **ambos** integrantes del equipo (Sofía y Yuly)
deben respetar para que la Saga Coreografiada y la Saga Orquestada sean intercambiables
desde el frontend, y para que cualquier servicio pueda ser implementado o reemplazado
sin romper a los demás.

Propietaria del contrato: Yuly (rol de coreografía). Cambios aquí deben avisarse al equipo.

## 1. Bus de eventos (Redis Pub/Sub)

- **Canal único:** `saga.eventos`
- **Formato de mensaje (envelope JSON):**

```json
{
  "tipo": "SaldoDebitado",
  "idempotency_key": "3f2a1c9e-...-uuid4",
  "timestamp": "2026-09-12T15:04:05.123Z",
  "origen_servicio": "cuentas-y-saldos",
  "data": { "...": "payload específico del evento" }
}
```

- Todo servicio se suscribe al canal completo y filtra por `tipo`.
- `idempotency_key` va SIEMPRE en el sobre (no solo dentro de `data`), porque es la clave
  de correlación de toda la saga y la clave de deduplicación (CP-05).
- **Propagación de contexto (event-carried state transfer):** todo evento incluye, además de
  su payload propio, un objeto `contexto` con `{origen, destino, monto, flags_fallo}` copiado
  del `TransferenciaSolicitada` original. Así ningún servicio necesita recordar o consultar
  estado ajeno para reaccionar — cada evento es autosuficiente. Esto es lo que permite probar
  cada servicio de forma aislada (ver `tests/` de cada servicio) sin depender de que los demás
  ya estén implementados.

## 2. Catálogo de eventos de dominio (nombres exactos)

Todas las filas de abajo llevan además `contexto: {origen, destino, monto, flags_fallo}` (ver arriba).

| Evento | Quién lo emite | `data` propio (además de `contexto`) | Dispara en |
|---|---|---|---|
| `TransferenciaSolicitada` | Gateway (entrada a la saga) | `{modo}` | Inicio de toda transacción |
| `SaldoDebitado` | Cuentas y Saldos | `{}` | Fondos suficientes, débito aplicado |
| `RiesgoAprobado` | Riesgo y Antifraude | `{}` | Validación de riesgo OK |
| `RiesgoRechazado` | Riesgo y Antifraude | `{motivo}` | `forzar_fraude=true` o regla de riesgo activada |
| `LiquidacionConfirmada` | Pasarela Interbancaria | `{}` | Liquidación externa simulada con éxito |
| `TransferenciaFallida` | Cuentas (fondos) o Pasarela (red) | `{motivo, origen_fallo}` | `motivo`: `"fondos_insuficientes"` \| `"timeout_red"` |
| `CompensacionEjecutada` | Cualquier servicio que compensa | `{servicio, accion}` | Reversa de débito, anulación de aprobación de riesgo, etc. |

`motivo` valores estándar: `fondos_insuficientes`, `fraude_detectado`, `timeout_red`.
`accion` valores estándar: `reversa_debito`, `anulacion_riesgo`.

## 3. Flujo de reacciones esperado (quién escucha qué)

```
TransferenciaSolicitada
  -> Cuentas: valida saldo
       si insuficiente -> TransferenciaFallida{motivo: fondos_insuficientes}  (CP-02, sin compensación)
       si suficiente    -> debita -> SaldoDebitado

SaldoDebitado
  -> Riesgo: evalúa (o forzar_fraude)
       si fraude -> RiesgoRechazado{motivo: fraude_detectado}                 (CP-03)
       si ok     -> RiesgoAprobado

RiesgoRechazado
  -> Cuentas: reversa el débito -> CompensacionEjecutada{cuentas, reversa_debito}
  -> Estado final: RECHAZADO_RIESGO

RiesgoAprobado
  -> Pasarela: simula liquidación (delay 2-4s)
       si forzar_timeout -> TransferenciaFallida{motivo: timeout_red, origen_fallo: pasarela}  (CP-04)
       si ok             -> LiquidacionConfirmada

TransferenciaFallida{origen_fallo: pasarela}
  -> Riesgo:  anula aprobación -> CompensacionEjecutada{riesgo, anulacion_riesgo}
  -> Cuentas: reversa débito   -> CompensacionEjecutada{cuentas, reversa_debito}
  -> Estado final: RECHAZADO_RED

LiquidacionConfirmada
  -> Cuentas: acredita destino -> Estado final: CONFIRMADO
```

## 4. Estados de una transacción (para pintar igual en el frontend sin importar el modo)

```
EN_EJECUCION     -> en curso, sin resultado final todavía
CONFIRMADO       -> CP-01: éxito total
RECHAZADO_FONDOS -> CP-02: rechazo inmediato, sin compensación (nada que revertir)
RECHAZADO_RIESGO -> CP-03: rechazo por fraude, con compensación de débito
RECHAZADO_RED    -> CP-04: rechazo por caída de red externa, con doble compensación
COMPENSADO       -> paso intermedio: se muestra en el timeline en el instante en que
                     llega un CompensacionEjecutada, antes de asentarse en el estado final
                     RECHAZADO_RIESGO / RECHAZADO_RED (así el usuario ve la reversa ocurrir)
```

El campo que persiste como estado final de la fila es siempre uno de los 6 valores de arriba.
`COMPENSADO` puede aparecer en el `historial` de pasos aunque el `estado_final` sea
`RECHAZADO_RIESGO` o `RECHAZADO_RED` — así ambas rúbricas (estados + trazabilidad) quedan cubiertas.

## 5. Idempotencia (CP-05)

- Clave: `idem:{idempotency_key}` en Redis (`SETNX` con TTL de 24h) marcada al **recibir**
  `TransferenciaSolicitada` la primera vez.
- Si el Gateway recibe una petición `POST /transferencia` con un `idempotency_key` ya visto,
  **no vuelve a publicar** `TransferenciaSolicitada`: responde de inmediato con el estado actual
  almacenado (sin doble cobro, sin doble ejecución).
- Cada servicio que reacciona a un evento también debe ser idempotente a nivel de handler
  (ignorar el mismo evento si ya lo procesó), usando `procesado:{idempotency_key}:{tipo}` en Redis.

## 6. Contrato HTTP (API Gateway / entrypoints)

### Modo Coreografiado — `services/gateway-coreografia` (puerto `8100`)

```
POST /transferencia
  body: { "origen": str, "destino": str, "monto": number,
          "idempotency_key": str | null,   # si es null, el gateway genera un UUID
          "flags_fallo": { "forzar_fraude": bool, "forzar_timeout": bool } }
  200: { "idempotency_key": str, "estado": "EN_EJECUCION" | ... }

GET /transferencia/{idempotency_key}/estado
  200: { "idempotency_key": str, "estado": str, "historial": [ {tipo, timestamp, origen_servicio} ] }
```

### Modo Orquestado — expuesto por Sofía (puerto `8200`, mismo contrato de request/response)

El frontend usa el **mismo body y la misma forma de respuesta** contra la URL base que
corresponda al modo elegido (`Orquestada` -> `:8200`, `Coreografiada` -> `:8100`), y hace
`polling` cada 1-2s a `GET /transferencia/{idempotency_key}/estado` hasta llegar a un estado
terminal (`CONFIRMADO`, `RECHAZADO_FONDOS`, `RECHAZADO_RIESGO`, `RECHAZADO_RED`).

### Pasarela Interbancaria — `services/pasarela-interbancaria` (puerto `8300`)

Servicio reactivo (no expone un endpoint de negocio directo desde el frontend); solo:

```
GET /health
GET /auditoria/{idempotency_key}   # bitácora local de liquidaciones simuladas
```
