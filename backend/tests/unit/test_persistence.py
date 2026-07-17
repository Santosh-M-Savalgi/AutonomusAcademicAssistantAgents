"""Unit tests for Sprint 1 persistence models, enums, and repository."""

from __future__ import annotations

import uuid

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_all_enums_import() -> None:
    from app.db.models.enums import (
        BloomLevel,
        DifficultyLevel,
        EdgeCreatedBy,
        EdgeRelationshipType,
        LearningMode,
        QuizDifficultyLevel,
        ResourceType,
        SessionStatus,
        SyllabusStatus,
        UserRole,
    )

    assert UserRole.student.value == "student"
    assert UserRole.admin.value == "admin"
    assert UserRole.instructor.value == "instructor"


def test_difficulty_levels_separate() -> None:
    """Topic/Resource difficulty vs Quiz difficulty are distinct scales."""
    from app.db.models.enums import DifficultyLevel, QuizDifficultyLevel

    assert DifficultyLevel.beginner.value == "beginner"
    assert DifficultyLevel.intermediate.value == "intermediate"
    assert DifficultyLevel.advanced.value == "advanced"

    assert QuizDifficultyLevel.easy.value == "easy"
    assert QuizDifficultyLevel.medium.value == "medium"
    assert QuizDifficultyLevel.hard.value == "hard"

    # They must NOT overlap (architecture Sections 7.2 vs 13.3)
    assert set(DifficultyLevel) != set(QuizDifficultyLevel)


def test_learning_modes() -> None:
    from app.db.models.enums import LearningMode

    assert LearningMode.sprint.value == "sprint"
    assert LearningMode.journey.value == "journey"
    assert LearningMode.mastery.value == "mastery"


# ---------------------------------------------------------------------------
# Model instantiation tests
# ---------------------------------------------------------------------------


def _col(c: object) -> object:
    """Extract the underlying Column from a Mapped attribute."""
    try:
        return c.property.columns[0]  # type: ignore[union-attr]
    except Exception:
        return c


def _server_default(table: object, col_name: str) -> str | None:
    col = _col(getattr(table, col_name))
    sd = col.server_default
    if sd is not None and hasattr(sd, "arg"):
        return str(sd.arg)
    return None


def _column_default(table: object, col_name: str) -> object:
    col = _col(getattr(table, col_name))
    d = col.default
    if d is not None and hasattr(d, "arg"):
        return d.arg
    return None


def test_user_column_defaults() -> None:
    from app.db.models.user import User

    assert _column_default(User, "role") == "student"
    assert _column_default(User, "email_verified") is False


def test_student_profile_column_defaults() -> None:
    from app.db.models.user import StudentProfile

    assert _column_default(StudentProfile, "prefers_analogies") == 0.5
    assert _column_default(StudentProfile, "prefers_code_examples") == 0.5
    assert _column_default(StudentProfile, "prefers_shorter_lessons") == 0.5
    assert _column_default(StudentProfile, "study_streak_days") == 0
    assert _column_default(StudentProfile, "total_study_time_seconds") == 0
    assert _column_default(StudentProfile, "default_learning_mode") == "journey"


def test_refresh_token_column_defaults() -> None:
    from app.db.models.user import RefreshToken

    assert _column_default(RefreshToken, "revoked") is False


def test_topic_column_defaults() -> None:
    from app.db.models.knowledge_graph import Topic

    assert _column_default(Topic, "difficulty") == "beginner"
    assert _column_default(Topic, "learning_depth") == 15
    assert _column_default(Topic, "bloom_target_level") == "understand"
    assert _column_default(Topic, "mastery_threshold") == 0.75


def test_topic_edge_column_defaults() -> None:
    from app.db.models.knowledge_graph import TopicEdge

    assert _column_default(TopicEdge, "relationship_type") == "direct_prerequisite"
    assert _column_default(TopicEdge, "weight") == 1.0
    assert _column_default(TopicEdge, "created_by") == "llm_inferred"


def test_quiz_question_column_defaults() -> None:
    from app.db.models.quiz import QuizQuestion

    assert _column_default(QuizQuestion, "difficulty") == "medium"
    assert _column_default(QuizQuestion, "bloom_level") == "understand"
    assert _column_default(QuizQuestion, "estimated_time_seconds") == 60
    assert _column_default(QuizQuestion, "confidence_score") == 1.0


def test_concept_mastery_column_defaults() -> None:
    from app.db.models.session import ConceptMastery

    assert _column_default(ConceptMastery, "score") == 0.0
    assert _column_default(ConceptMastery, "confidence") == 0.0
    assert _column_default(ConceptMastery, "attempts_count") == 0


def test_session_column_defaults() -> None:
    from app.db.models.session import Session

    assert _column_default(Session, "status") == "active"


# ---------------------------------------------------------------------------
# All 17 tables registered on Base.metadata
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "users",
    "student_profiles",
    "refresh_tokens",
    "syllabi",
    "topics",
    "topic_edges",
    "topic_closure",
    "trusted_channels",
    "resources",
    "youtube_resources",
    "quiz_questions",
    "quiz_attempts",
    "quiz_attempt_answers",
    "concept_mastery",
    "sessions",
    "preferences",
    "analytics_events",
}


def test_all_tables_registered() -> None:
    from app.db.models import Base

    registered = set(Base.metadata.tables.keys())
    assert registered == EXPECTED_TABLES, (
        f"Missing: {EXPECTED_TABLES - registered}, "
        f"Extra: {registered - EXPECTED_TABLES}"
    )


# ---------------------------------------------------------------------------
# Migration validity
# ---------------------------------------------------------------------------


def test_migration_imports_and_has_revision() -> None:
    from importlib import import_module

    mod = import_module(
        "app.db.migrations.versions.5e0d4ce4b303_initial_schema_section_15"
    )
    assert mod.revision == "5e0d4ce4b303"
    assert mod.down_revision is None
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


# ---------------------------------------------------------------------------
# Repository function signatures (compile-time check)
# ---------------------------------------------------------------------------


def test_repository_functions_importable() -> None:
    from app.db.repository import (
        get_mastery,
        get_questions_by_topic,
        get_session_by_id,
        get_topic_by_id,
        get_topic_by_slug,
        get_topic_context,
        get_transitive_prerequisites,
        record_event,
        upsert_mastery,
        upsert_session_checkpoint,
    )

    # All functions should be callable
    assert callable(get_mastery)
    assert callable(get_questions_by_topic)
    assert callable(get_session_by_id)
    assert callable(get_topic_by_id)
    assert callable(get_topic_by_slug)
    assert callable(get_topic_context)
    assert callable(get_transitive_prerequisites)
    assert callable(record_event)
    assert callable(upsert_mastery)
    assert callable(upsert_session_checkpoint)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_postgres_dsn_default() -> None:
    from app.core.config import Settings

    s = Settings()
    assert "postgresql+asyncpg" in s.postgres_dsn
    assert "postgres" in s.postgres_dsn


def test_session_factory_creates_without_db() -> None:
    """get_session_factory() returns a factory without connecting."""
    from app.db.postgres import get_session_factory

    factory = get_session_factory()
    assert factory is not None


def test_checkpointer_instantiable() -> None:
    from app.graph.checkpointer import AAACheckpointSaver

    saver = AAACheckpointSaver()
    assert saver is not None
