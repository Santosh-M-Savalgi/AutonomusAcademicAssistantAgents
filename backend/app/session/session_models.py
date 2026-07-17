"""Session data models for durable persistence (Sprint 5).

Defines the data classes that represent a student's learning session,
including lesson state, quiz state, workflow state, and full session
serialization. These are JSON-serializable for Redis storage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Lifecycle status of a learning session."""

    ACTIVE = "active"
    """Session is running and accepting operations."""

    IDLE = "idle"
    """Session is inactive but recoverable (timeout threshold crossed)."""

    COMPLETED = "completed"
    """Session has finished (curriculum complete or student ended it)."""

    EXPIRED = "expired"
    """Session exceeded max idle TTL and has been marked for cleanup."""


@dataclass
class LessonState:
    """Serializable state of the current lesson.

    Persisted so a student can resume a partially viewed lesson
    without the tutor generating it again.
    """

    topic_id: str = ""
    topic_name: str = ""
    lesson_title: str = ""
    lesson_data: dict[str, Any] = field(default_factory=dict)
    """The full lesson response dict (cards, estimated_minutes, etc.)."""

    current_card_index: int = 0
    """Which card the student last viewed (0-indexed)."""

    lesson_complete: bool = False
    """True when the student has finished reviewing the lesson."""

    generated_at: str | None = None
    """ISO-8601 timestamp of when the lesson was generated."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "lesson_title": self.lesson_title,
            "lesson_data": self.lesson_data,
            "current_card_index": self.current_card_index,
            "lesson_complete": self.lesson_complete,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LessonState:
        return cls(
            topic_id=data.get("topic_id", ""),
            topic_name=data.get("topic_name", ""),
            lesson_title=data.get("lesson_title", ""),
            lesson_data=data.get("lesson_data", {}),
            current_card_index=data.get("current_card_index", 0),
            lesson_complete=data.get("lesson_complete", False),
            generated_at=data.get("generated_at"),
        )


@dataclass
class QuizState:
    """Serializable state of the current quiz.

    Persisted so a student can resume an unfinished quiz
    (e.g., after browser refresh).
    """

    topic_id: str = ""
    topic_name: str = ""
    quiz_data: dict[str, Any] = field(default_factory=dict)
    """The full quiz response dict (questions list, etc.)."""

    answers: list[dict[str, Any]] = field(default_factory=list)
    """Student answers submitted so far during this quiz attempt."""

    current_question_index: int = 0
    """Which question the student is on (0-indexed)."""

    quiz_complete: bool = False
    """True when all questions have been answered."""

    score: float = 0.0
    """Computed score (0.0–1.0) after evaluation, or 0.0 if not yet evaluated."""

    evaluation_data: dict[str, Any] = field(default_factory=dict)
    """Evaluation result dict if evaluation has been performed."""

    generated_at: str | None = None
    """ISO-8601 timestamp of when the quiz was generated."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "quiz_data": self.quiz_data,
            "answers": self.answers,
            "current_question_index": self.current_question_index,
            "quiz_complete": self.quiz_complete,
            "score": self.score,
            "evaluation_data": self.evaluation_data,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuizState:
        return cls(
            topic_id=data.get("topic_id", ""),
            topic_name=data.get("topic_name", ""),
            quiz_data=data.get("quiz_data", {}),
            answers=data.get("answers", []),
            current_question_index=data.get("current_question_index", 0),
            quiz_complete=data.get("quiz_complete", False),
            score=data.get("score", 0.0),
            evaluation_data=data.get("evaluation_data", {}),
            generated_at=data.get("generated_at"),
        )


@dataclass
class WorkflowState:
    """Serializable state of the LangGraph workflow.

    Preserves the graph node, routing state, and progress so the
    orchestrator can resume at the exact step where it left off.
    """

    current_node: str = ""
    """The name of the current graph node (e.g. 'teach', 'quiz', 'evaluate')."""

    completed_nodes: list[str] = field(default_factory=list)
    """Nodes that have been executed and completed."""

    routing_decision: str = ""
    """The last routing decision (NEXT_TOPIC, REVIEW_TOPIC, etc.)."""

    routing_reason: str = ""
    """Explanation for the last routing decision."""

    next_topic_id: str | None = None
    """The topic the router decided to move to next, if any."""

    errors: list[dict[str, Any]] = field(default_factory=list)
    """Errors encountered during workflow execution."""

    retry_count: int = 0
    """Number of retries on the current node."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_node": self.current_node,
            "completed_nodes": self.completed_nodes,
            "routing_decision": self.routing_decision,
            "routing_reason": self.routing_reason,
            "next_topic_id": self.next_topic_id,
            "errors": self.errors,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        return cls(
            current_node=data.get("current_node", ""),
            completed_nodes=data.get("completed_nodes", []),
            routing_decision=data.get("routing_decision", ""),
            routing_reason=data.get("routing_reason", ""),
            next_topic_id=data.get("next_topic_id"),
            errors=data.get("errors", []),
            retry_count=data.get("retry_count", 0),
        )


@dataclass
class SessionData:
    """Complete serializable snapshot of a student's learning session.

    This is the source of truth for an active learning journey.
    Every field is JSON-serializable for Redis storage.

    Session lifecycle:
    1. Created when a student starts a new learning journey
    2. Updated after every workflow phase (lesson → quiz → evaluation)
    3. Auto-saved at key transition points
    4. Can be resumed after browser refresh or backend restart
    5. Expired after prolonged inactivity
    """

    session_id: str = ""
    """Unique session identifier (UUID string)."""

    student_id: str = ""
    """Identifier of the student owning this session."""

    syllabus_id: str = ""
    """The syllabus / curriculum being studied."""

    current_topic: str = ""
    """Current topic name."""

    current_topic_id: str = ""
    """Current topic UUID string."""

    current_lesson: LessonState = field(default_factory=LessonState)
    """Current lesson state."""

    lesson_state: dict[str, Any] = field(default_factory=dict)
    """Additional lesson metadata."""

    quiz_state: QuizState = field(default_factory=QuizState)
    """Current quiz state."""

    workflow_state: WorkflowState = field(default_factory=WorkflowState)
    """Workflow / graph execution state."""

    mastery_snapshot: dict[str, Any] = field(default_factory=dict)
    """Snapshot of current mastery scores per topic (topic_id -> score)."""

    graph_state: dict[str, Any] = field(default_factory=dict)
    """Full graph state for LangGraph resumption."""

    retrieval_context: dict[str, Any] = field(default_factory=dict)
    """Context from the last retrieval operation (chunks, summaries)."""

    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    """History of interactions (lesson presented, quiz answers, etc.)."""

    last_activity: str = ""
    """ISO-8601 timestamp of the last recorded activity."""

    created_at: str = ""
    """ISO-8601 timestamp of when the session was created."""

    updated_at: str = ""
    """ISO-8601 timestamp of the last update."""

    status: SessionStatus = SessionStatus.ACTIVE
    """Current session lifecycle status."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Extensible metadata for custom session attributes."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the session to a JSON-safe dict for Redis storage."""
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "syllabus_id": self.syllabus_id,
            "current_topic": self.current_topic,
            "current_topic_id": self.current_topic_id,
            "current_lesson": self.current_lesson.to_dict(),
            "lesson_state": self.lesson_state,
            "quiz_state": self.quiz_state.to_dict(),
            "workflow_state": self.workflow_state.to_dict(),
            "mastery_snapshot": self.mastery_snapshot,
            "graph_state": self.graph_state,
            "retrieval_context": self.retrieval_context,
            "conversation_history": self.conversation_history,
            "last_activity": self.last_activity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionData:
        """Deserialize a session from a JSON-safe dict."""
        status_raw = data.get("status", "active")
        if isinstance(status_raw, SessionStatus):
            status = status_raw
        else:
            try:
                status = SessionStatus(status_raw)
            except ValueError:
                status = SessionStatus.ACTIVE

        return cls(
            session_id=data.get("session_id", ""),
            student_id=data.get("student_id", ""),
            syllabus_id=data.get("syllabus_id", ""),
            current_topic=data.get("current_topic", ""),
            current_topic_id=data.get("current_topic_id", ""),
            current_lesson=LessonState.from_dict(data.get("current_lesson", {})),
            lesson_state=data.get("lesson_state", {}),
            quiz_state=QuizState.from_dict(data.get("quiz_state", {})),
            workflow_state=WorkflowState.from_dict(data.get("workflow_state", {})),
            mastery_snapshot=data.get("mastery_snapshot", {}),
            graph_state=data.get("graph_state", {}),
            retrieval_context=data.get("retrieval_context", {}),
            conversation_history=data.get("conversation_history", []),
            last_activity=data.get("last_activity", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            status=status,
            metadata=data.get("metadata", {}),
        )

    def touch(self) -> None:
        """Update the last_activity and updated_at timestamps to now."""
        now = datetime.now(timezone.utc).isoformat()
        self.last_activity = now
        self.updated_at = now

    def is_active(self) -> bool:
        """Return True if the session is in an active/resumable state."""
        return self.status in (SessionStatus.ACTIVE, SessionStatus.IDLE)

    def is_expired(self) -> bool:
        """Return True if the session has been marked as expired."""
        return self.status == SessionStatus.EXPIRED

    @staticmethod
    def new_session_id() -> str:
        """Generate a new unique session ID."""
        return str(uuid.uuid4())

    @staticmethod
    def now_iso() -> str:
        """Return the current time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()
