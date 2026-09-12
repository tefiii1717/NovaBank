import json
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CANAL = "saga.eventos"

_client: Optional[aioredis.Redis] = None


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client


def set_client(client: aioredis.Redis) -> None:
    """Permite inyectar un cliente (p.ej. fakeredis) desde los tests."""
    global _client
    _client = client


async def publicar(
    tipo: str,
    idempotency_key: str,
    contexto: Dict[str, Any],
    data: Dict[str, Any],
    origen_servicio: str,
) -> Dict[str, Any]:
    envelope = {
        "tipo": tipo,
        "idempotency_key": idempotency_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origen_servicio": origen_servicio,
        "contexto": contexto,
        "data": data,
    }
    await get_client().publish(CANAL, json.dumps(envelope))
    return envelope


async def suscribirse() -> AsyncGenerator[Dict[str, Any], None]:
    client = get_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(CANAL)
    async for mensaje in pubsub.listen():
        if mensaje["type"] != "message":
            continue
        yield json.loads(mensaje["data"])
