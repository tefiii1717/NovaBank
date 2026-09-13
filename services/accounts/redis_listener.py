"""
El "oído" de Cuentas y Saldos para la Saga Coreografiada: se suscribe a
saga.eventos en Redis y reacciona sola, sin que nadie la llame por HTTP
(a diferencia del flow orquestado, que sí la llama directo). Reutiliza la
misma lógica de negocio (_debitar / _reversar) que ya usa el endpoint HTTP,
ver docs/CONTRATO_EVENTOS.md.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict

import redis

from database import SessionLocal
from main import _debitar, _reversar

logger = logging.getLogger("accounts.redis_listener")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CANAL = "saga.eventos"
SERVICIO = "accounts"


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
    # SET NX devuelve None si la clave ya existía -> ya se procesó antes (CP-05
    # a nivel de handler, además de la idempotencia propia de accounts.db).
    creado = cliente.set(f"procesado:{idempotency_key}:accounts:{clave}", "1", nx=True, ex=60 * 60 * 24)
    return not creado


def _manejar_transferencia_solicitada(cliente: "redis.Redis", evento: Dict[str, Any]) -> None:
    idem = evento["idempotency_key"]
    if _ya_procesado(cliente, idem, "TransferenciaSolicitada"):
        return

    contexto = evento["contexto"]
    db = SessionLocal()
    try:
        resultado = _debitar(db, contexto["origen"], contexto["monto"], idem)
    finally:
        db.close()

    if resultado["status"] in ("rechazado_fondos", "cuenta_no_encontrada"):
        _publicar(cliente, "TransferenciaFallida", idem, contexto,
                   {"motivo": "fondos_insuficientes", "origen_fallo": "accounts"})
        logger.info("CP-02: fondos insuficientes para %s", idem)
    elif resultado["status"] in ("ok", "duplicado"):
        _publicar(cliente, "SaldoDebitado", idem, contexto, {})
        logger.info("Saldo debitado para %s", idem)


def _debe_compensar(evento: Dict[str, Any]) -> bool:
    if evento.get("tipo") == "RiesgoRechazado":
        return True
    if evento.get("tipo") == "TransferenciaFallida" and evento.get("data", {}).get("origen_fallo") == "pasarela":
        return True
    return False


def _manejar_compensacion(cliente: "redis.Redis", evento: Dict[str, Any]) -> None:
    idem = evento["idempotency_key"]
    if _ya_procesado(cliente, idem, f"reversa:{evento['tipo']}"):
        return

    contexto = evento["contexto"]
    db = SessionLocal()
    try:
        _reversar(db, contexto["origen"], contexto["monto"], idem)
    finally:
        db.close()

    _publicar(cliente, "CompensacionEjecutada", idem, contexto,
               {"servicio": "accounts", "accion": "reversa_debito"})
    logger.info("Débito revertido para %s (motivo: %s)", idem, evento["tipo"])


def escuchar() -> None:
    cliente = _cliente()
    pubsub = cliente.pubsub()
    pubsub.subscribe(CANAL)
    logger.info("accounts escuchando %s en %s", CANAL, REDIS_URL)

    for mensaje in pubsub.listen():
        if mensaje["type"] != "message":
            continue
        try:
            evento = json.loads(mensaje["data"])
        except (TypeError, ValueError):
            continue

        try:
            if evento.get("tipo") == "TransferenciaSolicitada":
                _manejar_transferencia_solicitada(cliente, evento)
            elif _debe_compensar(evento):
                _manejar_compensacion(cliente, evento)
        except Exception:
            logger.exception("Error procesando evento en accounts: %s", evento)


def iniciar_en_segundo_plano() -> threading.Thread:
    hilo = threading.Thread(target=escuchar, daemon=True)
    hilo.start()
    return hilo
