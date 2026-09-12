"""
Pruebas del Gateway de Coreografía en aislamiento: Cuentas, Riesgo y la Pasarela
todavía no existen como servicios reales corriendo aquí, así que se simulan
publicando directamente los eventos que ELLOS emitirían (exactamente el contrato
de docs/CONTRATO_EVENTOS.md). Esto es válido porque, en una arquitectura
coreografiada, ningún servicio debe conocer la implementación de los demás —
solo el contrato de eventos — así que probar contra "dobles" que respetan el
contrato es una prueba de aislamiento legítima (ver docs/CONTRATO_EVENTOS.md).

Cubre la matriz completa de casos de prueba (CP-01 a CP-05) desde la perspectiva
del gateway: creación de la transacción, agregación de estado y idempotencia.
"""
import asyncio
import os
import tempfile

os.environ.setdefault("GATEWAY_DB_PATH", os.path.join(tempfile.mkdtemp(), "gateway_test.db"))

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app import aggregator, db, redis_bus
from app.main import app


@pytest.fixture(autouse=True)
async def _entorno():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_bus.set_client(fake)
    db.inicializar()
    tarea = asyncio.create_task(aggregator.escuchar())
    await asyncio.sleep(0.1)  # deja que el agregador quede suscrito antes de publicar nada
    yield fake
    tarea.cancel()


def _cliente() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _esperar_estado(client: AsyncClient, idem: str, estado_esperado: str, timeout: float = 2.0):
    loop = asyncio.get_event_loop()
    limite = loop.time() + timeout
    ultimo = None
    while loop.time() < limite:
        r = await client.get(f"/transferencia/{idem}/estado")
        assert r.status_code == 200
        ultimo = r.json()
        if ultimo["estado"] == estado_esperado:
            return ultimo
        await asyncio.sleep(0.05)
    raise AssertionError(f"nunca llegó a {estado_esperado}, último estado visto: {ultimo}")


async def _esperar_pasos_en_historial(client: AsyncClient, idem: str, cantidad_minima: int, timeout: float = 2.0):
    loop = asyncio.get_event_loop()
    limite = loop.time() + timeout
    ultimo = None
    while loop.time() < limite:
        r = await client.get(f"/transferencia/{idem}/estado")
        assert r.status_code == 200
        ultimo = r.json()
        if len(ultimo["historial"]) >= cantidad_minima:
            return ultimo
        await asyncio.sleep(0.05)
    raise AssertionError(f"el historial nunca llegó a {cantidad_minima} pasos: {ultimo}")


async def test_cp01_camino_feliz_confirmado():
    async with _cliente() as client:
        resp = await client.post(
            "/transferencia",
            json={"origen": "CTA-001", "destino": "CTA-002", "monto": 100.0},
        )
        assert resp.status_code == 200
        cuerpo = resp.json()
        idem = cuerpo["idempotency_key"]
        assert cuerpo["estado"] == "EN_EJECUCION"

        contexto = {
            "origen": "CTA-001", "destino": "CTA-002", "monto": 100.0,
            "flags_fallo": {"forzar_fraude": False, "forzar_timeout": False},
        }
        # Lo que emitirían Cuentas, Riesgo y la Pasarela en el camino feliz:
        await redis_bus.publicar("SaldoDebitado", idem, contexto, {}, "cuentas-y-saldos")
        await redis_bus.publicar("RiesgoAprobado", idem, contexto, {}, "riesgo-antifraude")
        await redis_bus.publicar("LiquidacionConfirmada", idem, contexto, {}, "pasarela-interbancaria")

        estado = await _esperar_estado(client, idem, "CONFIRMADO")
        tipos = [p["tipo"] for p in estado["historial"]]
        assert tipos == [
            "TransferenciaSolicitada", "SaldoDebitado", "RiesgoAprobado", "LiquidacionConfirmada",
        ]


async def test_cp02_fondos_insuficientes_rechazo_sin_compensacion():
    async with _cliente() as client:
        resp = await client.post(
            "/transferencia",
            json={"origen": "CTA-001", "destino": "CTA-002", "monto": 999999.0},
        )
        idem = resp.json()["idempotency_key"]
        contexto = {
            "origen": "CTA-001", "destino": "CTA-002", "monto": 999999.0,
            "flags_fallo": {"forzar_fraude": False, "forzar_timeout": False},
        }
        # Cuentas rechaza de inmediato: nunca hubo SaldoDebitado, no hay nada que revertir.
        await redis_bus.publicar(
            "TransferenciaFallida", idem, contexto,
            {"motivo": "fondos_insuficientes", "origen_fallo": "cuentas-y-saldos"},
            "cuentas-y-saldos",
        )

        estado = await _esperar_estado(client, idem, "RECHAZADO_FONDOS")
        tipos = [p["tipo"] for p in estado["historial"]]
        assert "CompensacionEjecutada" not in tipos
        assert "SaldoDebitado" not in tipos


async def test_cp03_riesgo_rechaza_y_se_compensa_el_debito():
    async with _cliente() as client:
        resp = await client.post(
            "/transferencia",
            json={
                "origen": "CTA-001", "destino": "CTA-002", "monto": 100.0,
                "flags_fallo": {"forzar_fraude": True, "forzar_timeout": False},
            },
        )
        idem = resp.json()["idempotency_key"]
        contexto = {
            "origen": "CTA-001", "destino": "CTA-002", "monto": 100.0,
            "flags_fallo": {"forzar_fraude": True, "forzar_timeout": False},
        }
        await redis_bus.publicar("SaldoDebitado", idem, contexto, {}, "cuentas-y-saldos")
        await redis_bus.publicar(
            "RiesgoRechazado", idem, contexto, {"motivo": "fraude_detectado"}, "riesgo-antifraude",
        )

        estado = await _esperar_estado(client, idem, "RECHAZADO_RIESGO")

        # Cuentas reacciona a RiesgoRechazado reintegrando el débito.
        await redis_bus.publicar(
            "CompensacionEjecutada", idem, contexto,
            {"servicio": "cuentas-y-saldos", "accion": "reversa_debito"}, "cuentas-y-saldos",
        )
        await asyncio.sleep(0.2)

        estado = await client.get(f"/transferencia/{idem}/estado")
        estado = estado.json()
        # El estado final de negocio sigue siendo RECHAZADO_RIESGO (tabla CP-03),
        # pero el paso de compensación queda visible en el historial como COMPENSADO.
        assert estado["estado"] == "RECHAZADO_RIESGO"
        pasos = {p["tipo"]: p["estado_paso"] for p in estado["historial"]}
        assert pasos["CompensacionEjecutada"] == "COMPENSADO"


async def test_cp04_timeout_red_doble_compensacion():
    async with _cliente() as client:
        resp = await client.post(
            "/transferencia",
            json={
                "origen": "CTA-001", "destino": "CTA-002", "monto": 250.0,
                "flags_fallo": {"forzar_fraude": False, "forzar_timeout": True},
            },
        )
        idem = resp.json()["idempotency_key"]
        contexto = {
            "origen": "CTA-001", "destino": "CTA-002", "monto": 250.0,
            "flags_fallo": {"forzar_fraude": False, "forzar_timeout": True},
        }
        await redis_bus.publicar("SaldoDebitado", idem, contexto, {}, "cuentas-y-saldos")
        await redis_bus.publicar("RiesgoAprobado", idem, contexto, {}, "riesgo-antifraude")
        # La pasarela (real, ver services/pasarela-interbancaria) detecta forzar_timeout:
        await redis_bus.publicar(
            "TransferenciaFallida", idem, contexto,
            {"motivo": "timeout_red", "origen_fallo": "pasarela-interbancaria"},
            "pasarela-interbancaria",
        )

        estado = await _esperar_estado(client, idem, "RECHAZADO_RED")

        # Riesgo anula su aprobación y Cuentas revierte el débito.
        await redis_bus.publicar(
            "CompensacionEjecutada", idem, contexto,
            {"servicio": "riesgo-antifraude", "accion": "anulacion_riesgo"}, "riesgo-antifraude",
        )
        await redis_bus.publicar(
            "CompensacionEjecutada", idem, contexto,
            {"servicio": "cuentas-y-saldos", "accion": "reversa_debito"}, "cuentas-y-saldos",
        )
        await asyncio.sleep(0.2)

        estado = (await client.get(f"/transferencia/{idem}/estado")).json()
        assert estado["estado"] == "RECHAZADO_RED"
        compensaciones = [p for p in estado["historial"] if p["tipo"] == "CompensacionEjecutada"]
        assert len(compensaciones) == 2
        assert {c["data"]["accion"] for c in compensaciones} == {"anulacion_riesgo", "reversa_debito"}


async def test_cp05_idempotencia_no_duplica_publicacion():
    async with _cliente() as client:
        idem = "cp05-mismo-id"
        payload = {
            "origen": "CTA-001", "destino": "CTA-002", "monto": 50.0,
            "idempotency_key": idem,
        }

        primera = await client.post("/transferencia", json=payload)
        segunda = await client.post("/transferencia", json=payload)

        assert primera.json() == segunda.json()

        # Debe haber exactamente un TransferenciaSolicitada publicado, no dos
        # (el agregador procesa el evento de forma asíncrona, así que esperamos
        # a que aparezca en el historial antes de contar).
        estado = await _esperar_pasos_en_historial(client, idem, cantidad_minima=1)
        tipos = [p["tipo"] for p in estado["historial"]]
        assert tipos.count("TransferenciaSolicitada") == 1
