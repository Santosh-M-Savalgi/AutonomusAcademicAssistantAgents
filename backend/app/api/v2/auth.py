"""Authentication endpoints (Sprint 6).

Provides user registration, login, token refresh, logout,
current-user info retrieval, and password change.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.service import (
    change_user_password,
    login_user,
    refresh_user_token,
    register_user,
    revoke_refresh_tokens,
)
from app.db.models import User
from app.db.postgres import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Register a new user account.

    Creates a user with the given email, username, and password.
    The password is hashed with bcrypt before storage.
    Default role is 'student'.
    """
    try:
        user = await register_user(db, request)
        await db.commit()
        logger.info("User registered: %s (id=%s)", user.email, user.id)
        return MessageResponse(message="User registered successfully")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if "already exists" in str(exc) else status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate a user and return access + refresh tokens.

    Accepts either email or username in the email_or_username field.
    Returns JWT access token (short-lived) and refresh token (long-lived).
    """
    try:
        result = await login_user(db, request)
        await db.commit()
        logger.info("User logged in: %s", result.user.email)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Refresh an expired access token using a valid refresh token.

    Implements refresh token rotation: the old refresh token is revoked
    and a new one is issued.
    """
    try:
        result = await refresh_user_token(db, request.refresh_token)
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Log out the current user by revoking all active refresh tokens."""
    count = await revoke_refresh_tokens(db, current_user.id)
    await db.commit()
    logger.info("User logged out: %s (%d tokens revoked)", current_user.email, count)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        username=current_user.username,
        role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        is_active=current_user.is_active,
    )


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Change the current user's password.

    Requires the current password for verification.
    The new password must meet the configured password policy.
    """
    try:
        await change_user_password(db, current_user, request.current_password, request.new_password)
        await db.commit()
        logger.info("Password changed for user: %s", current_user.email)
        return MessageResponse(message="Password changed successfully")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
