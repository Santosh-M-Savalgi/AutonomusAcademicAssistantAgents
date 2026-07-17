"""Auth service tests (Sprint 6).

Covers:
- User registration
- User authentication (login)
- Token refresh with rotation
- Password change
- Token revocation
- Edge cases: duplicate email, duplicate username, disabled user, invalid credentials
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.auth.password import hash_password
from app.auth.schemas import LoginRequest, RegisterRequest
from app.auth.service import (
    authenticate_user,
    change_user_password,
    login_user,
    refresh_user_token,
    register_user,
    revoke_refresh_tokens,
)
from app.db.models import RefreshToken, User
from app.db.models.enums import UserRole


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create a mock async database session."""
    db = AsyncMock(spec=AsyncSession)

    # Mock execute() to return a result with scalar_one_or_none
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock

    return db


@pytest.fixture
def sample_register_request() -> RegisterRequest:
    return RegisterRequest(
        email="test@example.com",
        username="testuser",
        password="SecurePass1!",
    )


@pytest.fixture
def sample_login_request() -> LoginRequest:
    return LoginRequest(
        email_or_username="test@example.com",
        password="SecurePass1!",
    )


def _make_user(
    user_id: str = "11111111-1111-1111-1111-111111111111",
    email: str = "test@example.com",
    username: str = "testuser",
    role: str = "student",
    is_active: bool = True,
) -> User:
    """Helper to create a User-like mock object."""
    user = MagicMock(spec=User)
    user.id = uuid.UUID(user_id)
    user.email = email
    user.username = username
    user.role = role
    user.is_active = is_active
    user.password_hash = hash_password("SecurePass1!")
    user.last_login = None
    return user


class TestRegisterUser:
    """User registration."""

    @pytest.mark.asyncio
    async def test_register_success(self, mock_db: AsyncMock, sample_register_request: RegisterRequest) -> None:
        user = await register_user(mock_db, sample_register_request)
        assert user.email == sample_register_request.email
        assert user.username == sample_register_request.username
        assert user.is_active is True
        assert user.role == UserRole.student
        # Password should be hashed, not stored in plain text
        assert user.password_hash != sample_register_request.password
        assert user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, mock_db: AsyncMock, sample_register_request: RegisterRequest) -> None:
        # Simulate existing email
        existing_user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = result_mock

        with pytest.raises(ValueError, match="already exists"):
            await register_user(mock_db, sample_register_request)

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, mock_db: AsyncMock) -> None:
        # First call (email check) returns None, second call (username check) returns existing user
        existing_user = _make_user()

        def execute_side_effect(*args, **kwargs):
            result = MagicMock()
            # Second call (username check) returns existing
            if "username" in str(args[0]):
                result.scalar_one_or_none.return_value = existing_user
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute.side_effect = execute_side_effect

        request = RegisterRequest(
            email="other@example.com",
            username="testuser",
            password="SecurePass1!",
        )
        with pytest.raises(ValueError, match="already exists"):
            await register_user(mock_db, request)

    @pytest.mark.asyncio
    async def test_register_weak_password(self, mock_db: AsyncMock) -> None:
        request = RegisterRequest(
            email="test@example.com",
            username="testuser",
            password="alllowercase1!",
        )
        with pytest.raises(ValueError, match="uppercase"):
            await register_user(mock_db, request)


class TestAuthenticateUser:
    """User authentication (login)."""

    @pytest.mark.asyncio
    async def test_authenticate_by_email(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="test@example.com", password="SecurePass1!")
        authenticated = await authenticate_user(mock_db, request)
        assert authenticated is user

    @pytest.mark.asyncio
    async def test_authenticate_by_username(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="testuser", password="SecurePass1!")
        authenticated = await authenticate_user(mock_db, request)
        assert authenticated is user

    @pytest.mark.asyncio
    async def test_authenticate_invalid_credentials(self, mock_db: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="unknown@example.com", password="WrongPass1!")
        with pytest.raises(ValueError, match="Invalid credentials"):
            await authenticate_user(mock_db, request)

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="test@example.com", password="WrongPass1!")
        with pytest.raises(ValueError, match="Invalid credentials"):
            await authenticate_user(mock_db, request)

    @pytest.mark.asyncio
    async def test_authenticate_disabled_user(self, mock_db: AsyncMock) -> None:
        user = _make_user(is_active=False)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="test@example.com", password="SecurePass1!")
        with pytest.raises(ValueError, match="disabled"):
            await authenticate_user(mock_db, request)


class TestLoginUser:
    """Login flow (authenticate + generate tokens)."""

    @pytest.mark.asyncio
    async def test_login_success(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = result_mock

        request = LoginRequest(email_or_username="test@example.com", password="SecurePass1!")
        response = await login_user(mock_db, request)

        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.token_type == "bearer"
        assert response.user.email == "test@example.com"
        assert response.user.username == "testuser"

        # Verify refresh token was stored
        mock_db.add.assert_called_once()
        added_rt = mock_db.add.call_args[0][0]
        assert isinstance(added_rt, RefreshToken)
        assert str(added_rt.user_id) == "11111111-1111-1111-1111-111111111111"
        assert added_rt.revoked is False


class TestRefreshToken:
    """Token refresh with rotation."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, mock_db: AsyncMock) -> None:
        user = _make_user()

        # Mock user lookup
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = user_result

        # Create a valid refresh token
        refresh_token_str, _ = create_refresh_token(str(user.id))

        # Mock token lookup to find the stored (matching) token.
        # The service now uses _hash_token which hashes the JWT's jti.
        from app.auth.service import _hash_token

        stored_token = MagicMock(spec=RefreshToken)
        stored_token.user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        stored_token.revoked = False
        stored_token.token_hash = _hash_token(refresh_token_str)

        def execute_side_effect(*args, **kwargs):
            result = MagicMock()
            if "refresh_tokens" in str(args[0]) or "RefreshToken" in str(args[0]):
                result.scalars.return_value.all.return_value = [stored_token]
            else:
                result.scalar_one_or_none.return_value = user
            return result

        mock_db.execute.side_effect = execute_side_effect

        response = await refresh_user_token(mock_db, refresh_token_str)

        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.refresh_token != refresh_token_str  # Rotation
        assert stored_token.revoked is True  # Old token revoked

    @pytest.mark.asyncio
    async def test_refresh_with_access_token(self, mock_db: AsyncMock) -> None:
        access_token, _ = create_access_token("user-123")
        with pytest.raises(ValueError, match="Cannot refresh with an access token"):
            await refresh_user_token(mock_db, access_token)

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, mock_db: AsyncMock) -> None:
        with pytest.raises(ValueError, match="Invalid refresh token"):
            await refresh_user_token(mock_db, "invalid-token")


class TestRevokeRefreshTokens:
    """Token revocation."""

    @pytest.mark.asyncio
    async def test_revoke_all_tokens(self, mock_db: AsyncMock) -> None:
        token1 = MagicMock(spec=RefreshToken, revoked=False)
        token2 = MagicMock(spec=RefreshToken, revoked=False)
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [token1, token2]
        mock_db.execute.return_value = result_mock

        user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        count = await revoke_refresh_tokens(mock_db, user_id)
        assert count == 2
        assert token1.revoked is True
        assert token2.revoked is True
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_no_tokens(self, mock_db: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = result_mock

        user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        count = await revoke_refresh_tokens(mock_db, user_id)
        assert count == 0
        mock_db.flush.assert_not_called()


class TestChangePassword:
    """Password change."""

    @pytest.mark.asyncio
    async def test_change_password_success(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        old_hash = user.password_hash

        await change_user_password(mock_db, user, "SecurePass1!", "NewSecurePass1!")

        assert user.password_hash != old_hash
        assert user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$")
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        with pytest.raises(ValueError, match="Current password is incorrect"):
            await change_user_password(mock_db, user, "WrongPass1!", "NewSecurePass1!")

    @pytest.mark.asyncio
    async def test_change_password_weak_new(self, mock_db: AsyncMock) -> None:
        user = _make_user()
        with pytest.raises(ValueError, match="at least 8"):
            await change_user_password(mock_db, user, "SecurePass1!", "weak")
