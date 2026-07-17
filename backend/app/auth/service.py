"""Auth service layer — user registration, login, token lifecycle (Sprint 6).

Provides the business logic behind the authentication API endpoints,
including user creation, credential verification, token generation,
and refresh token rotation.

Note on refresh token storage:
    JWT refresh tokens exceed bcrypt's 72-byte input limit (bcrypt >= 5.0).
    We hash the JWT token id (jti) instead, which is unique per token
    and fits within bcrypt's input constraint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_jti,
    is_access_token,
)
from app.auth.password import (
    hash_password,
    validate_password,
    verify_password,
)
from app.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.db.models import RefreshToken, User
from app.db.models.enums import UserRole


def _hash_token(token: str) -> str:
    """Hash a JWT token for secure storage.

    JWT tokens exceed bcrypt's 72-byte input limit (bcrypt >= 5.0).
    We hash the JWT id (jti) instead of the full token string,
    which is unique and within the input limit.

    Args:
        token: The JWT token string.

    Returns:
        A bcrypt hash of the token's jti.
    """
    jti = get_token_jti(token)
    if jti is None:
        raise ValueError("Cannot extract jti from token")
    return hash_password(jti)


def _token_matches_hash(token: str, token_hash: str) -> bool:
    """Verify that a JWT token matches a stored hash.

    Uses the token's jti (JWT id) for comparison, matching the
    approach used in _hash_token.

    Args:
        token: The JWT token string.
        token_hash: The stored bcrypt hash.

    Returns:
        True if the token's jti matches the hash.
    """
    jti = get_token_jti(token)
    if jti is None:
        return False
    return verify_password(jti, token_hash)


async def register_user(
    db: AsyncSession,
    request: RegisterRequest,
) -> User:
    """Register a new user.

    Validates the password policy, checks for duplicate email/username,
    hashes the password, and persists the user.

    Args:
        db: Database session.
        request: Registration payload.

    Returns:
        The newly created User instance.

    Raises:
        ValueError: If email or username already exists, or password is weak.
    """
    # Check for existing email
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none() is not None:
        raise ValueError("A user with this email already exists")

    # Check for existing username
    result = await db.execute(select(User).where(User.username == request.username))
    if result.scalar_one_or_none() is not None:
        raise ValueError("A user with this username already exists")

    # Validate password
    validation = validate_password(request.password)
    if not validation.valid:
        raise ValueError(validation.message)

    # Hash password and create user
    password_hash_value = hash_password(request.password)
    user = User(
        email=request.email,
        username=request.username,
        password_hash=password_hash_value,
        role=request.role if request.role else UserRole.student,
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(
    db: AsyncSession,
    request: LoginRequest,
) -> User:
    """Authenticate a user by email/username and password.

    Args:
        db: Database session.
        request: Login payload (email or username + password).

    Returns:
        The authenticated User instance.

    Raises:
        ValueError: If credentials are invalid or account is disabled.
    """
    # Try to find by email or username
    result = await db.execute(
        select(User).where(
            (User.email == request.email_or_username)
            | (User.username == request.email_or_username)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise ValueError("Invalid credentials")

    if not user.is_active:
        raise ValueError("Account is disabled")

    if not verify_password(request.password, user.password_hash):
        raise ValueError("Invalid credentials")

    return user


async def login_user(
    db: AsyncSession,
    request: LoginRequest,
) -> TokenResponse:
    """Authenticate a user and generate access + refresh tokens.

    Updates the user's last_login timestamp.

    Args:
        db: Database session.
        request: Login payload.

    Returns:
        A TokenResponse with access token, refresh token, and user info.
    """
    user = await authenticate_user(db, request)

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.flush()

    access_token, access_expires = create_access_token(str(user.id))
    refresh_token, refresh_expires = create_refresh_token(str(user.id))

    # Store hashed refresh token (using jti, not full token)
    refresh_token_hash = _hash_token(refresh_token)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_token_hash,
        expires_at=refresh_expires,
        revoked=False,
    )
    db.add(rt)
    await db.flush()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=int(access_expires.timestamp()),
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            is_active=user.is_active,
        ),
    )


async def refresh_user_token(
    db: AsyncSession,
    refresh_token_str: str,
) -> TokenResponse:
    """Refresh an access token using a valid refresh token.

    Implements refresh token rotation: the old refresh token is revoked
    and a new one is issued.

    Args:
        db: Database session.
        refresh_token_str: The refresh token string.

    Returns:
        A TokenResponse with new access and refresh tokens.

    Raises:
        ValueError: If the refresh token is invalid or revoked.
    """
    # Decode the refresh token
    try:
        payload = decode_token(refresh_token_str)
    except Exception as exc:
        raise ValueError("Invalid refresh token") from exc

    if is_access_token(payload):
        raise ValueError("Cannot refresh with an access token")

    subject = payload.get("sub")
    if subject is None:
        raise ValueError("Invalid refresh token: missing subject")

    user_id = uuid.UUID(subject)

    # Fetch user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("User not found or disabled")

    # Find and revoke matching refresh token (matched by jti hash)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    stored_tokens = result.scalars().all()
    found = False
    for stored in stored_tokens:
        if _token_matches_hash(refresh_token_str, stored.token_hash):
            stored.revoked = True
            found = True
            break

    if not found:
        # Could be already revoked — revoke all to prevent reuse
        for stored in stored_tokens:
            stored.revoked = True
        raise ValueError("Refresh token has been revoked")

    # Generate new tokens
    access_token, access_expires = create_access_token(str(user.id))
    new_refresh_token, refresh_expires = create_refresh_token(str(user.id))

    # Store new refresh token hash (using jti)
    new_rt_hash = _hash_token(new_refresh_token)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=new_rt_hash,
        expires_at=refresh_expires,
        revoked=False,
    )
    db.add(rt)
    await db.flush()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=int(access_expires.timestamp()),
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            is_active=user.is_active,
        ),
    )


async def revoke_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke all active (non-revoked) refresh tokens for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        The number of tokens revoked.
    """
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    tokens = result.scalars().all()
    count = 0
    for token in tokens:
        token.revoked = True
        count += 1
    if count > 0:
        await db.flush()
    return count


async def change_user_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    """Change a user's password.

    Verifies the current password, validates the new password,
    hashes it, and updates the stored hash.

    Args:
        db: Database session.
        user: The target User instance.
        current_password: The user's current password.
        new_password: The desired new password.

    Raises:
        ValueError: If current password is wrong or new password is weak.
    """
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")

    validation = validate_password(new_password)
    if not validation.valid:
        raise ValueError(validation.message)

    user.password_hash = hash_password(new_password)
    await db.flush()
