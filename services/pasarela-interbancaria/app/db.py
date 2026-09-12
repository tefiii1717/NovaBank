import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DB_PATH = os.getenv("PASARELA_DB_PATH", "./data/pasarela.db")


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
            CREATE TABLE IF NOT EXISTS liquidaciones (
                idempotency_key TEXT PRIMARY KEY,
                origen TEXT NOT NULL,
                destino TEXT NOT NULL,
                monto REAL NOT NULL,
                forzar_timeout INTEGER NOT NULL DEFAULT 0,
                resultado TEXT NOT NULL DEFAULT 'EN_PROCESO',
                creado_en TEXT NOT NULL,
                resuelto_en TEXT
            )
            """
        )


def registrar_inicio(idempotency_key: str, contexto: Dict[str, Any], forzar_timeout: bool) -> None:
    with _conectar() as conn:
        conn.execute(
            """
            INSERT INTO liquidaciones
                (idempotency_key, origen, destino, monto, forzar_timeout, resultado, creado_en)
            VALUES (?, ?, ?, ?, ?, 'EN_PROCESO', ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (
                idempotency_key,
                contexto["origen"],
                contexto["destino"],
                contexto["monto"],
                int(bool(forzar_timeout)),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def registrar_resultado(idempotency_key: str, resultado: str) -> None:
    with _conectar() as conn:
        conn.execute(
            "UPDATE liquidaciones SET resultado = ?, resuelto_en = ? WHERE idempotency_key = ?",
            (resultado, datetime.now(timezone.utc).isoformat(), idempotency_key),
        )


def obtener(idempotency_key: str) -> Optional[Dict[str, Any]]:
    with _conectar() as conn:
        fila = conn.execute(
            "SELECT * FROM liquidaciones WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return dict(fila) if fila else None
