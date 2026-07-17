"""JWT handler tests (Sprint 6).

Covers:
- Access token creation and structure
- Refresh token creation and structure
- Token decoding and verification
- Token expiration
- Token type checks
- JTI extraction
- Error handling
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_jti,
    is_access_token,
)
from app.core.config import get_settings


class TestAccessToken:
    """Access token creation and validation."""

    def test_create_access_token_returns_tuple(self) -> None:
        token, expires = create_access_token("user-123")
        assert isinstance(token, str)
        assert isinstance(expires, datetime)

    def test_create_access_token_decodes(self) -> None:
        token, _ = create_access_token("user-123")
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_access_token_expiration(self) -> None:
        token, expires = create_access_token(
            "user-123",
            expires_delta=timedelta(hours=1),
        )
        now = datetime.now(timezone.utc)
        assert expires > now
        assert expires < now + timedelta(hours=2)

    def test_access_token_jti_unique(self) -> None:
        t1, _ = create_access_token("user-123")
        t2, _ = create_access_token("user-123")
        jti1 = get_token_jti(t1)
        jti2 = get_token_jti(t2)
        assert jti1 != jti2

    def test_access_token_is_access_token(self) -> None:
        token, _ = create_access_token("user-123")
        payload = decode_token(token)
        assert is_access_token(payload) is True


class TestRefreshToken:
    """Refresh token creation and validation."""

    def test_create_refresh_token_returns_tuple(self) -> None:
        token, expires = create_refresh_token("user-123")
        assert isinstance(token, str)
        assert isinstance(expires, datetime)

    def test_refresh_token_decodes(self) -> None:
        token, _ = create_refresh_token("user-123")
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["type"] == "refresh"
        assert "jti" in payload

    def test_refresh_token_not_access(self) -> None:
        token, _ = create_refresh_token("user-123")
        payload = decode_token(token)
        assert is_access_token(payload) is False

    def test_refresh_token_longer_expiry(self) -> None:
        """Refresh tokens should expire after access tokens by default."""
        access, access_exp = create_access_token("user-123")
        refresh, refresh_exp = create_refresh_token("user-123")
        assert refresh_exp > access_exp

    def test_refresh_token_custom_expiry(self) -> None:
        token, expires = create_refresh_token(
            "user-123",
            expires_delta=timedelta(days=30),
        )
        now = datetime.now(timezone.utc)
        assert expires > now + timedelta(days=29)


class TestTokenDecoding:
    """Token decoding and error handling."""

    def test_decode_invalid_token_raises(self) -> None:
        with pytest.raises(jwt.PyJWTError):
            decode_token("invalid-token")

    def test_decode_tampered_token_raises(self) -> None:
        token, _ = create_access_token("user-123")
        # Tamper with the token
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + ".tampered"
        with pytest.raises(jwt.PyJWTError):
            decode_token(tampered)

    def test_decode_expired_token_raises(self) -> None:
        token, _ = create_access_token(
            "user-123",
            expires_delta=timedelta(seconds=-1),  # Already expired
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token)

    def test_get_token_jti_invalid(self) -> None:
        jti = get_token_jti("invalid-token")
        assert jti is None

    def test_get_token_jti_valid(self) -> None:
        token, _ = create_access_token("user-123")
        payload = decode_token(token)
        jti = get_token_jti(token)
        assert jti == payload["jti"]

    def test_get_token_jti_expired(self) -> None:
        """get_token_jti should extract JTI even from expired tokens."""
        token, _ = create_access_token(
            "user-123",
            expires_delta=timedelta(seconds=-1),
        )
        jti = get_token_jti(token)
        assert jti is not None
        assert isinstance(jti, str)


class TestExtraClaims:
    """Extra claims in access tokens."""

    def test_access_token_with_extra_claims(self) -> None:
        token, _ = create_access_token(
            "user-123",
            extra_claims={"role": "admin", "scope": "read"},
        )
        payload = decode_token(token)
        assert payload["role"] == "admin"
        assert payload["scope"] == "read"

    def test_access_token_extra_claims_in_payload(self) -> None:
        """Extra claims are merged into the token payload."""
        token, _ = create_access_token(
            "user-123",
            extra_claims={"scope": "read"},
        )
        payload = decode_token(token)
        assert payload["scope"] == "read"
        assert payload["sub"] == "user-123"  # Standard claims preserved
