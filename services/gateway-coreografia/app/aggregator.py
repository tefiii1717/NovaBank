"""
Escucha TODOS los eventos del bus (saga.eventos) y mantiene la foto de estado de
cada transacción (tabla `transacciones` + `historial`) para que el frontend pueda
hacer polling de GET /transferencia/{id}/estado sin depender de un orquestador
central — este es el "read model" propio de la saga coreografiada.
"""
import logging
from typing import Any, Dict, Optional, Tuple

from . import db
from .redis_bus import suscribirse

logger = logging.getLogger("gateway.aggregator")


def _estado_paso_y_final(evento: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Devuelve (estado_paso_para_historial, estado_final_o_None).

    `estado_final` solo se asienta en la columna `estado` cuando el evento
    representa una decisión de negocio definitiva. `CompensacionEjecutada` NUNCA
    pisa el estado final ya asentado (RECHAZADO_RIESGO / RECHAZADO_RED): solo se
    ve reflejado como paso 'COMPENSADO' en el historial, que es lo que el
    frontend muestra en tiempo real mientras ocurre la reversa.
    """
    tipo = evento["tipo"]
    data = evento.get("data", {})

    if tipo in ("TransferenciaSolicitada", "SaldoDebitado", "RiesgoAprobado"):
        return "EN_EJECUCION", None
    if tipo == "RiesgoRechazado":
        return "RECHAZADO_RIESGO", "RECHAZADO_RIESGO"
    if tipo == "LiquidacionConfirmada":
        return "CONFIRMADO", "CONFIRMADO"
    if tipo == "TransferenciaFallida":
        motivo = data.get("motivo")
        if motivo == "fondos_insuficientes":
            return "RECHAZADO_FONDOS", "RECHAZADO_FONDOS"
        return "RECHAZADO_RED", "RECHAZADO_RED"
    if tipo == "CompensacionEjecutada":
        return "COMPENSADO", None
    return "EN_EJECUCION", None


async def procesar_evento(evento: Dict[str, Any]) -> None:
    idem = evento["idempotency_key"]
    contexto = evento.get("contexto", {})

    # Idempotente: si la fila ya existe (caso normal, creada por el propio POST
    # /transferencia), esto no hace nada.
    db.crear_transaccion_si_no_existe(idem, contexto)

    estado_paso, estado_final = _estado_paso_y_final(evento)
    db.agregar_paso(
        idem,
        evento["tipo"],
        estado_paso,
        evento.get("origen_servicio", "desconocido"),
        evento.get("timestamp", ""),
        evento.get("data", {}),
    )
    if estado_final:
        db.actualizar_estado(idem, estado_final)
        logger.info("Transacción %s -> %s", idem, estado_final)


async def escuchar() -> None:
    async for evento in suscribirse():
        try:
            await procesar_evento(evento)
        except Exception:
            logger.exception("Error procesando evento en el agregador: %s", evento)
