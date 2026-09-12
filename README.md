# NovaBank International — Saga Bancaria (Coreografía vs. Orquestación)

Taller de arquitectura: transferencias interbancarias implementadas con el
**Patrón Saga** en dos modalidades — **Coreografiada** (Redis Pub/Sub, sin
coordinador central) y **Orquestada** (Prefect) — con compensaciones en orden
inverso y observabilidad de cada paso.

Equipo: Tefi (orquestación + observabilidad Prefect) y Yuly (frontend, pasarela
interbancaria, bus de eventos y saga coreografiada).

## Estado actual del repositorio

| Componente | Dueño | Estado |
|---|---|---|
| `frontend/` (React + Tailwind) | Yuly | ✅ Implementado |
| `services/pasarela-interbancaria/` (Clearing Gateway) | Yuly | ✅ Implementado |
| `services/gateway-coreografia/` (entrypoint + read model de la saga coreografiada) | Yuly | ✅ Implementado |
| `docs/CONTRATO_EVENTOS.md` (contrato de eventos y API) | Yuly | ✅ Implementado |
| `services/cuentas-y-saldos/` (Account & Ledger) | Tefi | ⬜ Pendiente |
| `services/riesgo-antifraude/` | Tefi | ⬜ Pendiente |
| Saga Orquestada (Prefect) + API Gateway `:8200` | Tefi | ⬜ Pendiente |

**Importante:** sin los servicios de Cuentas y Riesgo, la saga coreografiada no
puede completarse de punta a punta con datos reales — pero todo lo que depende de
Yuly está construido, probado y verificado (ver "Cómo se verificó" más abajo). El
contrato de eventos (`docs/CONTRATO_EVENTOS.md`) es lo único que Tefi necesita
respetar para que sus servicios encajen sin tocar nada de lo ya construido.

## Arquitectura (las 4 capas del taller)

1. **Frontend / Simulador de caos** (`frontend/`): formulario de transferencia,
   switches para forzar cada tipo de fallo (CP-02 a CP-04), selector de modo
   (Coreografiada / Orquestada) y panel de estado en tiempo real por *polling*.
2. **API Gateway**: en modo coreografiado es `services/gateway-coreografia`
   (puerto `8100`); en modo orquestado lo expone Tefi (puerto `8200`) — mismo
   contrato HTTP en ambos, ver `docs/CONTRATO_EVENTOS.md` §6.
3. **Microservicios de dominio bancario**: `pasarela-interbancaria` (Yuly, este
   repo) + `cuentas-y-saldos` y `riesgo-antifraude` (Tefi, pendientes).
4. **Observabilidad**: en coreografía, cada paso queda en la tabla `historial`
   de `gateway-coreografia` con timestamp y servicio de origen, visible en el
   timeline del frontend; en orquestación, la UI de Prefect (Tefi).

## Cómo correr todo

Requiere Docker Desktop.

```bash
docker compose up -d --build
```

Esto levanta: `redis`, `pasarela-interbancaria` (`:8300`), `gateway-coreografia`
(`:8100`) y `frontend` (`:5173`). Abre `http://localhost:5173`.

Los servicios de Tefi (Cuentas, Riesgo, Prefect, API Gateway orquestado) se
agregan en `docker-compose.yml`, en el bloque comentado al final del archivo —
sin ellos, el modo "Orquestada" del frontend y el flujo coreografiado completo
(que necesita Cuentas y Riesgo reaccionando) no van a completar la transacción.

### Correr solo el backend de Yuly sin Docker (desarrollo)

```bash
# Redis real (o docker run -p 6379:6379 redis:7-alpine)
cd services/pasarela-interbancaria && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m uvicorn app.main:app --port 8300

cd services/gateway-coreografia && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
REDIS_URL=redis://localhost:6379/0 .venv/Scripts/python -m uvicorn app.main:app --port 8100

cd frontend && npm install && npm run dev
```

## Matriz de casos de prueba

| ID | Escenario | Cómo probarlo en el frontend |
|---|---|---|
| CP-01 | Camino feliz | Enviar sin switches activados |
| CP-02 | Fondos insuficientes | Activar "CP-02 · Fondos insuficientes" |
| CP-03 | Fraude / riesgo | Activar "CP-03 · Forzar fraude" |
| CP-04 | Timeout de red externa | Activar "CP-04 · Forzar timeout de red" |
| CP-05 | Idempotencia / reintento | Botón "Reusar último ID (CP-05)" y reenviar |

CP-02, CP-03 y el resto de la saga completa (débito/crédito reales) requieren los
servicios de Cuentas y Riesgo de Tefi corriendo y suscritos al mismo canal Redis
(`saga.eventos`) — ver `docs/CONTRATO_EVENTOS.md`.

## Cómo se verificó (sin los servicios de Tefi)

1. **Pruebas unitarias** (no requieren Docker ni Redis real, usan `fakeredis`):
   ```bash
   cd services/pasarela-interbancaria && .venv/Scripts/python -m pytest
   cd services/gateway-coreografia && .venv/Scripts/python -m pytest
   ```
   Cubren CP-01 a CP-05 simulando a Cuentas/Riesgo como "dobles" que respetan el
   contrato de eventos (así se prueba el aislamiento real de cada servicio).

2. **Verificación E2E contra el stack real** (Docker + Redis real + la Pasarela
   real reaccionando con su delay de 2-4s):
   ```bash
   docker compose up -d redis pasarela-interbancaria gateway-coreografia
   python scripts/probar_cp_coreografia.py
   ```
   Este script simula únicamente lo que Cuentas y Riesgo publicarían, y deja que
   la Pasarela real (Yuly) reaccione de verdad — confirmado pasando los 5 CP.

3. **Frontend en navegador** contra el stack real: transferencia enviada desde la
   UI, estado inicial `EN_EJECUCION`, eventos simulados de Cuentas/Riesgo vía
   Redis, la Pasarela real resuelve tras su delay, y el timeline del frontend
   muestra cada paso hasta `CONFIRMADO` (CP-01) y `RECHAZADO_RED` con
   compensaciones (CP-04).

## Documentos del taller

- [`docs/CONTRATO_EVENTOS.md`](docs/CONTRATO_EVENTOS.md) — contrato de eventos y API (fuente de verdad para ambos).
- [`docs/COMPARATIVA_ORQUESTACION_VS_COREOGRAFIA.md`](docs/COMPARATIVA_ORQUESTACION_VS_COREOGRAFIA.md) — comparativa de los dos enfoques.

## Variables de entorno

Ver `.env.example` en `frontend/` y las variables `REDIS_URL`,
`PASARELA_DB_PATH`, `GATEWAY_DB_PATH`, `PASARELA_DELAY_MIN/MAX` documentadas en
cada `Dockerfile` / `docker-compose.yml`.
