"""JWT signing and validation isolated from FastAPI route handlers."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from pydantic import ValidationError

from apps.api.auth.schemas import TokenClaims, TokenType
from apps.api.config import Settings, get_settings


class JWTConfigurationError(RuntimeError):
    """Raised when token signing is attempted without safe JWT configuration."""


class InvalidTokenError(ValueError):
    """Raised when a token cannot be trusted or does not satisfy its contract."""


_RESERVED_CLAIMS = frozenset({"sub", "iat", "exp", "jti", "token_type", "iss", "aud"})
_UNSAFE_SECRET_PREFIXES = ("replace-with-", "change-me")


class JWTService:
    """Create and validate signed JWT access and refresh tokens."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _secret(self) -> str:
        configured_secret = self.settings.jwt_secret_key
        if configured_secret is None:
            raise JWTConfigurationError("JWT signing key is not configured")

        secret = configured_secret.get_secret_value()
        if len(secret) < 32:
            raise JWTConfigurationError("JWT signing key does not meet the minimum length")
        if secret.strip().lower().startswith(_UNSAFE_SECRET_PREFIXES):
            raise JWTConfigurationError("JWT signing key must be replaced with a random value")
        return secret

    def create_access_token(
        self,
        subject: str,
        *,
        expires_delta: timedelta | None = None,
        additional_claims: Mapping[str, object] | None = None,
    ) -> str:
        """Create a short-lived access token for an opaque subject identifier."""

        return self._create_token(
            subject,
            token_type="access",
            expires_delta=expires_delta
            or timedelta(minutes=self.settings.jwt_access_token_expire_minutes),
            additional_claims=additional_claims,
        )

    def create_refresh_token(
        self,
        subject: str,
        *,
        expires_delta: timedelta | None = None,
        additional_claims: Mapping[str, object] | None = None,
    ) -> str:
        """Create a refresh token for a later refresh-token product flow."""

        return self._create_token(
            subject,
            token_type="refresh",
            expires_delta=expires_delta
            or timedelta(days=self.settings.jwt_refresh_token_expire_days),
            additional_claims=additional_claims,
        )

    def _create_token(
        self,
        subject: str,
        *,
        token_type: TokenType,
        expires_delta: timedelta,
        additional_claims: Mapping[str, object] | None,
    ) -> str:
        if not subject:
            raise ValueError("Token subject must not be empty")

        extra = dict(additional_claims or {})
        reserved = _RESERVED_CLAIMS.intersection(extra)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"Additional claims cannot override reserved claims: {names}")

        now = datetime.now(UTC)
        expires_at = now + expires_delta
        payload: dict[str, object] = {
            "sub": subject,
            "iat": now,
            "exp": expires_at,
            "jti": str(uuid4()),
            "token_type": token_type,
            "iss": self.settings.jwt_issuer,
            "aud": self.settings.jwt_audience,
            **extra,
        }
        return jwt.encode(
            payload,
            self._secret(),
            algorithm=self.settings.jwt_algorithm,
        )

    def decode_token(self, token: str) -> TokenClaims:
        """Decode and validate signature, expiry, issuer, audience, and required claims."""

        if not token:
            raise InvalidTokenError("Invalid or expired token")

        try:
            payload = jwt.decode(
                token,
                self._secret(),
                algorithms=[self.settings.jwt_algorithm],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                options={
                    "require": [
                        "sub",
                        "iat",
                        "exp",
                        "jti",
                        "token_type",
                        "iss",
                        "aud",
                    ]
                },
            )
            return TokenClaims.model_validate(payload)
        except (jwt.PyJWTError, ValidationError) as error:
            raise InvalidTokenError("Invalid or expired token") from error

    def validate_access_token(self, token: str) -> TokenClaims:
        """Validate a token and require that it is an access token."""

        claims = self.decode_token(token)
        if claims.token_type != "access":
            raise InvalidTokenError("Invalid token type")
        return claims
