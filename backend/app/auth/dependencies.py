"""FastAPI dependencies for authentication and authorization (Sprint 6).

Provides:
- get_current_user: extracts and validates the authenticated user from JWT
- get_current_student: ensures the user has the student role
- require_admin: ensures the user has the admin role
- get_current_user_optional: optional auth (does not reject unauthenticated)
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import decode_token, is_access_token
from app.db.models import User
from app.db.postgres import get_db

_security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current authenticated user from the JWT.

    Requires a valid Bearer access token in the Authorization header.

    Args:
        credentials: HTTPBearer credentials from the request.
        db: Database session.

    Returns:
        The authenticated User instance.

    Raises:
        HTTPException 401: If no token, token is invalid, expired,
                           or user not found/disabled.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not is_access_token(payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — use an access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    return user


async def get_current_student(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to have the 'student' role.

    Args:
        current_user: The authenticated user from get_current_user.

    Returns:
        The user if they are a student.

    Raises:
        HTTPException 403: If the user is not a student.
    """
    if current_user.role not in ("student", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can access this resource",
        )
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to have the 'admin' role.

    Args:
        current_user: The authenticated user from get_current_user.

    Returns:
        The user if they are an administrator.

    Raises:
        HTTPException 403: If the user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Optionally extract the current user, returning None if not authenticated.

    Does not raise on missing/invalid tokens — use for endpoints where
    authentication is optional.

    Args:
        credentials: HTTPBearer credentials from the request.
        db: Database session.

    Returns:
        The authenticated User instance, or None.
    """
    if credentials is None:
        return None

    try:
        payload = decode_token(credentials.credentials)
    except Exception:
        return None

    if not is_access_token(payload):
        return None

    subject = payload.get("sub")
    if subject is None:
        return None

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None

    return user
