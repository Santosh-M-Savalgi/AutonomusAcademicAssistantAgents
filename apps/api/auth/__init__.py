"""Reusable authentication primitives for the AAA v3 API."""

from apps.api.auth.dependencies import get_current_identity
from apps.api.auth.jwt import InvalidTokenError, JWTConfigurationError, JWTService
from apps.api.auth.passwords import hash_password, verify_password
from apps.api.auth.schemas import AuthenticatedIdentity, TokenClaims, TokenType

__all__ = [
    "AuthenticatedIdentity",
    "InvalidTokenError",
    "JWTConfigurationError",
    "JWTService",
    "TokenClaims",
    "TokenType",
    "get_current_identity",
    "hash_password",
    "verify_password",
]
