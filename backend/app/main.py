"""AAA v2 FastAPI app factory (Sprint 0-10).

Sprint 10 adds:
- Request context correlation middleware
- Security headers middleware
- Rate limiting middleware
- Global exception handler
- Prometheus metrics endpoint
- OpenTelemetry tracing (optional)
- Configuration validation at startup
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v2 import router as v2_router
from app.core.config import get_settings, validate_configuration
from app.core.exceptions import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.monitoring.metrics import metrics_endpoint

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    # Startup summary — use standard Python logging msg+args format
    logger.info(
        "startup_complete app=%s version=%s env=%s host=%s port=%s log_level=%s rate_limit=%s slow_threshold=%dms",
        settings.app_name,
        settings.app_version,
        settings.app_env,
        settings.api_host,
        settings.api_port,
        settings.log_level,
        settings.enable_rate_limit,
        settings.slow_request_threshold_ms,
    )

    # Validate configuration on startup
    config_status = validate_configuration()
    if config_status["status"] == "invalid":
        logger.error("Configuration validation failed: %s", config_status.get("errors"))
        # Log but don't crash — allow the app to start for debugging
        # Production deployments should gate on this
    else:
        logger.info("Configuration validation passed")

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # ── Middleware order matters. Outermost first. ──────────────────────────

    # 1. Security headers (outermost — applied to all responses)
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Request context / correlation ID (before logging)
    app.add_middleware(RequestContextMiddleware)

    # 4. Structured request logging
    app.add_middleware(RequestLoggingMiddleware)

    # 5. Rate limiting (guards all API routes)
    if settings.enable_rate_limit:
        app.add_middleware(RateLimitMiddleware)

    # ── Exception handlers ─────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routes ─────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(v2_router.router)

    # Prometheus /metrics endpoint
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    return app


app = create_app()
