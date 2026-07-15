"""Object storage health integration for Sprint 0.

AAA architecture specifies object storage for artifacts/media.
Sprint 0 validates endpoint reachability and readiness only.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings


async def check_object_storage() -> tuple[bool, str]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=settings.dependency_check_timeout_seconds) as client:
            response = await client.get(settings.object_storage_health_url)
        if response.status_code == 200:
            return True, "ok"
        return False, f"unexpected status {response.status_code}"
    except Exception as exc:  # surfaced in readiness payload
        return False, str(exc)

