from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TipoEvento(str, Enum):
    TRANSFERENCIA_SOLICITADA = "TransferenciaSolicitada"
    SALDO_DEBITADO = "SaldoDebitado"
    RIESGO_APROBADO = "RiesgoAprobado"
    RIESGO_RECHAZADO = "RiesgoRechazado"
    LIQUIDACION_CONFIRMADA = "LiquidacionConfirmada"
    TRANSFERENCIA_FALLIDA = "TransferenciaFallida"
    COMPENSACION_EJECUTADA = "CompensacionEjecutada"


class EstadoTransaccion(str, Enum):
    EN_EJECUCION = "EN_EJECUCION"
    CONFIRMADO = "CONFIRMADO"
    RECHAZADO_FONDOS = "RECHAZADO_FONDOS"
    RECHAZADO_RIESGO = "RECHAZADO_RIESGO"
    RECHAZADO_RED = "RECHAZADO_RED"
    COMPENSADO = "COMPENSADO"


class FlagsFallo(BaseModel):
    forzar_fraude: bool = False
    forzar_timeout: bool = False


class SolicitudTransferencia(BaseModel):
    origen: str
    destino: str
    monto: float
    idempotency_key: Optional[str] = None
    flags_fallo: FlagsFallo = Field(default_factory=FlagsFallo)


class PasoHistorial(BaseModel):
    tipo: str
    estado_paso: str
    timestamp: str
    origen_servicio: str
    data: Dict[str, Any] = Field(default_factory=dict)


class RespuestaTransferencia(BaseModel):
    idempotency_key: str
    estado: EstadoTransaccion


class RespuestaEstado(BaseModel):
    idempotency_key: str
    estado: EstadoTransaccion
    origen: str
    destino: str
    monto: float
    historial: List[PasoHistorial]


class Envelope(BaseModel):
    tipo: TipoEvento
    idempotency_key: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    origen_servicio: str
    contexto: Dict[str, Any]
    data: Dict[str, Any] = Field(default_factory=dict)
