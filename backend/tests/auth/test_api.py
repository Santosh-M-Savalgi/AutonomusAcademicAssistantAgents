"""Auth API endpoint tests (Sprint 6).

Covers:
- Registration (success, duplicate, weak password)
- Login (success, invalid credentials, disabled user)
- Token refresh (success, invalid, access token)
- Logout
- Get current user (/me)
- Change password
- Authorization (role enforcement, session ownership)
- Protected routes
- Expired/invalid tokens
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.auth.password import hash_password
from app.core.config import get_settings
from app.db.models import User
from app.db.models.enums import UserRole
from app.main import create_app


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    _app = create_app()
    return _app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def _mock_auth_deps(app, user_id: str = None, role: str = "student", is_active: bool = True):
    """Override auth dependencies in the app for tests that need a real user."""
    from app.auth import dependencies as auth_deps

    _user_id = uuid.UUID(user_id or "00000000-0000-0000-0000-000000000001")
    _email = "test@example.com"
    _username = "testuser"
    _role = role
    _is_active = is_active

    class MockUser:
        id = _user_id
        email = _email
        username = _username
        role = _role
        is_active = _is_active

    mock_user = MockUser()

    async def mock_get_current_user():
        if not _is_active:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
        return mock_user

    async def mock_get_current_student():
        if _role not in ("student", "admin"):
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students")
        return mock_user

    app.dependency_overrides[auth_deps.get_current_user] = mock_get_current_user
    app.dependency_overrides[auth_deps.get_current_student] = mock_get_current_student

    return mock_user


# ── Registration Tests ──────────────────────────────────────────────────────


class TestRegister:
    """POST /auth/register"""

    def test_register_success(self, client, app) -> None:
        """Register a new user successfully."""
        # Patch the register_user service
        with patch("app.api.v2.auth.register_user") as mock_register:
            mock_user = MagicMock(spec=User)
            mock_user.id = uuid.uuid4()
            mock_user.email = "new@example.com"
            mock_register.return_value = mock_user

            response = client.post(
                "/api/v2/auth/register",
                json={
                    "email": "new@example.com",
                    "username": "newuser",
                    "password": "SecurePass1!",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "User registered successfully"

    def test_register_duplicate_email(self, client, app) -> None:
        with patch("app.api.v2.auth.register_user") as mock_register:
            mock_register.side_effect = ValueError("A user with this email already exists")

            response = client.post(
                "/api/v2/auth/register",
                json={
                    "email": "existing@example.com",
                    "username": "existinguser",
                    "password": "SecurePass1!",
                },
            )

        assert response.status_code == 409
        data = response.json()
        assert "already exists" in data["detail"]

    def test_register_weak_password(self, client, app) -> None:
        with patch("app.api.v2.auth.register_user") as mock_register:
            mock_register.side_effect = ValueError("must contain at least one uppercase letter")

            response = client.post(
                "/api/v2/auth/register",
                json={
                    "email": "test@example.com",
                    "username": "testuser",
                    "password": "alllowercase1!",
                },
            )

        assert response.status_code == 400

    def test_register_invalid_email(self, client, app) -> None:
        response = client.post(
            "/api/v2/auth/register",
            json={
                "email": "not-an-email",
                "username": "testuser",
                "password": "SecurePass1!",
            },
        )
        assert response.status_code == 422


# ── Login Tests ─────────────────────────────────────────────────────────────


class TestLogin:
    """POST /auth/login"""

    def test_login_success(self, client, app) -> None:
        with patch("app.api.v2.auth.login_user") as mock_login:
            from app.auth.schemas import TokenResponse, UserResponse

            mock_login.return_value = TokenResponse(
                access_token="access-token-123",
                refresh_token="refresh-token-456",
                token_type="bearer",
                expires_in=9999999999,
                user=UserResponse(
                    id=str(uuid.uuid4()),
                    email="test@example.com",
                    username="testuser",
                    role="student",
                    is_active=True,
                ),
            )

            response = client.post(
                "/api/v2/auth/login",
                json={
                    "email_or_username": "test@example.com",
                    "password": "SecurePass1!",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "access-token-123"
        assert data["refresh_token"] == "refresh-token-456"
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client, app) -> None:
        with patch("app.api.v2.auth.login_user") as mock_login:
            mock_login.side_effect = ValueError("Invalid credentials")

            response = client.post(
                "/api/v2/auth/login",
                json={
                    "email_or_username": "test@example.com",
                    "password": "WrongPass1!",
                },
            )

        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_login_disabled_user(self, client, app) -> None:
        with patch("app.api.v2.auth.login_user") as mock_login:
            mock_login.side_effect = ValueError("Account is disabled")

            response = client.post(
                "/api/v2/auth/login",
                json={
                    "email_or_username": "disabled@example.com",
                    "password": "SecurePass1!",
                },
            )

        assert response.status_code == 401
        assert "disabled" in response.json()["detail"]


# ── Token Refresh Tests ─────────────────────────────────────────────────────


class TestRefresh:
    """POST /auth/refresh"""

    def test_refresh_success(self, client, app) -> None:
        with patch("app.api.v2.auth.refresh_user_token") as mock_refresh:
            from app.auth.schemas import TokenResponse, UserResponse

            mock_refresh.return_value = TokenResponse(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
                token_type="bearer",
                expires_in=9999999999,
                user=UserResponse(
                    id=str(uuid.uuid4()),
                    email="test@example.com",
                    username="testuser",
                    role="student",
                    is_active=True,
                ),
            )

            response = client.post(
                "/api/v2/auth/refresh",
                json={"refresh_token": "old-refresh-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "new-access-token"
        assert data["refresh_token"] == "new-refresh-token"

    def test_refresh_invalid_token(self, client, app) -> None:
        with patch("app.api.v2.auth.refresh_user_token") as mock_refresh:
            mock_refresh.side_effect = ValueError("Invalid refresh token")

            response = client.post(
                "/api/v2/auth/refresh",
                json={"refresh_token": "invalid-token"},
            )

        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]


# ── Logout Tests ────────────────────────────────────────────────────────────


class TestLogout:
    """POST /auth/logout"""

    def test_logout_success(self, client, app) -> None:
        _mock_auth_deps(app)
        with patch("app.api.v2.auth.revoke_refresh_tokens") as mock_revoke:
            mock_revoke.return_value = 2

            response = client.post(
                "/api/v2/auth/logout",
                headers={"Authorization": "Bearer valid-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Logged out successfully"

    def test_logout_unauthenticated(self, client, app) -> None:
        response = client.post("/api/v2/auth/logout")
        assert response.status_code == 401


# ── Get Current User Tests ──────────────────────────────────────────────────


class TestGetMe:
    """GET /auth/me"""

    def test_get_me_success(self, client, app) -> None:
        _mock_auth_deps(app)

        response = client.get(
            "/api/v2/auth/me",
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert data["role"] == "student"
        assert data["is_active"] is True

    def test_get_me_unauthenticated(self, client, app) -> None:
        response = client.get("/api/v2/auth/me")
        assert response.status_code == 401

    def test_get_me_invalid_token(self, client, app) -> None:
        response = client.get(
            "/api/v2/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401


# ── Password Change Tests ───────────────────────────────────────────────────


class TestChangePassword:
    """POST /auth/change-password"""

    def test_change_password_success(self, client, app) -> None:
        _mock_auth_deps(app)

        with patch("app.api.v2.auth.change_user_password") as mock_change:
            response = client.post(
                "/api/v2/auth/change-password",
                json={
                    "current_password": "OldPass1!",
                    "new_password": "NewPass1!",
                },
                headers={"Authorization": "Bearer valid-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Password changed successfully"

    def test_change_password_wrong_current(self, client, app) -> None:
        _mock_auth_deps(app)

        with patch("app.api.v2.auth.change_user_password") as mock_change:
            mock_change.side_effect = ValueError("Current password is incorrect")

            response = client.post(
                "/api/v2/auth/change-password",
                json={
                    "current_password": "WrongOldPass1!",
                    "new_password": "NewPass1!",
                },
                headers={"Authorization": "Bearer valid-token"},
            )

        assert response.status_code == 400


# ── Authorization Tests ────────────────────────────────────────────────────


class TestAuthorization:
    """Role and ownership enforcement."""

    def test_protected_route_requires_auth(self, client, app) -> None:
        """Session endpoints should return 401 without auth."""
        response = client.get("/api/v2/sessions/nonexistent")
        assert response.status_code == 401

    def test_protected_route_with_auth(self, client, app) -> None:
        """Session endpoints should work with valid auth."""
        _mock_auth_deps(app)

        # Session not found is expected here — we're testing auth passes
        response = client.get(
            "/api/v2/sessions/nonexistent",
            headers={"Authorization": "Bearer valid-token"},
        )
        # Should get 404 (not found) not 401 (unauthorized)
        assert response.status_code == 404

    def test_expired_token_returns_401(self, client, app) -> None:
        """An expired token should produce 401."""
        expired_token, _ = create_access_token(
            str(uuid.uuid4()),
            expires_delta=timedelta(hours=-1),  # Already expired
        )

        response = client.get(
            "/api/v2/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, client, app) -> None:
        """A malformed token should produce 401."""
        response = client.get(
            "/api/v2/auth/me",
            headers={"Authorization": "Bearer definitely-invalid"},
        )
        assert response.status_code == 401

    def test_refresh_token_cant_access_protected(self, client, app) -> None:
        """A refresh token should not grant access to protected endpoints."""
        refresh_token, _ = create_refresh_token(str(uuid.uuid4()))

        response = client.get(
            "/api/v2/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert response.status_code == 401

    def test_session_ownership_enforced(self, client, app) -> None:
        """A student should not access another student's session."""
        # Create two mock users with different IDs
        user1_id = "11111111-1111-1111-1111-111111111111"
        user2_id = "22222222-2222-2222-2222-222222222222"

        from app.auth import dependencies as auth_deps

        class MockUser1:
            id = uuid.UUID(user1_id)
            email = "user1@example.com"
            username = "user1"
            role = "student"
            is_active = True

        async def mock_user1():
            return MockUser1()

        # Clear previous overrides and set user1
        app.dependency_overrides[auth_deps.get_current_user] = mock_user1
        app.dependency_overrides[auth_deps.get_current_student] = mock_user1

        # Mock the session manager to return a session owned by user2
        mock_session = MagicMock()
        mock_session.student_id = user2_id  # Different user!
        mock_session.session_id = "test-session-123"
        mock_session.syllabus_id = ""
        mock_session.current_topic = ""
        mock_session.current_topic_id = ""
        mock_session.current_lesson = MagicMock()
        mock_session.current_lesson.to_dict.return_value = {}
        mock_session.current_lesson.generated_at = None
        mock_session.quiz_state = MagicMock()
        mock_session.quiz_state.to_dict.return_value = {}
        mock_session.quiz_state.generated_at = None
        mock_session.workflow_state = MagicMock()
        mock_session.workflow_state.to_dict.return_value = {}
        mock_session.workflow_state.current_node = None
        mock_session.workflow_state.routing_decision = None
        mock_session.mastery_snapshot = {}
        mock_session.retrieval_context = {}
        mock_session.last_activity = ""
        mock_session.created_at = ""
        mock_session.updated_at = ""
        mock_session.status = MagicMock()
        mock_session.status.value = "active"
        mock_session.metadata = {}
        mock_session.to_dict.return_value = {"student_id": user2_id}

        import app.api.v2.session as sess_mod
        original_get_manager = sess_mod._get_manager

        mock_manager = AsyncMock()
        mock_manager.get_session.return_value = mock_session
        sess_mod._get_manager = lambda: mock_manager

        try:
            response = client.get(
                f"/api/v2/sessions/test-session-123",
                headers={"Authorization": "Bearer valid-token"},
            )
            assert response.status_code == 403
        finally:
            sess_mod._get_manager = original_get_manager
