"""FastAPI application entry point for the AAA v3 runtime foundation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from apps.api.config import Settings, get_settings
from apps.api.curriculum import router as curriculum_router
from apps.api.documents.router import router as documents_router
from apps.api.graphs import router as graphs_router
from apps.api.health import router as health_router
from apps.api.jobs import router as jobs_router
from apps.api.logging import configure_logging
from apps.api.middleware import RequestIDMiddleware
from apps.api.runtime import RuntimeResources, create_runtime_resources


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and close process-owned runtime resources."""

    settings: Settings = application.state.settings
    configure_logging(settings.log_level)
    logger = structlog.get_logger("aaa.api")
    logger.info("api_starting", app_env=settings.app_env)
    try:
        resources: RuntimeResources = create_runtime_resources(settings)
    except Exception as error:
        logger.error("api_startup_failed", error_type=type(error).__name__)
        raise
    application.state.runtime = resources
    logger.info(
        "api_started",
        app_env=settings.app_env,
        dependencies=["postgresql", "redis", "minio"],
    )
    try:
        yield
    finally:
        logger.info("api_stopping")
        try:
            await resources.close()
        except Exception as error:
            logger.error("api_shutdown_failed", error_type=type(error).__name__)
            raise
        logger.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application without embedding business logic in the entry point."""

    resolved_settings = settings or get_settings()
    application = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    application.state.settings = resolved_settings
    application.add_middleware(RequestIDMiddleware)
    application.include_router(health_router)
    application.include_router(jobs_router)
    application.include_router(documents_router)
    application.include_router(curriculum_router)
    application.include_router(graphs_router)
    return application


app = create_app()
