"""
Script de verificación manual de la Saga Coreografiada CONTRA EL STACK REAL
COMPLETO (docker-compose up: redis + accounts + risk + pasarela-interbancaria +
gateway-coreografia) — sin ningún evento sintético. Los tres servicios de
dominio reaccionan solos a saga.eventos (ver redis_listener.py en accounts y
risk, y app/listener.py en pasarela-interbancaria).

Uso:
    1) docker compose up -d --build
    2) python scripts/probar_cp_coreografia.py
       (usa el intérprete de services/gateway-coreografia/.venv o cualquiera
        que tenga instalado el paquete `requests`, o simplemente urllib como aquí)
"""
import json
import time
import urllib.error
import urllib.request
import uuid

GATEWAY_URL = "http://localhost:8100"
ACCOUNTS_URL = "http://localhost:8001"

CUENTA_ORIGEN = "CTA-001"
CUENTA_DESTINO = "CTA-002"


def _post(url, payload):
    datos = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            return {"ya_existia": True}
        raise


def asegurar_cuentas():
    _post(f"{ACCOUNTS_URL}/cuentas", {"numero_cuenta": CUENTA_ORIGEN, "saldo_inicial": 100000.0})
    _post(f"{ACCOUNTS_URL}/cuentas", {"numero_cuenta": CUENTA_DESTINO, "saldo_inicial": 100.0})


def post_transferencia(**kwargs):
    return _post(f"{GATEWAY_URL}/transferencia", kwargs)


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


def cp01_camino_feliz():
    idem = f"cp01-{uuid.uuid4()}"
    post_transferencia(origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=100.0, idempotency_key=idem)
    estado = esperar_estado(idem, "CONFIRMADO", timeout=8.0)
    print("CP-01 OK ->", estado["estado"])


def cp02_fondos_insuficientes():
    idem = f"cp02-{uuid.uuid4()}"
    post_transferencia(origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=999999999.0, idempotency_key=idem)
    estado = esperar_estado(idem, "RECHAZADO_FONDOS")
    assert "CompensacionEjecutada" not in [p["tipo"] for p in estado["historial"]]
    print("CP-02 OK ->", estado["estado"])


def cp03_riesgo_rechazado():
    idem = f"cp03-{uuid.uuid4()}"
    post_transferencia(
        origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=100.0, idempotency_key=idem,
        flags_fallo={"forzar_fraude": True, "forzar_timeout": False},
    )
    estado = esperar_estado(idem, "RECHAZADO_RIESGO")
    assert any(p["tipo"] == "CompensacionEjecutada" for p in estado["historial"])
    print("CP-03 OK ->", estado["estado"], "(con compensación)")


def cp04_timeout_red():
    idem = f"cp04-{uuid.uuid4()}"
    post_transferencia(
        origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=250.0, idempotency_key=idem,
        flags_fallo={"forzar_fraude": False, "forzar_timeout": True},
    )
    estado = esperar_estado(idem, "RECHAZADO_RED", timeout=8.0)
    compensaciones = [p for p in estado["historial"] if p["tipo"] == "CompensacionEjecutada"]
    assert len(compensaciones) == 2
    print("CP-04 OK ->", estado["estado"], "(doble compensación)")


def cp05_idempotencia():
    idem = f"cp05-{uuid.uuid4()}"
    primera = post_transferencia(origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=50.0, idempotency_key=idem)
    segunda = post_transferencia(origen=CUENTA_ORIGEN, destino=CUENTA_DESTINO, monto=50.0, idempotency_key=idem)
    assert primera == segunda
    time.sleep(0.5)
    estado = obtener_estado(idem)
    tipos = [p["tipo"] for p in estado["historial"]]
    assert tipos.count("TransferenciaSolicitada") == 1
    print("CP-05 OK -> idempotency_key reenviada, sin duplicar (historial:", tipos, ")")


def main():
    try:
        urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=2)
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"No se pudo contactar {GATEWAY_URL}/health ({exc}). "
            "¿Corriste `docker compose up -d --build`?"
        )

    asegurar_cuentas()
    cp01_camino_feliz()
    cp02_fondos_insuficientes()
    cp03_riesgo_rechazado()
    cp04_timeout_red()
    cp05_idempotencia()
    print("\nTodos los CP verificados contra el stack coreografiado real (sin eventos sintéticos).")


if __name__ == "__main__":
    main()
