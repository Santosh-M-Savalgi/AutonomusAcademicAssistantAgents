"""Structured logging setup for AAA v2."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - exercised only in partial local envs
    structlog = None


def configure_logging(level: str) -> None:
    """Configure JSON structured logging for the process."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s", stream=sys.stdout, force=True)

    if structlog is None:
        return
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


class _FallbackBoundLogger:
    def __init__(self, **context):
        self._logger = logging.getLogger("aaa.request")
        self._context = context

    def info(self, event: str, **fields) -> None:
        self._logger.info(event, extra={**self._context, **fields})

    def exception(self, event: str, **fields) -> None:
        self._logger.exception(event, extra={**self._context, **fields})


def _bound_request_logger(**context):
    if structlog is not None:
        return structlog.get_logger().bind(**context)
    return _FallbackBoundLogger(**context)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request-scoped structured logging with request and session correlation."""

    async def dispatch(self, request: Request, call_next: Callable):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        session_id = request.headers.get("x-session-id") or request.query_params.get("session_id")
        logger = _bound_request_logger(
            request_id=request_id,
            session_id=session_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        logger.info("request_started")
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception("request_failed", duration_ms=elapsed_ms)
            raise
        else:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request_finished",
                status_code=response.status_code,
                duration_ms=elapsed_ms,
            )
            response.headers["x-request-id"] = request_id
            if session_id:
                response.headers["x-session-id"] = session_id
            return response
