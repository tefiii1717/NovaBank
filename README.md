# NovaBank International — Saga Bancaria (Coreografía vs. Orquestación)

Taller de arquitectura: transferencias interbancarias implementadas con el
**Patrón Saga** en dos modalidades — **Coreografiada** (Redis Pub/Sub, sin
coordinador central) y **Orquestada** (Prefect) — con compensaciones en orden
inverso y observabilidad de cada paso.

Equipo: Sofía (orquestación + observabilidad Prefect) y Yuly (frontend, pasarela
interbancaria, bus de eventos y saga coreografiada).

## Estado actual del repositorio

| Componente | Dueño | Estado |
|---|---|---|
| `frontend/` (React + Tailwind) | Yuly | ✅ Implementado |
| `services/pasarela-interbancaria/` (Clearing Gateway, reactiva a eventos) | Yuly | ✅ Implementado |
| `services/gateway-coreografia/` (entrypoint + read model de la saga coreografiada) | Yuly | ✅ Implementado |
| `docs/CONTRATO_EVENTOS.md` (contrato de eventos y API) | Yuly | ✅ Implementado |
| `services/accounts/` (Cuentas y Saldos) | Sofía | ✅ Implementado |
| `services/risk/` (Riesgo y Antifraude) | Sofía | ✅ Implementado |
| `services/clearing-stub/` (stub de pasarela para el modo orquestado) | Sofía | ✅ Implementado |
| `saga-orchestrator/flows.py` (saga orquestada con Prefect) | Sofía | ✅ Implementado |
| `saga-orchestrator/api.py` (API Gateway orquestada, puerto `:8200`) | Yuly (wrapper sobre el flow de Sofía) | ✅ Implementado |
| `services/accounts/redis_listener.py`, `services/risk/redis_listener.py` (reacción a `saga.eventos`) | Yuly (agregado sobre el código de Sofía) | ✅ Implementado |

**Los dos modos (Coreografiada y Orquestada) funcionan de punta a punta contra
el stack real, con los 5 casos de prueba pasando en ambos y sin ningún evento
o servicio simulado** (ver "Cómo se verificó" más abajo). `accounts` y `risk`
ahora exponen dos caminos hacia la misma lógica de negocio: sus endpoints HTTP
de siempre (que usa el flow orquestado) y un listener de Redis que reacciona
solo a `saga.eventos` (que completa la coreografía) — ver
`docs/CONTRATO_EVENTOS.md`.

## Arquitectura (las 4 capas del taller)

1. **Frontend / Simulador de caos** (`frontend/`): formulario de transferencia,
   switches para forzar cada tipo de fallo (CP-02 a CP-04), selector de modo
   (Coreografiada / Orquestada) y panel de estado en tiempo real por *polling*.
2. **API Gateway**: en modo coreografiado es `services/gateway-coreografia`
   (puerto `8100`); en modo orquestado es `saga-orchestrator/api.py` (puerto
   `8200`) — mismo contrato HTTP en ambos, ver `docs/CONTRATO_EVENTOS.md` §6.
3. **Microservicios de dominio bancario**: `pasarela-interbancaria` (Yuly) +
   `accounts` y `risk` (Sofía) + `clearing-stub` (Sofía, pasarela síncrona para
   el flow orquestado).
4. **Observabilidad**: en coreografía, cada paso queda en la tabla `historial`
   de `gateway-coreografia` con timestamp y servicio de origen; en
   orquestación, el flow corre como un `@flow`/`@task` de Prefect (UI en
   `http://localhost:4200`) y `saga-orchestrator/api.py` traduce el resultado
   al mismo formato de `historial` para que el frontend pinte igual en ambos
   modos.

## Cómo correr todo

Requiere Docker Desktop.

```bash
docker compose up -d --build
```

Esto levanta los 9 servicios: `redis`, `pasarela-interbancaria` (`:8300`),
`gateway-coreografia` (`:8100`), `accounts` (`:8001`), `risk` (`:8002`),
`clearing-stub` (`:8003`), `prefect-server` (`:4200`), `saga-orchestrator`
(`:8200`) y `frontend` (`:5173`). Abre `http://localhost:5173`.

`accounts` no trae cuentas de prueba por defecto — créalas antes de probar:

```bash
curl -X POST http://localhost:8001/cuentas -H "Content-Type: application/json" -d '{"numero_cuenta":"CTA-001","saldo_inicial":1000}'
curl -X POST http://localhost:8001/cuentas -H "Content-Type: application/json" -d '{"numero_cuenta":"CTA-002","saldo_inicial":100}'
```

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

Los 5 casos están verificados contra **ambos modos reales**, sin dobles de
prueba: Orquestada (Prefect + accounts + risk + clearing-stub) y Coreografiada
(gateway-coreografia + accounts + risk + pasarela-interbancaria, todos
reaccionando solos vía Redis).

## Cómo se verificó

1. **Pruebas unitarias** de la parte coreografiada (no requieren Docker ni Redis
   real, usan `fakeredis`):
   ```bash
   cd services/pasarela-interbancaria && .venv/Scripts/python -m pytest
   cd services/gateway-coreografia && .venv/Scripts/python -m pytest
   ```
   Cubren CP-01 a CP-05 simulando a `accounts`/`risk` como "dobles" que respetan
   el contrato de eventos (así se prueba el aislamiento real de cada servicio).

2. **Coreografía E2E contra el stack real** (Docker completo — redis, accounts,
   risk, pasarela-interbancaria y gateway-coreografia, todos reales, ningún
   evento simulado):
   ```bash
   docker compose up -d --build
   python scripts/probar_cp_coreografia.py
   ```
   Crea las cuentas de prueba y corre los 5 CP contra el bus de eventos real
   — accounts y risk reaccionan solos, sin que el script les diga qué hacer.

3. **Orquestación E2E contra el stack real** (Prefect + accounts + risk +
   clearing-stub, sin ningún doble de prueba):
   ```bash
   docker compose up -d --build
   curl -X POST http://localhost:8001/cuentas -H "Content-Type: application/json" -d '{"numero_cuenta":"CTA-001","saldo_inicial":1000}'
   curl -X POST http://localhost:8001/cuentas -H "Content-Type: application/json" -d '{"numero_cuenta":"CTA-002","saldo_inicial":100}'
   curl -X POST http://localhost:8200/transferencia -H "Content-Type: application/json" -d '{"origen":"CTA-001","destino":"CTA-002","monto":100}'
   # copiar el idempotency_key de la respuesta y consultar:
   curl http://localhost:8200/transferencia/<idempotency_key>/estado
   ```
   Los 5 CP se probaron así manualmente (CP-01 → CONFIRMADO, CP-02 →
   RECHAZADO_FONDOS, CP-03 → RECHAZADO_RIESGO con compensación, CP-04 →
   RECHAZADO_RED con doble compensación, CP-05 → mismo idempotency_key no
   duplica la ejecución).

4. **Frontend en navegador** contra el stack real, en ambos modos: transferencia
   enviada desde la UI, estado inicial `EN_EJECUCION`, y el timeline mostrando
   los 4 pasos reales (accounts → risk → pasarela/clearing) hasta `CONFIRMADO`
   — confirmado tanto en Coreografiada como en Orquestada.

## Documentos del taller

- [`docs/CONTRATO_EVENTOS.md`](docs/CONTRATO_EVENTOS.md) — contrato de eventos y API (fuente de verdad para ambos).
- [`docs/COMPARATIVA_ORQUESTACION_VS_COREOGRAFIA.md`](docs/COMPARATIVA_ORQUESTACION_VS_COREOGRAFIA.md) — comparativa de los dos enfoques.

## Variables de entorno

Ver `.env.example` en `frontend/` y las variables `REDIS_URL`,
`PASARELA_DB_PATH`, `GATEWAY_DB_PATH`, `PASARELA_DELAY_MIN/MAX` documentadas en
cada `Dockerfile` / `docker-compose.yml`.
