"""HTTP middleware for request correlation."""

from time import perf_counter
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind one request ID to logs and return it to the caller."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        tokens = structlog.contextvars.bind_contextvars(request_id=request_id)
        started = perf_counter()
        logger = structlog.get_logger("aaa.api")
        try:
            response = await call_next(request)  # type: ignore[operator]
        except Exception:
            logger.exception("request_failed", path=request.url.path, method=request.method)
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_complete",
                path=request.url.path,
                method=request.method,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.reset_contextvars(**tokens)
