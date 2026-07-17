"""Shared PostgreSQL enum types for AAA v2 (Section 15 schema).

All enums defined once here and referenced by SQLAlchemy models
via ``sqlalchemy.Enum`` with ``create_constraint=True`` so Alembic
generates proper ``CREATE TYPE`` statements.
"""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    student = "student"
    admin = "admin"
    instructor = "instructor"  # reserved for Future Scope (Section 24)


class DifficultyLevel(str, enum.Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class BloomLevel(str, enum.Enum):
    remember = "remember"
    understand = "understand"
    apply = "apply"
    analyze = "analyze"
    evaluate = "evaluate"
    create = "create"


class EdgeRelationshipType(str, enum.Enum):
    direct_prerequisite = "direct_prerequisite"
    related_concept = "related_concept"
    part_of = "part_of"


class EdgeCreatedBy(str, enum.Enum):
    llm_inferred = "llm_inferred"
    human_curated = "human_curated"


class LearningMode(str, enum.Enum):
    sprint = "sprint"
    journey = "journey"
    mastery = "mastery"


class SyllabusStatus(str, enum.Enum):
    parsing = "parsing"
    ready = "ready"
    failed = "failed"


class ResourceType(str, enum.Enum):
    web = "web"
    docs = "docs"
    blog = "blog"
    research = "research"


class SessionStatus(str, enum.Enum):
    active = "active"
    idle = "idle"
    completed = "completed"


class QuizDifficultyLevel(str, enum.Enum):
    """Quiz-specific difficulty scale (Section 13.3: easy/medium/hard)."""
    easy = "easy"
    medium = "medium"
    hard = "hard"
