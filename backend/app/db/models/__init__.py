"""AAA v2 SQLAlchemy models — all Section 15 tables.

Import this package to ensure all models are registered on ``Base.metadata``
so Alembic can autogenerate migrations.
"""

from app.db.models.base import Base, IdMixin, TimestampMixin
from app.db.models.enums import (
    BloomLevel,
    DifficultyLevel,
    EdgeCreatedBy,
    EdgeRelationshipType,
    QuizDifficultyLevel,
    LearningMode,
    ResourceType,
    SessionStatus,
    SyllabusStatus,
    UserRole,
)
from app.db.models.knowledge_graph import (
    Syllabus,
    Topic,
    TopicClosure,
    TopicEdge,
)
from app.db.models.quiz import QuizAttempt, QuizAttemptAnswer, QuizQuestion
from app.db.models.resources import Resource, TrustedChannel, YouTubeResource
from app.db.models.session import AnalyticsEvent, ConceptMastery, Preference, Session
from app.db.models.user import RefreshToken, StudentProfile, User

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    # Enums
    "BloomLevel",
    "DifficultyLevel",
    "EdgeCreatedBy",
    "EdgeRelationshipType",
    "QuizDifficultyLevel",
    "LearningMode",
    "ResourceType",
    "SessionStatus",
    "SyllabusStatus",
    "UserRole",
    # Knowledge Graph
    "Syllabus",
    "Topic",
    "TopicClosure",
    "TopicEdge",
    # Quiz
    "QuizAttempt",
    "QuizAttemptAnswer",
    "QuizQuestion",
    # Resources
    "Resource",
    "TrustedChannel",
    "YouTubeResource",
    # Session / Mastery / Preferences / Analytics
    "AnalyticsEvent",
    "ConceptMastery",
    "Preference",
    "Session",
    # User
    "RefreshToken",
    "StudentProfile",
    "User",
]
