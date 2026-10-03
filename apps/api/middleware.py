"""HTTP middleware for request correlation."""

import re
from time import perf_counter
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _request_id(request: Request) -> str:
    """Accept a safe caller correlation ID or generate a fresh UUID."""

    supplied = request.headers.get("X-Request-ID", "")
    if _REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return str(uuid4())


class RequestIDMiddleware:
    """Correlate the entire ASGI response, including streaming and error paths."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = _request_id(request)
        request.state.request_id = request_id
        previous_context = structlog.contextvars.get_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = perf_counter()
        logger = structlog.get_logger("aaa.api")
        status_code = 500
        response_started = False

        async def send_response(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                response_started = True
            await send(message)

        def fields() -> dict[str, object]:
            # Never log raw paths: path parameters and 404 URLs can contain PII.
            route = getattr(scope.get("route"), "path", "unmatched")
            return {
                "route": route,
                "method": request.method if request.method in {
                    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"
                } else "OTHER",
                "status_code": status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            }

        try:
            await self.app(scope, receive, send_response)
        except Exception as error:
            logger.error(
                "request_failed",
                error_type=type(error).__name__,
                **fields(),
            )
            if response_started:
                # Headers cannot be changed after a streaming response begins.
                raise RuntimeError("Response failed after headers were sent") from None
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
            await response(scope, receive, send_response)
        else:
            if status_code == 503:
                logger.warning("request_unavailable", **fields())
            elif status_code >= 500:
                logger.error("request_failed", **fields())
            elif status_code >= 400:
                logger.info("request_rejected", **fields())
            else:
                logger.info("request_complete", **fields())
        finally:
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(**previous_context)
