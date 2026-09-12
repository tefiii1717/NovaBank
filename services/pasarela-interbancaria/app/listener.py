import asyncio
import logging
import os
import random
from typing import Any, Dict

from . import db
from .redis_bus import get_client, publicar, suscribirse

logger = logging.getLogger("pasarela.listener")

DELAY_MIN = float(os.getenv("PASARELA_DELAY_MIN", "2"))
DELAY_MAX = float(os.getenv("PASARELA_DELAY_MAX", "4"))
SERVICIO = "pasarela-interbancaria"


async def _procesado_ya(idempotency_key: str, tipo: str) -> bool:
    clave = f"procesado:{idempotency_key}:{tipo}"
    # SET NX regresa None si la clave ya existía -> ya se proceso antes (CP-05)
    creado = await get_client().set(clave, "1", nx=True, ex=60 * 60 * 24)
    return not creado


async def manejar_riesgo_aprobado(evento: Dict[str, Any]) -> None:
    idem = evento["idempotency_key"]

    if await _procesado_ya(idem, "pasarela:riesgo_aprobado"):
        logger.info("RiesgoAprobado ya procesado para %s, se descarta (idempotencia)", idem)
        return

    contexto = evento["contexto"]
    flags = contexto.get("flags_fallo", {}) or {}
    forzar_timeout = bool(flags.get("forzar_timeout"))

    db.registrar_inicio(idem, contexto, forzar_timeout)

    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    logger.info("Liquidando %s: esperando %.1fs (simulación de red interbancaria)", idem, delay)
    await asyncio.sleep(delay)

    if forzar_timeout:
        db.registrar_resultado(idem, "FALLIDA_TIMEOUT")
        await publicar(
            "TransferenciaFallida",
            idem,
            contexto,
            {"motivo": "timeout_red", "origen_fallo": "pasarela"},
            SERVICIO,
        )
        logger.warning("CP-04: timeout simulado en la pasarela para %s", idem)
    else:
        db.registrar_resultado(idem, "CONFIRMADA")
        await publicar("LiquidacionConfirmada", idem, contexto, {}, SERVICIO)
        logger.info("Liquidación confirmada para %s", idem)


async def escuchar() -> None:
    async for evento in suscribirse():
        if evento.get("tipo") == "RiesgoAprobado":
            asyncio.create_task(manejar_riesgo_aprobado(evento))
