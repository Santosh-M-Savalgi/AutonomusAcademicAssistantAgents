"""Request correlation middleware for AAA v2.

Generates and propagates X-Request-ID headers, stores them in contextvars
so that all layers (services, repositories, workers, logs) can access the
current request ID without threading it through every function signature.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_user_id_ctx: ContextVar[str] = ContextVar("user_id", default="")
_session_id_ctx: ContextVar[str] = ContextVar("session_id", default="")
_job_id_ctx: ContextVar[str] = ContextVar("job_id", default="")


def get_request_id() -> str:
    """Return the current request ID from context, or empty string."""
    return _request_id_ctx.get()


def get_user_id() -> str:
    """Return the current user ID from context, or empty string."""
    return _user_id_ctx.get()


def get_session_id() -> str:
    """Return the current session ID from context, or empty string."""
    return _session_id_ctx.get()


def get_job_id() -> str:
    """Return the current job ID from context, or empty string."""
    return _job_id_ctx.get()


def set_job_id(job_id: str) -> None:
    """Set the job ID in context (used by background workers)."""
    _job_id_ctx.set(job_id)


def set_user_id(user_id: str) -> None:
    """Set the user ID in context (used after auth resolution)."""
    _user_id_ctx.set(user_id)


def set_session_id(session_id: str) -> None:
    """Set the session ID in context."""
    _session_id_ctx.set(session_id)


def _get_request_id_from_request(request: Request) -> str:
    """Extract or generate a request ID from the incoming request."""
    return request.headers.get("x-request-id", str(uuid.uuid4()))


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware that ensures every request has a unique X-Request-ID.

    - Generates one if the client did not supply one.
    - Stores it in request.state and a contextvar.
    - Also captures user_id (after auth) and session_id from headers.
    - Returns the ID in the response header.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        request_id = _get_request_id_from_request(request)
        session_id = request.headers.get("x-session-id") or request.query_params.get("session_id", "")

        # Store in request.state for middleware chain access
        request.state.request_id = request_id
        request.state.session_id = session_id

        # Set contextvars
        _request_id_ctx.set(request_id)
        if session_id:
            _session_id_ctx.set(session_id)

        response = await call_next(request)

        # Attach request ID to the response
        response.headers["X-Request-ID"] = request_id
        if session_id:
            response.headers["X-Session-ID"] = session_id

        return response
