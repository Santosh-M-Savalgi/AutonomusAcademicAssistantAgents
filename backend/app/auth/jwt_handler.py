"""JWT token creation, verification, and decoding (Sprint 6).

Provides short-lived access tokens and long-lived refresh tokens
with expiration, verification, and optional revocation via a blocklist.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def create_access_token(
    subject: str,
    *,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, object] | None = None,
) -> tuple[str, datetime]:
    """Create a signed JWT access token.

    Args:
        subject: The user identifier (UUID string) to embed in the token.
        expires_delta: Optional custom expiration duration.
                       Defaults from settings (ACCESS_TOKEN_EXPIRE_MINUTES).
        extra_claims: Optional dict of additional claims to include.

    Returns:
        A tuple of (encoded_token, expiration_datetime).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, object] = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "type": "access",
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expire


def create_refresh_token(
    subject: str,
    *,
    expires_delta: timedelta | None = None,
) -> tuple[str, datetime]:
    """Create a signed JWT refresh token.

    Args:
        subject: The user identifier (UUID string) to embed in the token.
        expires_delta: Optional custom expiration duration.
                       Defaults from settings (REFRESH_TOKEN_EXPIRE_DAYS).

    Returns:
        A tuple of (encoded_token, expiration_datetime).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    if expires_delta is not None:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload: dict[str, object] = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token, expire


def decode_token(token: str) -> dict[str, object]:
    """Decode and validate a JWT token.

    Args:
        token: The encoded JWT string.

    Returns:
        The decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is malformed or signature invalid.
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )  # type: ignore[no-any-return]


def get_token_jti(token: str) -> str | None:
    """Extract the JWT ID (jti) from a token without full validation.

    Useful for revoking tokens before they expire.

    Args:
        token: The encoded JWT string.

    Returns:
        The JTI string or None if extraction fails.
    """
    try:
        settings = get_settings()
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        return payload.get("jti")  # type: ignore[no-any-return]
    except jwt.PyJWTError:
        return None


def is_access_token(payload: dict[str, object]) -> bool:
    """Check whether a decoded token payload is an access token.

    Args:
        payload: The decoded JWT payload.

    Returns:
        True if the token type is 'access'.
    """
    return payload.get("type") == "access"
