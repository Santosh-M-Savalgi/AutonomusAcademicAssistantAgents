"""Health and readiness endpoints.

Sprint 10: Extended health diagnostics with uptime, provider health,
and job system health.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.chroma_client import check_chroma
from app.db.object_storage import check_object_storage
from app.db.postgres import check_postgres
from app.db.redis import check_redis
# Job system health is checked inline to avoid circular imports

router = APIRouter(tags=["health"])

_start_time: float = time.time()


async def check_provider_health() -> tuple[bool, str]:
    """Check LLM provider availability.

    Returns:
        A tuple of (healthy, detail_string).
    """
    try:
        from app.llm.provider_router import ProviderFactory

        factory = ProviderFactory()
        factory.get_provider()
        return True, "available"
    except Exception as exc:
        return False, str(exc)


async def check_jobs_health() -> tuple[bool, str]:
    """Check job system (Redis) availability.

    Returns:
        A tuple of (healthy, detail_string).
    """
    try:
        from app.db.redis import get_redis

        redis = get_redis()
        await redis.ping()
        return True, "redis_available"
    except Exception as exc:
        return False, str(exc)


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
    """Detailed readiness check returning the health of all dependencies.

    Returns:
        JSON response with detailed status for each dependency:
        - database: PostgreSQL
        - redis: Redis cache
        - chroma: ChromaDB vector store
        - minio: Object storage (MinIO)
        - provider: LLM provider health
        - jobs: Background job system
        - uptime_seconds: Server uptime
    """
    settings = get_settings()
    postgres_ok, postgres_detail = await check_postgres()
    redis_ok, redis_detail = await check_redis()
    chroma_ok, chroma_detail = await check_chroma()
    object_storage_ok, object_storage_detail = await check_object_storage()

    # Provider health check (basic - just report availability)
    provider_ok, provider_detail = await check_provider_health()

    # Job system health — check Redis queue availability
    jobs_ok, jobs_detail = await check_jobs_health()

    checks = {
        settings.service_name_postgres: {"ok": postgres_ok, "detail": postgres_detail},
        settings.service_name_redis: {"ok": redis_ok, "detail": redis_detail},
        settings.service_name_chroma: {"ok": chroma_ok, "detail": chroma_detail},
        settings.service_name_object_storage: {
            "ok": object_storage_ok,
            "detail": object_storage_detail,
        },
        "provider": {"ok": provider_ok, "detail": provider_detail},
        "jobs": {"ok": jobs_ok, "detail": jobs_detail},
    }

    # Flatten to match the Sprint 10 requirement shape
    flat: dict[str, str] = {
        "database": "healthy" if postgres_ok else "unhealthy",
        "redis": "healthy" if redis_ok else "unhealthy",
        "chroma": "healthy" if chroma_ok else "unhealthy",
        "minio": "healthy" if object_storage_ok else "unhealthy",
        "provider": "healthy" if provider_ok else "unhealthy",
        "jobs": "healthy" if jobs_ok else "unhealthy",
        "uptime_seconds": round(time.time() - _start_time),
    }

    health_values = [v for k, v in flat.items() if k != "uptime_seconds"]
    all_healthy = all(v == "healthy" for v in health_values)
    status_code = 200 if all_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content=flat,
    )


@router.get("/readyz/detailed")
async def readiness_detailed() -> JSONResponse:
    """Extended readiness with detailed per-dependency information."""
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
        content={
            "status": "ready" if ready else "not_ready",
            "uptime_seconds": round(time.time() - _start_time),
            "checks": checks,
        },
    )
