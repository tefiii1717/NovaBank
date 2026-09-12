"""
Pruebas de la Pasarela Interbancaria en aislamiento total (sin Cuentas ni Riesgo reales):
se le inyecta un Redis falso (fakeredis) y se publican eventos `RiesgoAprobado` sintéticos
directamente, tal como lo haría el servicio de Riesgo de Tefi en producción.

Cubre:
- Liquidación exitosa -> LiquidacionConfirmada (camino feliz de la pasarela)
- CP-04: forzar_timeout=true -> TransferenciaFallida{motivo: timeout_red}
- CP-05: mismo idempotency_key reenviado -> no se vuelve a publicar el resultado
"""
import asyncio
import json
import os
import tempfile

os.environ.setdefault("PASARELA_DB_PATH", os.path.join(tempfile.mkdtemp(), "pasarela_test.db"))
os.environ.setdefault("PASARELA_DELAY_MIN", "0.01")
os.environ.setdefault("PASARELA_DELAY_MAX", "0.02")

import fakeredis.aioredis
import pytest

from app import db, redis_bus
from app.listener import escuchar

CONTEXTO_BASE = {
    "origen": "CTA-001",
    "destino": "CTA-002",
    "monto": 500.0,
    "flags_fallo": {"forzar_fraude": False, "forzar_timeout": False},
}


@pytest.fixture(autouse=True)
async def _fake_redis():
    # Debe crearse dentro del mismo event loop que usará el test (pytest-asyncio
    # crea uno nuevo por test); si se crea en un fixture síncrono, el cliente queda
    # atado a un loop distinto y los mensajes de pub/sub nunca llegan.
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_bus.set_client(fake)
    db.inicializar()
    yield fake


async def _iniciar_listener():
    """Arranca el listener y espera a que su suscripción interna a Redis quede
    activa antes de seguir — si publicáramos inmediatamente, habría una carrera
    entre `escuchar()` suscribiéndose y el test publicando, y el mensaje se perdería
    (Redis Pub/Sub no entrega mensajes a quien se suscribe después de publicados)."""
    tarea = asyncio.create_task(escuchar())
    await asyncio.sleep(0.1)
    return tarea


async def _esperar_evento(pubsub, tipo_esperado, timeout=2.0):
    async def _leer():
        async for mensaje in pubsub.listen():
            if mensaje["type"] != "message":
                continue
            payload = json.loads(mensaje["data"])
            if payload["tipo"] == tipo_esperado:
                return payload

    return await asyncio.wait_for(_leer(), timeout=timeout)


async def test_liquidacion_exitosa_confirma():
    tarea = await _iniciar_listener()
    try:
        pubsub = redis_bus.get_client().pubsub()
        await pubsub.subscribe(redis_bus.CANAL)

        idem = "cp01-exito"
        await redis_bus.publicar("RiesgoAprobado", idem, CONTEXTO_BASE, {}, "riesgo-antifraude")

        evento = await _esperar_evento(pubsub, "LiquidacionConfirmada")
        assert evento["idempotency_key"] == idem
        assert db.obtener(idem)["resultado"] == "CONFIRMADA"
    finally:
        tarea.cancel()


async def test_forzar_timeout_dispara_transferencia_fallida_cp04():
    tarea = await _iniciar_listener()
    try:
        pubsub = redis_bus.get_client().pubsub()
        await pubsub.subscribe(redis_bus.CANAL)

        idem = "cp04-timeout"
        contexto = {**CONTEXTO_BASE, "flags_fallo": {"forzar_fraude": False, "forzar_timeout": True}}
        await redis_bus.publicar("RiesgoAprobado", idem, contexto, {}, "riesgo-antifraude")

        evento = await _esperar_evento(pubsub, "TransferenciaFallida")
        assert evento["idempotency_key"] == idem
        assert evento["data"]["motivo"] == "timeout_red"
        assert evento["data"]["origen_fallo"] == "pasarela"
        assert db.obtener(idem)["resultado"] == "FALLIDA_TIMEOUT"
    finally:
        tarea.cancel()


async def test_reintento_mismo_idempotency_key_no_duplica_cp05():
    tarea = await _iniciar_listener()
    try:
        pubsub = redis_bus.get_client().pubsub()
        await pubsub.subscribe(redis_bus.CANAL)

        idem = "cp05-retry"
        await redis_bus.publicar("RiesgoAprobado", idem, CONTEXTO_BASE, {}, "riesgo-antifraude")
        primera = await _esperar_evento(pubsub, "LiquidacionConfirmada")
        assert primera["idempotency_key"] == idem

        # Reintento: mismo idempotency_key -> debe descartarse sin reprocesar
        await redis_bus.publicar("RiesgoAprobado", idem, CONTEXTO_BASE, {}, "riesgo-antifraude")

        with pytest.raises(asyncio.TimeoutError):
            await _esperar_evento(pubsub, "LiquidacionConfirmada", timeout=0.5)
    finally:
        tarea.cancel()
