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

from app.middleware.request_context import get_request_id


class DatabaseError(Exception):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database error", *, cause: Exception | None = None) -> None:
        self.message = message
        self.cause = cause
        super().__init__(message)


class RedisError(Exception):
    """Raised when a Redis operation fails."""

    def __init__(self, message: str = "Redis error", *, cause: Exception | None = None) -> None:
        self.message = message
        self.cause = cause
        super().__init__(message)


class ProviderError(Exception):
    """Raised when an external provider (LLM, embedding, etc.) fails."""

    def __init__(
        self, message: str = "Provider error", *, provider: str = "unknown", cause: Exception | None = None
    ) -> None:
        self.message = message
        self.provider = provider
        self.cause = cause
        super().__init__(message)


class UnknownException(Exception):
    """Wrapper for unexpected exceptions to ensure consistent error shape."""

    def __init__(self, message: str = "An unexpected error occurred", *, cause: Exception | None = None) -> None:
        self.message = message
        self.cause = cause
        super().__init__(message)


def _error_response(error_type: str, message: str, status_code: int) -> dict[str, Any]:
    """Build a consistent error response body."""
    return {
        "error": error_type,
        "message": message,
        "request_id": get_request_id(),
    }


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Top-level exception handler for the FastAPI application.

    Maps known exception types to appropriate HTTP status codes and
    returns a consistent JSON response body.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_response("HTTPException", exc.detail, exc.status_code),
        )

    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_response("HTTPException", exc.detail, exc.status_code),
        )

    if isinstance(exc, DatabaseError):
        return JSONResponse(
            status_code=500,
            content=_error_response("DatabaseError", exc.message, 500),
        )

    if isinstance(exc, RedisError):
        return JSONResponse(
            status_code=503,
            content=_error_response("RedisError", exc.message, 503),
        )

    if isinstance(exc, ProviderError):
        return JSONResponse(
            status_code=502,
            content=_error_response("ProviderError", exc.message, 502),
        )

    if isinstance(exc, ValueError):
        return JSONResponse(
            status_code=422,
            content=_error_response("ValidationError", str(exc), 422),
        )

    # Catch-all for unexpected exceptions
    return JSONResponse(
        status_code=500,
        content=_error_response("UnknownException", "An unexpected error occurred", 500),
    )


def register_exception_handlers(app: Any) -> None:
    """Register exception handlers on a FastAPI application instance.

    Args:
        app: A FastAPI application instance.
    """
    app.add_exception_handler(Exception, global_exception_handler)
