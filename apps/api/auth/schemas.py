"""Typed authentication contracts used by the token service and dependencies."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TokenType = Literal["access", "refresh"]


class TokenClaims(BaseModel):
    """Claims required in every AAA v3 authentication token."""

    model_config = ConfigDict(extra="allow")

    subject: str = Field(alias="sub", min_length=1)
    issued_at: datetime = Field(alias="iat")
    expires_at: datetime = Field(alias="exp")
    token_id: str = Field(alias="jti", min_length=1)
    token_type: TokenType = Field(alias="token_type")
    issuer: str = Field(alias="iss", min_length=1)
    audience: str = Field(alias="aud", min_length=1)


class AuthenticatedIdentity(BaseModel):
    """Identity made available to protected API endpoints after token validation."""

    subject: str = Field(min_length=1)
    token_id: str = Field(min_length=1)
    token_type: TokenType
    claims: TokenClaims

    @classmethod
    def from_claims(cls, claims: TokenClaims) -> "AuthenticatedIdentity":
        """Build the request identity from already validated token claims."""

        return cls(
            subject=claims.subject,
            token_id=claims.token_id,
            token_type=claims.token_type,
            claims=claims,
        )
