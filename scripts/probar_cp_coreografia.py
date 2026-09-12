"""
Script de verificación manual de la Saga Coreografiada CONTRA EL STACK REAL
(docker-compose up: redis + pasarela-interbancaria + gateway-coreografia).

Cuentas y Saldos y Riesgo y Antifraude (servicios de Tefi) todavía no existen en
este repo, así que este script simula sus reacciones publicando directamente al
bus de eventos los mensajes que ELLOS emitirían según docs/CONTRATO_EVENTOS.md.
La Pasarela Interbancaria (Yuly) es real y corre de verdad — por eso CP-01 y
CP-04 demuestran el comportamiento real de la pasarela (incluido el delay de
2-4s), mientras que CP-02, CP-03 y CP-05 verifican el comportamiento del propio
gateway-coreografia.

Uso:
    1) docker compose up -d redis pasarela-interbancaria gateway-coreografia
    2) python scripts/probar_cp_coreografia.py
       (usa el intérprete de services/gateway-coreografia/.venv o cualquiera
        que tenga instalado el paquete `redis`)
"""
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import redis

GATEWAY_URL = "http://localhost:8100"
REDIS_URL = "redis://localhost:6379/0"
CANAL = "saga.eventos"


def publicar(cliente_redis, tipo, idem, contexto, data, origen):
    envelope = {
        "tipo": tipo,
        "idempotency_key": idem,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origen_servicio": origen,
        "contexto": contexto,
        "data": data,
    }
    cliente_redis.publish(CANAL, json.dumps(envelope))


def post_transferencia(**kwargs):
    payload = json.dumps(kwargs).encode()
    req = urllib.request.Request(
        f"{GATEWAY_URL}/transferencia", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def obtener_estado(idem):
    with urllib.request.urlopen(f"{GATEWAY_URL}/transferencia/{idem}/estado") as resp:
        return json.loads(resp.read())


def esperar_estado(idem, esperado, timeout=8.0):
    limite = time.time() + timeout
    ultimo = None
    while time.time() < limite:
        ultimo = obtener_estado(idem)
        if ultimo["estado"] == esperado:
            return ultimo
        time.sleep(0.3)
    raise AssertionError(f"{idem}: nunca llegó a {esperado}, último estado: {ultimo}")


def contexto_de(origen, destino, monto, forzar_fraude=False, forzar_timeout=False):
    return {
        "origen": origen, "destino": destino, "monto": monto,
        "flags_fallo": {"forzar_fraude": forzar_fraude, "forzar_timeout": forzar_timeout},
    }


def cp01_camino_feliz(r):
    idem = f"cp01-{uuid.uuid4()}"
    post_transferencia(origen="CTA-001", destino="CTA-002", monto=100.0, idempotency_key=idem)
    ctx = contexto_de("CTA-001", "CTA-002", 100.0)
    publicar(r, "SaldoDebitado", idem, ctx, {}, "cuentas-y-saldos (simulado)")
    publicar(r, "RiesgoAprobado", idem, ctx, {}, "riesgo-antifraude (simulado)")
    # A partir de aquí reacciona la Pasarela REAL (2-4s de delay)
    estado = esperar_estado(idem, "CONFIRMADO", timeout=8.0)
    print("CP-01 OK ->", estado["estado"])


def cp02_fondos_insuficientes(r):
    idem = f"cp02-{uuid.uuid4()}"
    post_transferencia(origen="CTA-001", destino="CTA-002", monto=999999999.0, idempotency_key=idem)
    ctx = contexto_de("CTA-001", "CTA-002", 999999999.0)
    publicar(r, "TransferenciaFallida", idem, ctx,
             {"motivo": "fondos_insuficientes", "origen_fallo": "cuentas-y-saldos"},
             "cuentas-y-saldos (simulado)")
    estado = esperar_estado(idem, "RECHAZADO_FONDOS")
    assert "CompensacionEjecutada" not in [p["tipo"] for p in estado["historial"]]
    print("CP-02 OK ->", estado["estado"])


def cp03_riesgo_rechazado(r):
    idem = f"cp03-{uuid.uuid4()}"
    post_transferencia(origen="CTA-001", destino="CTA-002", monto=100.0, idempotency_key=idem,
                        flags_fallo={"forzar_fraude": True, "forzar_timeout": False})
    ctx = contexto_de("CTA-001", "CTA-002", 100.0, forzar_fraude=True)
    publicar(r, "SaldoDebitado", idem, ctx, {}, "cuentas-y-saldos (simulado)")
    publicar(r, "RiesgoRechazado", idem, ctx, {"motivo": "fraude_detectado"}, "riesgo-antifraude (simulado)")
    estado = esperar_estado(idem, "RECHAZADO_RIESGO")
    publicar(r, "CompensacionEjecutada", idem, ctx,
             {"servicio": "cuentas-y-saldos", "accion": "reversa_debito"}, "cuentas-y-saldos (simulado)")
    time.sleep(0.5)
    estado = obtener_estado(idem)
    assert estado["estado"] == "RECHAZADO_RIESGO"
    assert any(p["tipo"] == "CompensacionEjecutada" for p in estado["historial"])
    print("CP-03 OK ->", estado["estado"], "(con compensación)")


def cp04_timeout_red(r):
    idem = f"cp04-{uuid.uuid4()}"
    post_transferencia(origen="CTA-001", destino="CTA-002", monto=250.0, idempotency_key=idem,
                        flags_fallo={"forzar_fraude": False, "forzar_timeout": True})
    ctx = contexto_de("CTA-001", "CTA-002", 250.0, forzar_timeout=True)
    publicar(r, "SaldoDebitado", idem, ctx, {}, "cuentas-y-saldos (simulado)")
    publicar(r, "RiesgoAprobado", idem, ctx, {}, "riesgo-antifraude (simulado)")
    # La Pasarela REAL detecta forzar_timeout y publica TransferenciaFallida (2-4s de delay)
    estado = esperar_estado(idem, "RECHAZADO_RED", timeout=8.0)
    publicar(r, "CompensacionEjecutada", idem, ctx,
             {"servicio": "riesgo-antifraude", "accion": "anulacion_riesgo"}, "riesgo-antifraude (simulado)")
    publicar(r, "CompensacionEjecutada", idem, ctx,
             {"servicio": "cuentas-y-saldos", "accion": "reversa_debito"}, "cuentas-y-saldos (simulado)")
    time.sleep(0.5)
    estado = obtener_estado(idem)
    compensaciones = [p for p in estado["historial"] if p["tipo"] == "CompensacionEjecutada"]
    assert len(compensaciones) == 2
    print("CP-04 OK ->", estado["estado"], "(doble compensación)")


def cp05_idempotencia(r):
    idem = f"cp05-{uuid.uuid4()}"
    primera = post_transferencia(origen="CTA-001", destino="CTA-002", monto=50.0, idempotency_key=idem)
    segunda = post_transferencia(origen="CTA-001", destino="CTA-002", monto=50.0, idempotency_key=idem)
    assert primera == segunda
    time.sleep(0.5)
    estado = obtener_estado(idem)
    tipos = [p["tipo"] for p in estado["historial"]]
    assert tipos.count("TransferenciaSolicitada") == 1
    print("CP-05 OK -> idempotency_key reenviada, sin duplicar (historial:", tipos, ")")


def main():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=2)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"No se pudo contactar {GATEWAY_URL}/health ({exc}). "
            "¿Corriste `docker compose up -d redis pasarela-interbancaria gateway-coreografia`?"
        )

    cp01_camino_feliz(r)
    cp02_fondos_insuficientes(r)
    cp03_riesgo_rechazado(r)
    cp04_timeout_red(r)
    cp05_idempotencia(r)
    print("\nTodos los CP verificados contra el stack coreografiado real.")


if __name__ == "__main__":
    main()
