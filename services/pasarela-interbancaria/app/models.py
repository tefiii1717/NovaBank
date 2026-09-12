from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

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


class Contexto(BaseModel):
    origen: str
    destino: str
    monto: float
    flags_fallo: FlagsFallo


class Envelope(BaseModel):
    tipo: TipoEvento
    idempotency_key: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    origen_servicio: str
    contexto: Contexto
    data: Dict[str, Any] = Field(default_factory=dict)
