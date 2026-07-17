"""AAA v2 Durable Session Persistence (Sprint 5).

This package provides:
- ``SessionModels`` — data classes for session state
- ``CheckpointStore`` — Redis-backed checkpoint persistence
- ``SessionRepository`` — CRUD for session metadata
- ``SessionManager`` — orchestration layer with autosave
"""

from app.session.session_models import (
    LessonState,
    QuizState,
    SessionData,
    SessionStatus,
    WorkflowState,
)
from app.session.checkpoint_store import CheckpointStore, RedisCheckpointBackend
from app.session.session_repository import SessionRepository
from app.session.session_manager import SessionManager

__all__ = [
    "SessionData",
    "SessionStatus",
    "LessonState",
    "QuizState",
    "WorkflowState",
    "CheckpointStore",
    "RedisCheckpointBackend",
    "SessionRepository",
    "SessionManager",
]
