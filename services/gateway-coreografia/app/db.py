import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("GATEWAY_DB_PATH", "./data/gateway_coreografia.db")


def _conectar() -> sqlite3.Connection:
    directorio = os.path.dirname(DB_PATH)
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar() -> None:
    with _conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transacciones (
                idempotency_key TEXT PRIMARY KEY,
                origen TEXT NOT NULL,
                destino TEXT NOT NULL,
                monto REAL NOT NULL,
                forzar_fraude INTEGER NOT NULL DEFAULT 0,
                forzar_timeout INTEGER NOT NULL DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'EN_EJECUCION',
                creado_en TEXT NOT NULL,
                actualizado_en TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL,
                tipo TEXT NOT NULL,
                estado_paso TEXT NOT NULL,
                origen_servicio TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (idempotency_key) REFERENCES transacciones(idempotency_key)
            )
            """
        )


def crear_transaccion_si_no_existe(idempotency_key: str, contexto: Dict[str, Any]) -> bool:
    """Devuelve True si la fila se creó ahora (primera vez), False si ya existía (CP-05)."""
    ahora = datetime.now(timezone.utc).isoformat()
    flags = contexto.get("flags_fallo", {}) or {}
    with _conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transacciones
                (idempotency_key, origen, destino, monto, forzar_fraude, forzar_timeout, estado, creado_en, actualizado_en)
            VALUES (?, ?, ?, ?, ?, ?, 'EN_EJECUCION', ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (
                idempotency_key,
                contexto["origen"],
                contexto["destino"],
                contexto["monto"],
                int(bool(flags.get("forzar_fraude"))),
                int(bool(flags.get("forzar_timeout"))),
                ahora,
                ahora,
            ),
        )
        return cursor.rowcount == 1


def actualizar_estado(idempotency_key: str, estado: str) -> None:
    with _conectar() as conn:
        conn.execute(
            "UPDATE transacciones SET estado = ?, actualizado_en = ? WHERE idempotency_key = ?",
            (estado, datetime.now(timezone.utc).isoformat(), idempotency_key),
        )


def agregar_paso(
    idempotency_key: str,
    tipo: str,
    estado_paso: str,
    origen_servicio: str,
    timestamp: str,
    data: Dict[str, Any],
) -> None:
    with _conectar() as conn:
        conn.execute(
            """
            INSERT INTO historial (idempotency_key, tipo, estado_paso, origen_servicio, timestamp, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (idempotency_key, tipo, estado_paso, origen_servicio, timestamp, json.dumps(data)),
        )


def obtener_transaccion(idempotency_key: str) -> Optional[Dict[str, Any]]:
    with _conectar() as conn:
        fila = conn.execute(
            "SELECT * FROM transacciones WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return dict(fila) if fila else None


def obtener_historial(idempotency_key: str) -> List[Dict[str, Any]]:
    with _conectar() as conn:
        filas = conn.execute(
            "SELECT * FROM historial WHERE idempotency_key = ? ORDER BY id ASC", (idempotency_key,)
        ).fetchall()
        resultado = []
        for fila in filas:
            item = dict(fila)
            item["data"] = json.loads(item["data"])
            resultado.append(item)
        return resultado
