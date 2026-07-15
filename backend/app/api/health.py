"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.chroma_client import check_chroma
from app.db.object_storage import check_object_storage
from app.db.postgres import check_postgres
from app.db.redis import check_redis

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_name_backend,
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@router.get("/readyz")
async def readiness() -> JSONResponse:
    settings = get_settings()
    postgres_ok, postgres_detail = await check_postgres()
    redis_ok, redis_detail = await check_redis()
    chroma_ok, chroma_detail = await check_chroma()
    object_storage_ok, object_storage_detail = await check_object_storage()

    checks = {
        settings.service_name_postgres: {"ok": postgres_ok, "detail": postgres_detail},
        settings.service_name_redis: {"ok": redis_ok, "detail": redis_detail},
        settings.service_name_chroma: {"ok": chroma_ok, "detail": chroma_detail},
        settings.service_name_object_storage: {
            "ok": object_storage_ok,
            "detail": object_storage_detail,
        },
    }
    ready = all(item["ok"] for item in checks.values())
    status_code = 200 if ready else 503

    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )

