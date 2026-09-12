from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, get_db, Base
from models import Account, ProcessedRequest

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Servicio de Cuentas y Saldos")


class CrearCuentaRequest(BaseModel):
    numero_cuenta: str
    saldo_inicial: float


@app.post("/cuentas")
def crear_cuenta(req: CrearCuentaRequest, db: Session = Depends(get_db)):
    existente = db.query(Account).filter(Account.numero_cuenta == req.numero_cuenta).first()
    if existente:
        raise HTTPException(status_code=400, detail="La cuenta ya existe")

    cuenta = Account(numero_cuenta=req.numero_cuenta, saldo=req.saldo_inicial)
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return {"numero_cuenta": cuenta.numero_cuenta, "saldo": cuenta.saldo}


class DebitoRequest(BaseModel):
    numero_cuenta: str
    monto: float
    idempotency_key: str


@app.post("/debitar")
def debitar(req: DebitoRequest, db: Session = Depends(get_db)):
    ya_procesada = db.query(ProcessedRequest).filter(
        ProcessedRequest.idempotency_key == req.idempotency_key
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    cuenta = db.query(Account).filter(Account.numero_cuenta == req.numero_cuenta).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    if cuenta.saldo < req.monto:
        registro = ProcessedRequest(idempotency_key=req.idempotency_key, resultado="RECHAZADO_FONDOS")
        db.add(registro)
        db.commit()
        raise HTTPException(status_code=400, detail="RECHAZADO_FONDOS")

    cuenta.saldo -= req.monto
    registro = ProcessedRequest(idempotency_key=req.idempotency_key, resultado="DEBITADO")
    db.add(registro)
    db.commit()
    return {"status": "ok", "numero_cuenta": cuenta.numero_cuenta, "saldo": cuenta.saldo}


class ReversaRequest(BaseModel):
    numero_cuenta: str
    monto: float
    idempotency_key: str


@app.post("/reversar")
def reversar(req: ReversaRequest, db: Session = Depends(get_db)):
    clave_reversa = f"reversa-{req.idempotency_key}"
    ya_procesada = db.query(ProcessedRequest).filter(
        ProcessedRequest.idempotency_key == clave_reversa
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    cuenta = db.query(Account).filter(Account.numero_cuenta == req.numero_cuenta).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    cuenta.saldo += req.monto
    registro = ProcessedRequest(idempotency_key=clave_reversa, resultado="COMPENSADO")
    db.add(registro)
    db.commit()
    return {"status": "ok", "numero_cuenta": cuenta.numero_cuenta, "saldo": cuenta.saldo}
