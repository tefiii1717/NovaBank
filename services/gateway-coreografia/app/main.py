import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import aggregator, db
from .models import PasoHistorial, RespuestaEstado, RespuestaTransferencia, SolicitudTransferencia
from .redis_bus import publicar

logging.basicConfig(level=logging.INFO)

SERVICIO = "gateway-coreografia"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.inicializar()
    tarea = asyncio.create_task(aggregator.escuchar())
    yield
    tarea.cancel()


app = FastAPI(title="Gateway Coreografía (entrypoint saga coreografiada)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICIO}


@app.post("/transferencia", response_model=RespuestaTransferencia)
async def crear_transferencia(payload: SolicitudTransferencia):
    idem = payload.idempotency_key or str(uuid.uuid4())
    contexto = {
        "origen": payload.origen,
        "destino": payload.destino,
        "monto": payload.monto,
        "flags_fallo": payload.flags_fallo.model_dump(),
    }

    es_nueva = db.crear_transaccion_si_no_existe(idem, contexto)
    if es_nueva:
        await publicar("TransferenciaSolicitada", idem, contexto, {"modo": "coreografia"}, SERVICIO)
    else:
        logging.getLogger("gateway.main").info(
            "CP-05: idempotency_key %s ya procesada, no se vuelve a publicar", idem
        )

    fila = db.obtener_transaccion(idem)
    return RespuestaTransferencia(idempotency_key=idem, estado=fila["estado"])


@app.get("/transferencia/{idempotency_key}/estado", response_model=RespuestaEstado)
async def obtener_estado(idempotency_key: str):
    fila = db.obtener_transaccion(idempotency_key)
    if not fila:
        raise HTTPException(status_code=404, detail="transacción no encontrada")

    historial = db.obtener_historial(idempotency_key)
    return RespuestaEstado(
        idempotency_key=idempotency_key,
        estado=fila["estado"],
        origen=fila["origen"],
        destino=fila["destino"],
        monto=fila["monto"],
        historial=[
            PasoHistorial(
                tipo=paso["tipo"],
                estado_paso=paso["estado_paso"],
                timestamp=paso["timestamp"],
                origen_servicio=paso["origen_servicio"],
                data=paso["data"],
            )
            for paso in historial
        ],
    )
