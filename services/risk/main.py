from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, get_db, Base
from models import RiskValidation

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Servicio de Riesgo y Antifraude")

LIMITE_DIARIO = 5000.0


class ValidarRiesgoRequest(BaseModel):
    numero_cuenta: str
    monto: float
    idempotency_key: str
    forzar_fraude: bool = False


def _validar_riesgo(db: Session, numero_cuenta: str, monto: float, idempotency_key: str, forzar_fraude: bool) -> dict:
    """Lógica pura de validación, reutilizada por el endpoint HTTP (orquestación)
    y por el listener de Redis (coreografía, reacciona a SaldoDebitado) — ver
    redis_listener.py."""
    ya_procesada = db.query(RiskValidation).filter(
        RiskValidation.idempotency_key == idempotency_key
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    if forzar_fraude:
        registro = RiskValidation(
            idempotency_key=idempotency_key, numero_cuenta=numero_cuenta,
            monto=monto, resultado="RECHAZADO_RIESGO",
        )
        db.add(registro)
        db.commit()
        return {"status": "rechazado", "motivo": "fraude_detectado"}

    if monto > LIMITE_DIARIO:
        registro = RiskValidation(
            idempotency_key=idempotency_key, numero_cuenta=numero_cuenta,
            monto=monto, resultado="RECHAZADO_RIESGO",
        )
        db.add(registro)
        db.commit()
        return {"status": "rechazado", "motivo": "limite_diario_excedido"}

    registro = RiskValidation(
        idempotency_key=idempotency_key, numero_cuenta=numero_cuenta,
        monto=monto, resultado="APROBADO",
    )
    db.add(registro)
    db.commit()
    return {"status": "ok", "resultado": "APROBADO"}


@app.post("/validar-riesgo")
def validar_riesgo(req: ValidarRiesgoRequest, db: Session = Depends(get_db)):
    resultado = _validar_riesgo(db, req.numero_cuenta, req.monto, req.idempotency_key, req.forzar_fraude)
    if resultado["status"] == "rechazado":
        detalle = (
            "RECHAZADO_RIESGO" if resultado["motivo"] == "fraude_detectado"
            else "RECHAZADO_RIESGO: excede limite diario"
        )
        raise HTTPException(status_code=400, detail=detalle)
    return resultado


class AnularRequest(BaseModel):
    idempotency_key: str


def _anular_riesgo(db: Session, idempotency_key: str) -> dict:
    clave_anulacion = f"anulacion-{idempotency_key}"
    ya_procesada = db.query(RiskValidation).filter(
        RiskValidation.idempotency_key == clave_anulacion
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    registro = RiskValidation(
        idempotency_key=clave_anulacion, numero_cuenta="N/A", monto=0.0, resultado="ANULADO",
    )
    db.add(registro)
    db.commit()
    return {"status": "ok", "resultado": "ANULADO"}


@app.post("/anular-riesgo")
def anular_riesgo(req: AnularRequest, db: Session = Depends(get_db)):
    return _anular_riesgo(db, req.idempotency_key)


@app.on_event("startup")
def _iniciar_listener_redis() -> None:
    from redis_listener import iniciar_en_segundo_plano
    iniciar_en_segundo_plano()
