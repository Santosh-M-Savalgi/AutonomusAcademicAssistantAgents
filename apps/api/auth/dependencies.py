"""Reusable FastAPI authentication dependencies."""

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from apps.api.auth.jwt import InvalidTokenError, JWTConfigurationError, JWTService
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.config import Settings, get_settings

_bearer_scheme = HTTPBearer(auto_error=False)
logger = structlog.get_logger("aaa.auth")


def _authentication_error(detail: str = "Not authenticated") -> HTTPException:
    """Create a uniform 401 response without exposing credential details."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> AuthenticatedIdentity:
    """Return the identity from a valid Bearer access token.

    This foundation dependency deliberately does not query a user table. Later
    application layers can resolve the opaque subject against their own store.
    """

    if credentials is None:
        logger.info("authentication_rejected", reason="missing_credentials")
        raise _authentication_error()

    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        settings = get_settings()

    try:
        claims = JWTService(settings).validate_access_token(credentials.credentials)
    except JWTConfigurationError:
        logger.error("authentication_configuration_error")
        raise _authentication_error("Authentication is not configured") from None
    except InvalidTokenError:
        logger.info("authentication_rejected", reason="invalid_token")
        raise _authentication_error("Invalid or expired token") from None

    return AuthenticatedIdentity.from_claims(claims)
