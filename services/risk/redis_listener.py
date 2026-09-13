"""
El "oído" de Riesgo y Antifraude para la Saga Coreografiada: se suscribe a
saga.eventos en Redis y reacciona a SaldoDebitado sin que nadie la llame por
HTTP. Reutiliza la misma lógica de negocio (_validar_riesgo / _anular_riesgo)
que ya usa el endpoint HTTP — ver docs/CONTRATO_EVENTOS.md.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict

import redis

from database import SessionLocal
from main import _anular_riesgo, _validar_riesgo

logger = logging.getLogger("risk.redis_listener")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CANAL = "saga.eventos"
SERVICIO = "risk"


def _cliente() -> "redis.Redis":
    return redis.from_url(REDIS_URL, decode_responses=True)


def _publicar(cliente: "redis.Redis", tipo: str, idempotency_key: str, contexto: Dict[str, Any], data: Dict[str, Any]) -> None:
    envelope = {
        "tipo": tipo,
        "idempotency_key": idempotency_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origen_servicio": SERVICIO,
        "contexto": contexto,
        "data": data,
    }
    cliente.publish(CANAL, json.dumps(envelope))


def _ya_procesado(cliente: "redis.Redis", idempotency_key: str, clave: str) -> bool:
    creado = cliente.set(f"procesado:{idempotency_key}:risk:{clave}", "1", nx=True, ex=60 * 60 * 24)
    return not creado


def _manejar_saldo_debitado(cliente: "redis.Redis", evento: Dict[str, Any]) -> None:
    idem = evento["idempotency_key"]
    if _ya_procesado(cliente, idem, "SaldoDebitado"):
        return

    contexto = evento["contexto"]
    flags = contexto.get("flags_fallo", {}) or {}
    db = SessionLocal()
    try:
        resultado = _validar_riesgo(
            db, contexto["origen"], contexto["monto"], idem, bool(flags.get("forzar_fraude"))
        )
    finally:
        db.close()

    if resultado["status"] == "rechazado":
        _publicar(cliente, "RiesgoRechazado", idem, contexto, {"motivo": "fraude_detectado"})
        logger.info("CP-03: riesgo rechazado para %s (%s)", idem, resultado.get("motivo"))
    else:
        _publicar(cliente, "RiesgoAprobado", idem, contexto, {})
        logger.info("Riesgo aprobado para %s", idem)


def _manejar_transferencia_fallida(cliente: "redis.Redis", evento: Dict[str, Any]) -> None:
    if evento.get("data", {}).get("origen_fallo") != "pasarela":
        return

    idem = evento["idempotency_key"]
    if _ya_procesado(cliente, idem, "anular_riesgo"):
        return

    contexto = evento["contexto"]
    db = SessionLocal()
    try:
        _anular_riesgo(db, idem)
    finally:
        db.close()

    _publicar(cliente, "CompensacionEjecutada", idem, contexto,
               {"servicio": "risk", "accion": "anulacion_riesgo"})
    logger.info("CP-04: aprobación de riesgo anulada para %s", idem)


def escuchar() -> None:
    cliente = _cliente()
    pubsub = cliente.pubsub()
    pubsub.subscribe(CANAL)
    logger.info("risk escuchando %s en %s", CANAL, REDIS_URL)

    for mensaje in pubsub.listen():
        if mensaje["type"] != "message":
            continue
        try:
            evento = json.loads(mensaje["data"])
        except (TypeError, ValueError):
            continue

        try:
            tipo = evento.get("tipo")
            if tipo == "SaldoDebitado":
                _manejar_saldo_debitado(cliente, evento)
            elif tipo == "TransferenciaFallida":
                _manejar_transferencia_fallida(cliente, evento)
        except Exception:
            logger.exception("Error procesando evento en risk: %s", evento)


def iniciar_en_segundo_plano() -> threading.Thread:
    hilo = threading.Thread(target=escuchar, daemon=True)
    hilo.start()
    return hilo
