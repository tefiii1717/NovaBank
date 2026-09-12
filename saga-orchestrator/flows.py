import time
import sys
import requests
from prefect import flow, task

ACCOUNTS_URL = "http://127.0.0.1:8001"
RISK_URL = "http://127.0.0.1:8002"
CLEARING_URL = "http://127.0.0.1:8003"

DELAY = 3


@task(name="Debitar Cuenta")
def debitar_cuenta(cuenta: str, monto: float, idempotency_key: str):
    time.sleep(DELAY)
    resp = requests.post(f"{ACCOUNTS_URL}/debitar", json={
        "numero_cuenta": cuenta,
        "monto": monto,
        "idempotency_key": idempotency_key
    })
    resp.raise_for_status()
    return resp.json()


@task(name="Reversar Debito (Compensacion)")
def reversar_debito(cuenta: str, monto: float, idempotency_key: str):
    time.sleep(DELAY)
    resp = requests.post(f"{ACCOUNTS_URL}/reversar", json={
        "numero_cuenta": cuenta,
        "monto": monto,
        "idempotency_key": idempotency_key
    })
    resp.raise_for_status()
    return resp.json()


@task(name="Validar Riesgo")
def validar_riesgo(cuenta: str, monto: float, idempotency_key: str, forzar_fraude: bool):
    time.sleep(DELAY)
    resp = requests.post(f"{RISK_URL}/validar-riesgo", json={
        "numero_cuenta": cuenta,
        "monto": monto,
        "idempotency_key": idempotency_key,
        "forzar_fraude": forzar_fraude
    })
    resp.raise_for_status()
    return resp.json()


@task(name="Anular Riesgo (Compensacion)")
def anular_riesgo(idempotency_key: str):
    time.sleep(DELAY)
    resp = requests.post(f"{RISK_URL}/anular-riesgo", json={
        "idempotency_key": idempotency_key
    })
    resp.raise_for_status()
    return resp.json()


@task(name="Liquidar en Pasarela Interbancaria")
def liquidar_pasarela(cuenta_destino: str, monto: float, idempotency_key: str, forzar_timeout: bool):
    time.sleep(DELAY)
    resp = requests.post(f"{CLEARING_URL}/liquidar", json={
        "cuenta_destino": cuenta_destino,
        "monto": monto,
        "idempotency_key": idempotency_key,
        "forzar_timeout": forzar_timeout
    })
    resp.raise_for_status()
    return resp.json()


@flow(name="Saga Transferencia Orquestada")
def saga_transferencia(
    cuenta_origen: str,
    cuenta_destino: str,
    monto: float,
    idempotency_key: str,
    forzar_fraude: bool = False,
    forzar_timeout: bool = False
):
    print(f"Iniciando saga para {idempotency_key}: {cuenta_origen} -> {cuenta_destino} por {monto}")

    try:
        debito = debitar_cuenta(cuenta_origen, monto, idempotency_key)
    except requests.exceptions.HTTPError:
        print("RECHAZADO_FONDOS: sin fondos suficientes, no se ejecuta ninguna compensacion")
        return {"status": "RECHAZADO_FONDOS"}

    try:
        riesgo = validar_riesgo(cuenta_origen, monto, idempotency_key, forzar_fraude)
    except requests.exceptions.HTTPError:
        print("RECHAZADO_RIESGO: revirtiendo debito")
        reversar_debito(cuenta_origen, monto, idempotency_key)
        return {"status": "RECHAZADO_RIESGO", "compensado": True}

    try:
        liquidacion = liquidar_pasarela(cuenta_destino, monto, idempotency_key, forzar_timeout)
    except requests.exceptions.HTTPError:
        print("RECHAZADO_RED: anulando riesgo y revirtiendo debito")
        anular_riesgo(idempotency_key)
        reversar_debito(cuenta_origen, monto, idempotency_key)
        return {"status": "RECHAZADO_RED", "compensado": True}

    print("CONFIRMADO: transferencia completada con exito")
    return {"status": "CONFIRMADO", "debito": debito, "riesgo": riesgo, "liquidacion": liquidacion}


if __name__ == "__main__":
    cuenta_origen = sys.argv[1] if len(sys.argv) > 1 else "1234"
    cuenta_destino = sys.argv[2] if len(sys.argv) > 2 else "5678"
    monto = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
    idempotency_key = sys.argv[4] if len(sys.argv) > 4 else "test-key"
    forzar_fraude = "--fraude" in sys.argv
    forzar_timeout = "--timeout" in sys.argv

    resultado = saga_transferencia(
        cuenta_origen, cuenta_destino, monto, idempotency_key,
        forzar_fraude, forzar_timeout
    )
    print(resultado)
