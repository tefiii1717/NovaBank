from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Stub temporal - Pasarela Interbancaria")


class LiquidarRequest(BaseModel):
    cuenta_destino: str
    monto: float
    idempotency_key: str
    forzar_timeout: bool = False


@app.post("/liquidar")
def liquidar(req: LiquidarRequest):
    if req.forzar_timeout:
        raise HTTPException(status_code=504, detail="RECHAZADO_RED: timeout simulado")
    return {"status": "ok", "resultado": "LIQUIDADO"}
