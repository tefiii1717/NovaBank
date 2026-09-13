"""
API Gateway de la Saga Orquestada — envuelve `saga_transferencia` (el @flow de
Prefect en flows.py) con el MISMO contrato HTTP que gateway-coreografia
(docs/CONTRATO_EVENTOS.md §6), para que el frontend use un solo formulario
contra cualquiera de los dos modos.

No modifica la lógica de la saga en flows.py (débito/riesgo/liquidación y sus
compensaciones siguen ahí tal cual) — solo la expone por HTTP y traduce su
resultado final a los mismos 6 estados y al mismo formato de `historial` que
usa el modo coreografiado, reconstruyendo los pasos a partir del resultado
(el flow corre de un tirón, así que no hay eventos incrementales reales como
en Redis; se interpolan timestamps entre el inicio y el fin para que el
timeline del frontend siga siendo legible).
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from flows import saga_transferencia

app = FastAPI(title="API Gateway — Saga Orquestada (Prefect)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_transacciones: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


class FlagsFallo(BaseModel):
    forzar_fraude: bool = False
    forzar_timeout: bool = False


class SolicitudTransferencia(BaseModel):
    origen: str
    destino: str
    monto: float
    idempotency_key: Optional[str] = None
    flags_fallo: FlagsFallo = Field(default_factory=FlagsFallo)


def _interpolar(inicio: datetime, fin: datetime, fraccion: float) -> str:
    delta = (fin - inicio) * fraccion
    return (inicio + delta).isoformat()


def _historial_para(status: str, inicio: datetime, fin: datetime) -> List[Dict[str, Any]]:
    pasos: List[Dict[str, Any]] = [
        {
            "tipo": "TransferenciaSolicitada", "estado_paso": "EN_EJECUCION",
            "timestamp": _interpolar(inicio, fin, 0.0),
            "origen_servicio": "api-gateway-orquestado", "data": {"modo": "orquestacion"},
        },
    ]

    if status == "RECHAZADO_FONDOS":
        pasos.append({
            "tipo": "TransferenciaFallida", "estado_paso": "RECHAZADO_FONDOS",
            "timestamp": _interpolar(inicio, fin, 1.0),
            "origen_servicio": "accounts", "data": {"motivo": "fondos_insuficientes"},
        })
        return pasos

    pasos.append({
        "tipo": "SaldoDebitado", "estado_paso": "EN_EJECUCION",
        "timestamp": _interpolar(inicio, fin, 0.33),
        "origen_servicio": "accounts", "data": {},
    })

    if status == "RECHAZADO_RIESGO":
        pasos.append({
            "tipo": "RiesgoRechazado", "estado_paso": "RECHAZADO_RIESGO",
            "timestamp": _interpolar(inicio, fin, 0.66),
            "origen_servicio": "risk", "data": {"motivo": "fraude_detectado"},
        })
        pasos.append({
            "tipo": "CompensacionEjecutada", "estado_paso": "COMPENSADO",
            "timestamp": _interpolar(inicio, fin, 1.0),
            "origen_servicio": "accounts",
            "data": {"servicio": "accounts", "accion": "reversa_debito"},
        })
        return pasos

    pasos.append({
        "tipo": "RiesgoAprobado", "estado_paso": "EN_EJECUCION",
        "timestamp": _interpolar(inicio, fin, 0.5),
        "origen_servicio": "risk", "data": {},
    })

    if status == "RECHAZADO_RED":
        pasos.append({
            "tipo": "TransferenciaFallida", "estado_paso": "RECHAZADO_RED",
            "timestamp": _interpolar(inicio, fin, 0.75),
            "origen_servicio": "clearing-stub",
            "data": {"motivo": "timeout_red", "origen_fallo": "clearing-stub"},
        })
        pasos.append({
            "tipo": "CompensacionEjecutada", "estado_paso": "COMPENSADO",
            "timestamp": _interpolar(inicio, fin, 0.9),
            "origen_servicio": "risk",
            "data": {"servicio": "risk", "accion": "anulacion_riesgo"},
        })
        pasos.append({
            "tipo": "CompensacionEjecutada", "estado_paso": "COMPENSADO",
            "timestamp": _interpolar(inicio, fin, 1.0),
            "origen_servicio": "accounts",
            "data": {"servicio": "accounts", "accion": "reversa_debito"},
        })
        return pasos

    pasos.append({
        "tipo": "LiquidacionConfirmada", "estado_paso": "CONFIRMADO",
        "timestamp": _interpolar(inicio, fin, 1.0),
        "origen_servicio": "clearing-stub", "data": {},
    })
    return pasos


def _ejecutar_en_segundo_plano(
    idem: str, origen: str, destino: str, monto: float, forzar_fraude: bool, forzar_timeout: bool
) -> None:
    inicio = datetime.now(timezone.utc)
    try:
        resultado = saga_transferencia(origen, destino, monto, idem, forzar_fraude, forzar_timeout)
        status = resultado.get("status", "RECHAZADO_RED")
    except Exception:
        status = "RECHAZADO_RED"
    fin = datetime.now(timezone.utc)
    if fin <= inicio:
        fin = inicio + timedelta(seconds=1)

    with _lock:
        registro = _transacciones.get(idem)
        if registro is not None:
            registro["estado"] = status
            registro["historial"] = _historial_para(status, inicio, fin)


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-gateway-orquestado"}


@app.post("/transferencia")
def crear_transferencia(payload: SolicitudTransferencia):
    idem = payload.idempotency_key or str(uuid.uuid4())

    with _lock:
        existente = _transacciones.get(idem)
        if existente is not None:
            return {"idempotency_key": idem, "estado": existente["estado"]}

        _transacciones[idem] = {
            "idempotency_key": idem,
            "origen": payload.origen,
            "destino": payload.destino,
            "monto": payload.monto,
            "estado": "EN_EJECUCION",
            "historial": [],
        }

    hilo = threading.Thread(
        target=_ejecutar_en_segundo_plano,
        args=(
            idem, payload.origen, payload.destino, payload.monto,
            payload.flags_fallo.forzar_fraude, payload.flags_fallo.forzar_timeout,
        ),
        daemon=True,
    )
    hilo.start()

    return {"idempotency_key": idem, "estado": "EN_EJECUCION"}


@app.get("/transferencia/{idempotency_key}/estado")
def obtener_estado(idempotency_key: str):
    with _lock:
        registro = _transacciones.get(idempotency_key)
    if registro is None:
        raise HTTPException(status_code=404, detail="transacción no encontrada")
    return registro
