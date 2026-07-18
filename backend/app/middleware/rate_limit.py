"""Rate limiting middleware for AAA v2.

Redis-backed rate limiting with three tiers:
- Anonymous: 60 requests per minute
- Authenticated: 300 requests per minute
- Admin: 1000 requests per minute

Returns 429 Too Many Requests with Retry-After header when the limit is exceeded.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.core.config import get_settings
from app.db.redis import get_redis

# Rate limit configuration: (requests, window_seconds) per tier
ANONYMOUS_LIMIT = 60
ANONYMOUS_WINDOW = 60

AUTHENTICATED_LIMIT = 300
AUTHENTICATED_WINDOW = 60

ADMIN_LIMIT = 1000
ADMIN_WINDOW = 60


def _rate_limit_key(request: Request) -> tuple[str, int, int]:
    """Determine the rate limit key and limits for a request.

    Returns:
        A tuple of (redis_key, max_requests, window_seconds).
    """
    settings = get_settings()

    # Check for admin API key or role
    api_key = request.headers.get("x-api-key", "")
    if api_key and api_key == getattr(settings, "admin_api_key", ""):
        return _make_key("admin", request), ADMIN_LIMIT, ADMIN_WINDOW

    # Check for authenticated user
    user_id = getattr(request.state, "user_id", None) or request.headers.get("x-user-id", "")
    if user_id:
        return _make_key(f"user:{user_id}", request), AUTHENTICATED_LIMIT, AUTHENTICATED_WINDOW

    # Check for bearer token (indicates authenticated even if not resolved)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token_prefix = auth_header[7:20]  # Use first 13 chars of token
        return _make_key(f"token:{token_prefix}", request), AUTHENTICATED_LIMIT, AUTHENTICATED_WINDOW

    # Anonymous
    client_ip = request.client.host if request.client else "unknown"
    return _make_key(f"anon:{client_ip}", request), ANONYMOUS_LIMIT, ANONYMOUS_WINDOW


def _make_key(prefix: str, request: Request) -> str:
    """Create a Redis key for rate limiting."""
    route = f"{request.method}:{request.url.path}"
    return f"ratelimit:{prefix}:{route}"


async def _check_rate_limit(key: str, max_requests: int, window: int) -> tuple[bool, int]:
    """Check if a request is within the rate limit.

    Uses a sliding window approach via Redis sorted sets.

    Args:
        key: The Redis key for this rate limit bucket.
        max_requests: Maximum allowed requests in the window.
        window: Time window in seconds.

    Returns:
        A tuple of (allowed, retry_after_seconds).
    """
    now = time.time()
    window_start = now - window

    redis = get_redis()
    pipeline = redis.pipeline()

    # Remove entries outside the window
    pipeline.zremrangebyscore(key, 0, window_start)
    # Count remaining entries
    pipeline.zcard(key)
    # Add current request
    pipeline.zadd(key, {str(now): now})
    # Set TTL on the key
    pipeline.expire(key, window)

    results = await pipeline.execute()
    count = results[1]  # zcard result

    if count > max_requests:
        # Get the oldest entry's timestamp to calculate retry-after
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(window - (now - oldest[0][1])) + 1
        else:
            retry_after = window
        return False, retry_after

    return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed rate limiting middleware.

    Applies per-route sliding window rate limits with three tiers:
    anonymous, authenticated, and admin.

    Requires a running Redis instance. Degrades gracefully if Redis is
    unavailable by allowing the request through.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        settings = get_settings()
        if not settings.enable_rate_limit:
            return await call_next(request)

        # Skip rate limiting for health/metrics endpoints
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return await call_next(request)

        key, max_reqs, window = _rate_limit_key(request)

        try:
            allowed, retry_after = await _check_rate_limit(key, max_reqs, window)
        except Exception:
            # Degrade gracefully: if Redis is down, allow the request
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "RateLimitExceeded",
                    "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "request_id": getattr(request.state, "request_id", ""),
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
