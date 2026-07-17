"""Structured logging setup for AAA v2.

Provides JSON structured logging with automatic enrichment from request context
(request_id, user_id, session_id, job_id), performance monitoring (slow request
logging), and configurable log levels.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings
from app.middleware.request_context import get_job_id, get_request_id, get_session_id, get_user_id

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - exercised only in partial local envs
    structlog = None


def configure_logging(level: str) -> None:
    """Configure JSON structured logging for the process.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s", stream=sys.stdout, force=True)

    if structlog is None:
        return

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _get_log_context() -> dict[str, str]:
    """Collect context from contextvars for log enrichment."""
    ctx: dict[str, str] = {}
    rid = get_request_id()
    uid = get_user_id()
    sid = get_session_id()
    jid = get_job_id()
    if rid:
        ctx["request_id"] = rid
    if uid:
        ctx["user_id"] = uid
    if sid:
        ctx["session_id"] = sid
    if jid:
        ctx["job_id"] = jid
    return ctx


class _FallbackBoundLogger:
    """Fallback logger when structlog is not available."""

    def __init__(self, **context: str) -> None:
        self._logger = logging.getLogger("aaa.request")
        self._context = context

    def _log(self, level: int, event: str, **fields: Any) -> None:
        extra = {**self._context, **fields}
        self._logger.log(level, event, extra=extra)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)

    def critical(self, event: str, **fields: Any) -> None:
        self._log(logging.CRITICAL, event, **fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._logger.exception(event, extra={**self._context, **fields})


def _bound_request_logger(**context: str) -> Any:
    """Create a bound logger with the given context."""
    enriched = {**_get_log_context(), **context}
    if structlog is not None:
        return structlog.get_logger().bind(**enriched)
    return _FallbackBoundLogger(**enriched)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request-scoped structured logging with request and session correlation.

    Produces JSON log entries for every request with:
    - request_id, user_id, session_id
    - path, method, status_code
    - duration_ms
    - Automatic slow request logging (> threshold)
    """

    async def dispatch(self, request: Request, call_next: Callable):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        session_id = request.headers.get("x-session-id") or request.query_params.get("session_id")

        # Merge context from request headers and contextvars
        log_context: dict[str, str] = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        if session_id:
            log_context["session_id"] = session_id

        logger = _bound_request_logger(**log_context)
        settings = get_settings()

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
            log_data: dict[str, Any] = {
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
            }

            # Log slow requests automatically
            if elapsed_ms > settings.slow_request_threshold_ms:
                log_data["slow"] = True
                logger.warning("slow_request", **log_data)
            else:
                logger.info("request_finished", **log_data)

            response.headers["x-request-id"] = request_id
            if session_id:
                response.headers["x-session-id"] = session_id
            return response
