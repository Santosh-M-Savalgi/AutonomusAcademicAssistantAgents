"""Rate-limit scaffolding for Sprint 0.

The architecture requires centralized rate limiting at the edge/API layer.
Sprint 0 wires middleware placement but does not implement policy logic yet.
"""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Pass-through middleware placeholder for future rate-limit policies."""

    async def dispatch(self, request: Request, call_next: Callable):
        return await call_next(request)

