"""Process liveness and dependency readiness endpoints."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


async def _run_probe(
    name: str,
    probe: Callable[[], Awaitable[None]],
    timeout_seconds: float,
) -> tuple[str, dict[str, str]]:
    try:
        await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except Exception as error:
        return name, {"status": "unavailable", "error": type(error).__name__}
    return name, {"status": "ok"}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the API process is alive."""

    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Check PostgreSQL, Redis, and MinIO before reporting readiness."""

    resources: Any = getattr(request.app.state, "runtime", None)
    if resources is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "dependencies": {"runtime": {"status": "missing"}}},
        )

    timeout_seconds = request.app.state.settings.healthcheck_timeout_seconds
    checks = await asyncio.gather(
        _run_probe("postgresql", resources.database.check, timeout_seconds),
        _run_probe("redis", resources.redis.check, timeout_seconds),
        _run_probe("minio", resources.object_storage.check, timeout_seconds),
    )
    dependencies = dict(checks)
    ready = all(result["status"] == "ok" for result in dependencies.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "unavailable", "dependencies": dependencies},
    )
