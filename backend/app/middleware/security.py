"""Security headers middleware for AAA v2.

Automatically adds security-related HTTP headers to every response:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Content-Security-Policy: restricted defaults
"""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Default security headers applied to every response
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    ),
    "X-XSS-Protection": "0",  # Deprecated but still serves as signal
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to every response.

    Applied after the request is processed but before the response is
    sent to ensure headers are present on all responses, including errors.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)

        for header_name, header_value in _SECURITY_HEADERS.items():
            if header_name not in response.headers:
                response.headers[header_name] = header_value

        return response
