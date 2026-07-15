"""Sprint 0 foundation tests for the AAA v2 app package."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_healthz_returns_backend_identity() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/healthz", headers={"x-session-id": "session-123"})

    assert response.status_code == 200
    assert response.headers["x-session-id"] == "session-123"
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "backend"


def test_readyz_reports_dependency_checks(monkeypatch) -> None:
    async def ok_check() -> tuple[bool, str]:
        return True, "ok"

    from app.api import health

    monkeypatch.setattr(health, "check_postgres", ok_check)
    monkeypatch.setattr(health, "check_redis", ok_check)
    monkeypatch.setattr(health, "check_chroma", ok_check)
    monkeypatch.setattr(health, "check_object_storage", ok_check)

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/readyz")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert set(payload["checks"]) == {"postgres", "redis", "chroma", "object_storage"}


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(cors_origins_raw="http://localhost:5173, https://example.test, ")

    assert settings.cors_origins == ["http://localhost:5173", "https://example.test"]
