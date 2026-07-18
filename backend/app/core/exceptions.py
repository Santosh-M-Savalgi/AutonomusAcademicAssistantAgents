"""Global exception handler for AAA v2.

Provides consistent JSON error responses for all exception types,
including validation errors, HTTP exceptions, database errors,
Redis errors, provider errors, and unexpected exceptions.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.llm.providers.base import ProviderRateLimitError, ProviderTimeoutError
from app.middleware.request_context import get_request_id


class BackendError(Exception):
    """Base for all structured backend errors.

    Carries an ``error_code`` (machine-readable), ``message`` (user-friendly),
    ``http_status``, and ``retryable`` flag so the frontend can choose the
    correct UX treatment without parsing the message string.
    """

    def __init__(
        self,
        error_code: str,
        message: str = "An unexpected error occurred",
        *,
        http_status: int = 500,
        retryable: bool = False,
        cause: Exception | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.cause = cause
        super().__init__(message)


class DatabaseError(BackendError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database error", *, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="DATABASE_ERROR",
            message=message,
            http_status=500,
            retryable=True,
            cause=cause,
        )


class RedisError(BackendError):
    """Raised when a Redis operation fails."""

    def __init__(self, message: str = "Redis error", *, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="CACHE_UNAVAILABLE",
            message=message,
            http_status=503,
            retryable=True,
            cause=cause,
        )


class ProviderError(BackendError):
    """Raised when an external provider (LLM, embedding, etc.) fails."""

    def __init__(
        self, message: str = "Provider error", *, provider: str = "unknown", cause: Exception | None = None
    ) -> None:
        self.provider = provider
        super().__init__(
            error_code="AI_PROVIDER_ERROR",
            message=message,
            http_status=502,
            retryable=True,
            cause=cause,
        )


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""

    def __init__(self, provider: str = "unknown", timeout_seconds: float = 0.0) -> None:
        super().__init__(
            message="AI service is temporarily busy. Your progress has been saved. Please wait a few minutes and try again.",
            provider=provider,
        )
        self.error_code = "AI_PROVIDER_TIMEOUT"
        self.http_status = 504


class ProviderRateLimitError(ProviderError):
    """Raised when a provider returns a rate-limit response."""

    def __init__(self, provider: str = "unknown", retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            message="AI service is temporarily busy. Your progress has been saved. Please wait a few minutes and try again.",
            provider=provider,
        )
        self.error_code = "AI_PROVIDER_BUSY"
        self.http_status = 429


class DomainError(BackendError):
    """Raised for domain-logic errors that should be user-visible.

    Examples: duplicate topic slug, invalid goal, session expired.
    """

    def __init__(
        self,
        error_code: str = "UNKNOWN_ERROR",
        message: str = "An unexpected error occurred",
        *,
        http_status: int = 400,
        retryable: bool = False,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            http_status=http_status,
            retryable=retryable,
            cause=cause,
        )


class RoadmapGenerationError(DomainError):
    """Raised when the adaptive pipeline cannot build a roadmap."""

    def __init__(self, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="ROADMAP_GENERATION_FAILED",
            message="Unable to generate your learning plan at the moment. Please try again.",
            http_status=500,
            retryable=True,
            cause=cause,
        )


class SyllabusParseError(DomainError):
    """Raised when the LLM cannot parse a learning goal."""

    def __init__(self, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="SYLLABUS_PARSE_FAILED",
            message="Unable to analyze your learning goal. Please try rephrasing it.",
            http_status=502,
            retryable=True,
            cause=cause,
        )


class InvalidInputError(DomainError):
    """Raised when user input fails validation."""

    def __init__(self, message: str = "Please check your input and try again.") -> None:
        super().__init__(
            error_code="INVALID_INPUT",
            message=message,
            http_status=422,
            retryable=False,
        )


class DatabaseConflictError(DomainError):
    """Raised on integrity violations (duplicate key, FK violation)."""

    def __init__(self, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="DATABASE_CONFLICT",
            message="We encountered a data synchronization issue. Please try again.",
            http_status=409,
            retryable=True,
            cause=cause,
        )


class UnknownException(BackendError):
    """Wrapper for unexpected exceptions to ensure consistent error shape."""

    def __init__(self, message: str = "An unexpected error occurred", *, cause: Exception | None = None) -> None:
        super().__init__(
            error_code="UNKNOWN_ERROR",
            message=message,
            http_status=500,
            retryable=False,
            cause=cause,
        )


def _error_response(exc: BackendError) -> dict[str, Any]:
    """Build a consistent error response body from a BackendError."""
    return {
        "success": False,
        "error_code": exc.error_code,
        "message": exc.message,
        "retryable": exc.retryable,
        "request_id": get_request_id(),
    }


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Top-level exception handler for the FastAPI application.

    Maps known exception types to appropriate HTTP status codes and
    returns a consistent JSON response body with ``success``, ``error_code``,
    ``message``, and ``retryable`` fields.
    """
    import logging

    logger = logging.getLogger(__name__)

    # FastAPI HTTPExceptions — pass through as-is
    if isinstance(exc, HTTPException):
        code = "HTTP_ERROR"
        if exc.status_code == 400:
            code = "INVALID_INPUT"
        elif exc.status_code == 401:
            code = "UNAUTHORIZED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 422:
            code = "VALIDATION_ERROR"
        logger.warning("HTTP %d: %s", exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": code,
                "message": exc.detail,
                "retryable": exc.status_code >= 500,
                "request_id": get_request_id(),
            },
        )

    if isinstance(exc, StarletteHTTPException):
        logger.warning("Starlette HTTP %d: %s", exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": "HTTP_ERROR",
                "message": exc.detail,
                "retryable": exc.status_code >= 500,
                "request_id": get_request_id(),
            },
        )

    # Structured BackendErrors — use the error's own fields
    if isinstance(exc, BackendError):
        if exc.http_status >= 500:
            logger.exception(
                "BackendError %s (status=%d, retryable=%s): %s",
                exc.error_code, exc.http_status, exc.retryable, exc.message,
                exc_info=exc.cause,
            )
        else:
            logger.warning(
                "BackendError %s (status=%d): %s",
                exc.error_code, exc.http_status, exc.message,
            )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_response(exc),
        )

    # Python built-in: ValueError → 422
    if isinstance(exc, ValueError):
        logger.warning("ValueError: %s", exc)
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "message": str(exc),
                "retryable": False,
                "request_id": get_request_id(),
            },
        )

    # Catch-all for anything else — log the full traceback
    logger.exception("Unhandled exception: %s: %s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "UNKNOWN_ERROR",
            "message": "Something unexpected happened. Please try again later.",
            "retryable": True,
            "request_id": get_request_id(),
        },
    )


def register_exception_handlers(app: Any) -> None:
    """Register exception handlers on a FastAPI application instance.

    Args:
        app: A FastAPI application instance.
    """
    app.add_exception_handler(Exception, global_exception_handler)
