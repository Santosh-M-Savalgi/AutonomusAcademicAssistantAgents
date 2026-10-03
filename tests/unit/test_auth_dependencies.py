"""FastAPI Bearer authentication dependency tests without user-table side effects."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from apps.api.auth.dependencies import get_current_identity
from apps.api.auth.jwt import JWTService
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.config import Settings, get_settings

_TEST_SIGNING_KEY = "dependency-test-only-key-with-at-least-32-characters"


def test_dependency_returns_valid_identity() -> None:
    settings = Settings(_env_file=None, jwt_secret_key=_TEST_SIGNING_KEY)
    service = JWTService(settings)
    token = service.create_access_token("student-123")
    application = FastAPI()
    application.state.settings = settings

    @application.get("/protected")
    def protected(
        identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    ) -> dict[str, str]:
        return {"subject": identity.subject, "token_id": identity.token_id}

    with TestClient(application) as client:
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["subject"] == "student-123"
    assert response.json()["token_id"] == service.validate_access_token(token).token_id


def test_dependency_rejects_missing_invalid_and_refresh_tokens(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", _TEST_SIGNING_KEY)
    get_settings.cache_clear()
    service = JWTService()
    refresh_token = service.create_refresh_token("student-123")
    application = FastAPI()

    @application.get("/protected")
    def protected(
        identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    ) -> str:
        return identity.subject

    with TestClient(application) as client:
        for headers in (
            {},
            {"Authorization": "Bearer not-a-jwt"},
            {"Authorization": f"Bearer {refresh_token}"},
            {"Authorization": "Basic dXNlcjpwYXNz"},
        ):
            response = client.get("/protected", headers=headers)
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.text.find(_TEST_SIGNING_KEY) == -1
