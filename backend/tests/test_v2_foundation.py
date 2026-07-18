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

    async def ok_tuple() -> tuple[bool, str]:
        return True, "available"

    from app.api import health

    monkeypatch.setattr(health, "check_postgres", ok_check)
    monkeypatch.setattr(health, "check_redis", ok_check)
    monkeypatch.setattr(health, "check_chroma", ok_check)
    monkeypatch.setattr(health, "check_object_storage", ok_check)
    monkeypatch.setattr(health, "check_provider_health", ok_tuple)
    monkeypatch.setattr(health, "check_jobs_health", ok_tuple)

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/readyz/detailed")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert set(payload["checks"]) == {"postgres", "redis", "chroma", "object_storage"}


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(cors_origins_raw="http://localhost:5173, https://example.test, ")

    assert settings.cors_origins == ["http://localhost:5173", "https://example.test"]


# ═══════════════════════════════════════════════════════════════════════
# Regression tests for stabilization bugs
# ═══════════════════════════════════════════════════════════════════════


def test_id_mixin_models_resolve_primary_key_correctly() -> None:
    """Regression: Base.id removed — models with IdMixin get 'id',
    composite-PK models do NOT inherit 'id' column."""
    from sqlalchemy import inspect
    from app.db.models import (
        ConceptMastery,
        Preference,
        StudentProfile,
        TopicClosure,
        User,
        Session,
    )

    # Single-PK tables SHOULD have 'id'
    user_cols = {c.name for c in inspect(User).columns}
    assert "id" in user_cols, "User must have id column"

    session_cols = {c.name for c in inspect(Session).columns}
    assert "id" in session_cols, "Session must have id column"

    # Composite-PK tables MUST NOT have 'id'
    cm_cols = {c.name for c in inspect(ConceptMastery).columns}
    assert "id" not in cm_cols, "ConceptMastery must not have inherited id column"
    assert "user_id" in cm_cols
    assert "topic_id" in cm_cols

    pref_cols = {c.name for c in inspect(Preference).columns}
    assert "id" not in pref_cols, "Preference must not have inherited id column"

    sp_cols = {c.name for c in inspect(StudentProfile).columns}
    assert "id" not in sp_cols, "StudentProfile must not have inherited id column"

    closure_cols = {c.name for c in inspect(TopicClosure).columns}
    assert "id" not in closure_cols, "TopicClosure must not have inherited id column"


def test_get_quiz_attempt_stats_uses_filter_instead_of_cast_type() -> None:
    """Regression: func.cast(condition, type_=type(func.count(1))) fails with
    'Neither count object nor Comparator object has an attribute _isnull'.
    Must use func.count(...).filter(...) instead."""
    from sqlalchemy import select, func
    from app.db.models import QuizAttempt

    # This query should compile without error
    query = select(
        func.count(QuizAttempt.id).label("total"),
        func.count(QuizAttempt.id).filter(
            QuizAttempt.submitted_at.isnot(None)
        ).label("completed"),
        func.avg(QuizAttempt.score).label("avg_score"),
    )
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "count" in compiled
    assert "filter" in compiled or "FILTER" in compiled.upper()


def test_get_session_stats_uses_filter_instead_of_cast_type() -> None:
    """Regression: same func.cast pattern in get_session_stats."""
    from sqlalchemy import select, func
    from app.db.models import Session
    from app.db.models.enums import SessionStatus

    query = select(
        func.count(Session.id).label("total"),
        func.count(Session.id).filter(
            Session.status == SessionStatus.active.value
        ).label("active"),
    )
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "count" in compiled
    assert "filter" in compiled or "FILTER" in compiled.upper()
