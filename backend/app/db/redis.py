"""Redis connectivity helpers."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

_redis_client: Any | None = None


def get_redis() -> Any:
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import Redis

        settings = get_settings()
        _redis_client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _redis_client


async def check_redis() -> tuple[bool, str]:
    try:
        client = get_redis()
        result = await client.ping()
        return bool(result), "ok" if result else "ping returned false"
    except Exception as exc:  # surfaced in readiness payload
        return False, str(exc)

