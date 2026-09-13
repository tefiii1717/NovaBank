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


def _debitar(db: Session, numero_cuenta: str, monto: float, idempotency_key: str) -> dict:
    """Lógica pura de débito, reutilizada tanto por el endpoint HTTP (orquestación,
    llamada directa desde flows.py) como por el listener de Redis (coreografía,
    reacciona a TransferenciaSolicitada) — ver redis_listener.py."""
    ya_procesada = db.query(ProcessedRequest).filter(
        ProcessedRequest.idempotency_key == idempotency_key
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    cuenta = db.query(Account).filter(Account.numero_cuenta == numero_cuenta).first()
    if not cuenta:
        return {"status": "cuenta_no_encontrada"}

    if cuenta.saldo < monto:
        registro = ProcessedRequest(idempotency_key=idempotency_key, resultado="RECHAZADO_FONDOS")
        db.add(registro)
        db.commit()
        return {"status": "rechazado_fondos"}

    cuenta.saldo -= monto
    registro = ProcessedRequest(idempotency_key=idempotency_key, resultado="DEBITADO")
    db.add(registro)
    db.commit()
    return {"status": "ok", "numero_cuenta": cuenta.numero_cuenta, "saldo": cuenta.saldo}


@app.post("/debitar")
def debitar(req: DebitoRequest, db: Session = Depends(get_db)):
    resultado = _debitar(db, req.numero_cuenta, req.monto, req.idempotency_key)
    if resultado["status"] == "cuenta_no_encontrada":
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if resultado["status"] == "rechazado_fondos":
        raise HTTPException(status_code=400, detail="RECHAZADO_FONDOS")
    return resultado


class ReversaRequest(BaseModel):
    numero_cuenta: str
    monto: float
    idempotency_key: str


def _reversar(db: Session, numero_cuenta: str, monto: float, idempotency_key: str) -> dict:
    clave_reversa = f"reversa-{idempotency_key}"
    ya_procesada = db.query(ProcessedRequest).filter(
        ProcessedRequest.idempotency_key == clave_reversa
    ).first()
    if ya_procesada:
        return {"status": "duplicado", "resultado": ya_procesada.resultado}

    cuenta = db.query(Account).filter(Account.numero_cuenta == numero_cuenta).first()
    if not cuenta:
        return {"status": "cuenta_no_encontrada"}

    cuenta.saldo += monto
    registro = ProcessedRequest(idempotency_key=clave_reversa, resultado="COMPENSADO")
    db.add(registro)
    db.commit()
    return {"status": "ok", "numero_cuenta": cuenta.numero_cuenta, "saldo": cuenta.saldo}


@app.post("/reversar")
def reversar(req: ReversaRequest, db: Session = Depends(get_db)):
    resultado = _reversar(db, req.numero_cuenta, req.monto, req.idempotency_key)
    if resultado["status"] == "cuenta_no_encontrada":
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return resultado


@app.on_event("startup")
def _iniciar_listener_redis() -> None:
    # Import diferido: evita el ciclo de import con redis_listener (que a su vez
    # importa _debitar/_reversar de este módulo).
    from redis_listener import iniciar_en_segundo_plano
    iniciar_en_segundo_plano()
