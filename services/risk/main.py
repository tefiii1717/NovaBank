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


@app.post("/validar-riesgo")
def validar_riesgo(req: ValidarRiesgoRequest, db: Session = Depends(get_db)):
    ya_procesada = db.query(RiskValidation).filter(
        RiskValidation.idempotency_key == req.idempotency_key
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    if req.forzar_fraude:
        registro = RiskValidation(
            idempotency_key=req.idempotency_key,
            numero_cuenta=req.numero_cuenta,
            monto=req.monto,
            resultado="RECHAZADO_RIESGO"
        )
        db.add(registro)
        db.commit()
        raise HTTPException(status_code=400, detail="RECHAZADO_RIESGO")

    if req.monto > LIMITE_DIARIO:
        registro = RiskValidation(
            idempotency_key=req.idempotency_key,
            numero_cuenta=req.numero_cuenta,
            monto=req.monto,
            resultado="RECHAZADO_RIESGO"
        )
        db.add(registro)
        db.commit()
        raise HTTPException(status_code=400, detail="RECHAZADO_RIESGO: excede limite diario")

    registro = RiskValidation(
        idempotency_key=req.idempotency_key,
        numero_cuenta=req.numero_cuenta,
        monto=req.monto,
        resultado="APROBADO"
    )
    db.add(registro)
    db.commit()
    return {"status": "ok", "resultado": "APROBADO"}


class AnularRequest(BaseModel):
    idempotency_key: str


@app.post("/anular-riesgo")
def anular_riesgo(req: AnularRequest, db: Session = Depends(get_db)):
    clave_anulacion = f"anulacion-{req.idempotency_key}"
    ya_procesada = db.query(RiskValidation).filter(
        RiskValidation.idempotency_key == clave_anulacion
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    registro = RiskValidation(
        idempotency_key=clave_anulacion,
        numero_cuenta="N/A",
        monto=0.0,
        resultado="ANULADO"
    )
    db.add(registro)
    db.commit()
    return {"status": "ok", "resultado": "ANULADO"}
