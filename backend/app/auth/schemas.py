"""Auth API request/response schemas (Sprint 6)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Request payload for user registration."""

    email: EmailStr = Field(..., description="User email address")
    username: str = Field(
        ...,
        min_length=3,
        max_length=150,
        description="Unique username",
        pattern=r"^[a-zA-Z0-9_]+$",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (must meet policy requirements)",
    )
    role: str | None = Field(None, description="Optional role override (default: student)")


class LoginRequest(BaseModel):
    """Request payload for user login."""

    email_or_username: str = Field(
        ...,
        description="Email address or username",
    )
    password: str = Field(
        ...,
        min_length=1,
        description="User password",
    )


class RefreshRequest(BaseModel):
    """Request payload for token refresh."""

    refresh_token: str = Field(..., description="Valid refresh token")


class ChangePasswordRequest(BaseModel):
    """Request payload for password change."""

    current_password: str = Field(..., description="Current password")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password (must meet policy requirements)",
    )


class UserResponse(BaseModel):
    """Public user information returned in auth responses."""

    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email")
    username: str = Field(..., description="User username")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="Whether the user account is active")


class TokenResponse(BaseModel):
    """Response payload for login and token refresh."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("bearer", description="Token type")
    expires_in: int = Field(..., description="Access token expiration timestamp (Unix)")
    user: UserResponse = Field(..., description="Authenticated user info")


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str = Field(..., description="Human-readable status message")
