import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import db
from .listener import escuchar

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.inicializar()
    tarea = asyncio.create_task(escuchar())
    yield
    tarea.cancel()


app = FastAPI(title="Pasarela Interbancaria (Clearing Gateway)", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pasarela-interbancaria"}


@app.get("/auditoria/{idempotency_key}")
async def auditoria(idempotency_key: str):
    registro = db.obtener(idempotency_key)
    if not registro:
        raise HTTPException(status_code=404, detail="no encontrado")
    return registro
