"""Session manager — orchestration layer for durable session persistence (Sprint 5).

``SessionManager`` provides the high-level API for creating, updating,
auto-saving, and resuming learning sessions. It coordinates between:

- ``CheckpointStore`` (Redis hot storage)
- ``SessionRepository`` (Postgres durable storage)
- ``SessionData`` / ``LessonState`` / ``QuizState`` / ``WorkflowState`` (domain models)

Auto-save triggers:
- After lesson generation
- After quiz generation
- After evaluation
- After topic completion
- After mastery update

Timeout handling:
- Sessions become IDLE after configurable inactivity
- Idle sessions remain recoverable for up to 7 days
- Expired sessions are cleaned up

Usage::

    manager = SessionManager()
    session = await manager.create_session(
        student_id="user-123",
        syllabus_id="syllabus-456",
    )
    await manager.update_after_lesson(session_id, lesson, ...)
    restored = await manager.resume_session(session_id)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.session.checkpoint_store import CheckpointStore
from app.session.session_models import (
    LessonState,
    QuizState,
    SessionData,
    SessionStatus,
    WorkflowState,
)

logger = logging.getLogger(__name__)

# Default timeouts (in seconds)
_DEFAULT_SESSION_TIMEOUT = 3_600  # 1 hour of inactivity before IDLE
_DEFAULT_MAX_IDLE_TTL = 604_800  # 7 days before session is expired

# Workflow node names for autosave triggers
_NODE_LESSON = "teach"
_NODE_QUIZ = "quiz"
_NODE_EVALUATE = "evaluate"
_NODE_ROUTING = "routing"


class SessionManager:
    """High-level session lifecycle manager.

    Provides a simplified API for session operations that coordinates
    Redis and Postgres persistence layers.

    Usage::

        manager = SessionManager()
        session = await manager.create_session(
            student_id="user-123",
            syllabus_id="syll-456",
        )
        await manager.save_checkpoint(session)

        # After a lesson is generated:
        await manager.update_after_lesson(
            session.session_id,
            topic_id="topic-1",
            topic_name="Python Lists",
            lesson_data={...},
        )
    """

    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
        session_timeout: int = _DEFAULT_SESSION_TIMEOUT,
        max_idle_ttl: int = _DEFAULT_MAX_IDLE_TTL,
    ) -> None:
        self._checkpoint_store = checkpoint_store or CheckpointStore()
        self.session_timeout = session_timeout
        self.max_idle_ttl = max_idle_ttl

    @property
    def checkpoint_store(self) -> CheckpointStore:
        """Expose the underlying checkpoint store."""
        return self._checkpoint_store

    # ── Session lifecycle ─────────────────────────────────────────────────

    async def create_session(
        self,
        student_id: str,
        syllabus_id: str = "",
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionData:
        """Create a new learning session.

        Args:
            student_id: Identifier of the student.
            syllabus_id: Optional syllabus / curriculum ID.
            session_id: Optional explicit session ID (auto-generated if None).
            metadata: Optional custom metadata for the session.

        Returns:
            A new ``SessionData`` instance with status ACTIVE.
        """
        now = SessionData.now_iso()
        session = SessionData(
            session_id=session_id or SessionData.new_session_id(),
            student_id=student_id,
            syllabus_id=syllabus_id,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_activity=now,
            metadata=metadata or {},
        )
        # Persist immediately
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Created session %s for student %s", session.session_id, student_id)
        return session

    async def get_session(self, session_id: str) -> SessionData | None:
        """Load a session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            The ``SessionData`` instance, or None if not found.
        """
        return await self._checkpoint_store.load_checkpoint(session_id)

    async def resume_session(self, session_id: str) -> SessionData | None:
        """Resume a session, refreshing its TTL.

        Recovers:
        - Lesson state (unfinished lesson)
        - Quiz state (unfinished quiz)
        - Workflow state (graph node position)
        - Routing state (last routing decision)
        - Knowledge graph state
        - Retrieval context

        Args:
            session_id: The session identifier.

        Returns:
            The resumed ``SessionData`` instance, or None if not found.
        """
        session = await self._checkpoint_store.resume_checkpoint(session_id)
        if session is None:
            logger.warning("Cannot resume session %s: not found", session_id)
            return None

        # Mark as active if idle
        if session.status == SessionStatus.IDLE:
            session.status = SessionStatus.ACTIVE
            await self._checkpoint_store.save_checkpoint(session)

        logger.info(
            "Resumed session %s for student %s (status=%s)",
            session_id,
            session.student_id,
            session.status.value,
        )
        return session

    async def complete_session(self, session_id: str) -> bool:
        """Mark a session as completed.

        Args:
            session_id: The session identifier.

        Returns:
            True if the session was completed.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return False
        session.status = SessionStatus.COMPLETED
        session.touch()
        return await self._checkpoint_store.save_checkpoint(session)

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its checkpoint.

        Args:
            session_id: The session identifier.

        Returns:
            True if the session was deleted.
        """
        return await self._checkpoint_store.delete_checkpoint(session_id)

    # ── Autosave triggers ─────────────────────────────────────────────────

    async def update_after_lesson(
        self,
        session_id: str,
        topic_id: str,
        topic_name: str,
        lesson_data: dict[str, Any],
        *,
        lesson_title: str = "",
        lesson_state: dict[str, Any] | None = None,
    ) -> SessionData | None:
        """Auto-save after lesson generation.

        Updates the session with the generated lesson data and
        advances the workflow state to the 'teach' node.

        Args:
            session_id: The session identifier.
            topic_id: The topic UUID string.
            topic_name: The topic name.
            lesson_data: The full lesson response dict.
            lesson_title: Optional lesson title.
            lesson_state: Optional additional lesson metadata.

        Returns:
            The updated ``SessionData``, or None if session not found.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.current_topic_id = topic_id
        session.current_topic = topic_name

        now = SessionData.now_iso()
        session.current_lesson = LessonState(
            topic_id=topic_id,
            topic_name=topic_name,
            lesson_title=lesson_title,
            lesson_data=lesson_data,
            generated_at=now,
        )
        if lesson_state:
            session.lesson_state = lesson_state

        session.workflow_state.current_node = _NODE_LESSON
        if _NODE_LESSON not in session.workflow_state.completed_nodes:
            session.workflow_state.completed_nodes.append(_NODE_LESSON)

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Autosave: lesson saved for session %s", session_id)
        return session

    async def update_after_quiz(
        self,
        session_id: str,
        topic_id: str,
        topic_name: str,
        quiz_data: dict[str, Any],
    ) -> SessionData | None:
        """Auto-save after quiz generation.

        Args:
            session_id: The session identifier.
            topic_id: The topic UUID string.
            topic_name: The topic name.
            quiz_data: The full quiz response dict.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.current_topic_id = topic_id
        session.current_topic = topic_name

        now = SessionData.now_iso()
        session.quiz_state = QuizState(
            topic_id=topic_id,
            topic_name=topic_name,
            quiz_data=quiz_data,
            generated_at=now,
        )

        session.workflow_state.current_node = _NODE_QUIZ
        if _NODE_QUIZ not in session.workflow_state.completed_nodes:
            session.workflow_state.completed_nodes.append(_NODE_QUIZ)

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Autosave: quiz saved for session %s", session_id)
        return session

    async def update_after_evaluation(
        self,
        session_id: str,
        score: float,
        evaluation_data: dict[str, Any],
        *,
        quiz_answers: list[dict[str, Any]] | None = None,
    ) -> SessionData | None:
        """Auto-save after evaluation.

        Args:
            session_id: The session identifier.
            score: The evaluation score (0.0–1.0).
            evaluation_data: The full evaluation result dict.
            quiz_answers: Optional list of student answers.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.quiz_state.score = score
        session.quiz_state.quiz_complete = True
        session.quiz_state.evaluation_data = evaluation_data
        if quiz_answers:
            session.quiz_state.answers = quiz_answers

        session.workflow_state.current_node = _NODE_EVALUATE
        if _NODE_EVALUATE not in session.workflow_state.completed_nodes:
            session.workflow_state.completed_nodes.append(_NODE_EVALUATE)

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Autosave: evaluation saved for session %s", session_id)
        return session

    async def update_after_routing(
        self,
        session_id: str,
        decision: str,
        reason: str,
        *,
        next_topic_id: str | None = None,
        weak_concepts: list[str] | None = None,
    ) -> SessionData | None:
        """Auto-save after routing decision.

        Args:
            session_id: The session identifier.
            decision: The routing decision (NEXT_TOPIC, REVIEW_TOPIC, etc.).
            reason: Explanation for the decision.
            next_topic_id: Optional next topic ID.
            weak_concepts: Optional list of weak concept tags.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.workflow_state.routing_decision = decision
        session.workflow_state.routing_reason = reason
        session.workflow_state.next_topic_id = next_topic_id
        session.workflow_state.current_node = _NODE_ROUTING
        if _NODE_ROUTING not in session.workflow_state.completed_nodes:
            session.workflow_state.completed_nodes.append(_NODE_ROUTING)

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Autosave: routing saved for session %s", session_id)
        return session

    async def update_after_topic_complete(
        self,
        session_id: str,
        topic_id: str,
        mastery_snapshot: dict[str, Any] | None = None,
    ) -> SessionData | None:
        """Auto-save after topic completion.

        Args:
            session_id: The session identifier.
            topic_id: The completed topic ID.
            mastery_snapshot: Optional updated mastery scores.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        if mastery_snapshot:
            session.mastery_snapshot.update(mastery_snapshot)

        # Reset per-topic state for the next topic
        session.current_lesson = LessonState()
        session.quiz_state = QuizState()
        session.lesson_state = {}

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        logger.info("Autosave: topic %s completed for session %s", topic_id, session_id)
        return session

    async def update_mastery(
        self,
        session_id: str,
        mastery_snapshot: dict[str, Any],
    ) -> SessionData | None:
        """Update mastery scores in the session snapshot.

        Args:
            session_id: The session identifier.
            mastery_snapshot: Dict of topic_id -> score.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.mastery_snapshot.update(mastery_snapshot)
        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        return session

    async def save_checkpoint(self, session: SessionData) -> bool:
        """Save a full session checkpoint.

        This is the main persistence method. Call it to snapshot
        the complete session state at any point.

        Args:
            session: The ``SessionData`` to persist.

        Returns:
            True if the save succeeded.
        """
        session.touch()
        return await self._checkpoint_store.save_checkpoint(session)

    async def load_checkpoint(self, session_id: str) -> SessionData | None:
        """Load a full session checkpoint.

        Args:
            session_id: The session identifier.

        Returns:
            The ``SessionData`` instance, or None.
        """
        return await self._checkpoint_store.load_checkpoint(session_id)

    async def delete_checkpoint(self, session_id: str) -> bool:
        """Delete a session checkpoint.

        Args:
            session_id: The session identifier.

        Returns:
            True if deleted.
        """
        return await self._checkpoint_store.delete_checkpoint(session_id)

    # ── Timeout handling ──────────────────────────────────────────────────

    async def check_timeout(self, session_id: str) -> SessionStatus:
        """Check if a session has timed out.

        Sessions with no activity for ``session_timeout`` seconds
        are marked IDLE. Idle sessions beyond ``max_idle_ttl``
        seconds are marked EXPIRED.

        Args:
            session_id: The session identifier.

        Returns:
            The current ``SessionStatus`` after the check.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return SessionStatus.EXPIRED

        if session.status == SessionStatus.COMPLETED:
            return session.status

        if not session.last_activity:
            return session.status

        try:
            last_active = datetime.fromisoformat(session.last_activity)
        except (ValueError, TypeError):
            return session.status

        now = datetime.now(timezone.utc)
        # If last_activity is naive, assume UTC
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)

        elapsed = (now - last_active).total_seconds()

        if elapsed >= self.max_idle_ttl:
            # Beyond max idle → expired
            session.status = SessionStatus.EXPIRED
            await self._checkpoint_store.save_checkpoint(session)
            await self._checkpoint_store.backend.delete(session_id)
            logger.info("Session %s expired after %.0f seconds idle", session_id, elapsed)
            return SessionStatus.EXPIRED

        if elapsed >= self.session_timeout:
            # Past activity timeout → idle but recoverable
            if session.status != SessionStatus.IDLE:
                session.status = SessionStatus.IDLE
                await self._checkpoint_store.save_checkpoint(session)
                await self._checkpoint_store.backend.mark_idle(session_id)
                logger.info("Session %s marked idle after %.0f seconds", session_id, elapsed)
            return SessionStatus.IDLE

        return session.status

    async def update_conversation_history(
        self,
        session_id: str,
        entry: dict[str, Any],
    ) -> SessionData | None:
        """Append an entry to the session's conversation history.

        Args:
            session_id: The session identifier.
            entry: A dict representing an interaction (e.g.,
                ``{"type": "lesson_generated", "topic_id": "...", ...}``).

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.conversation_history.append(entry)
        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        return session

    async def update_retrieval_context(
        self,
        session_id: str,
        retrieval_context: dict[str, Any],
    ) -> SessionData | None:
        """Update the retrieval context in the session.

        Args:
            session_id: The session identifier.
            retrieval_context: Dict with retrieval results (chunks, summaries).

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        session.retrieval_context.update(retrieval_context)
        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        return session

    async def update_workflow_state(
        self,
        session_id: str,
        workflow_state: WorkflowState | dict[str, Any],
    ) -> SessionData | None:
        """Update the workflow/graph execution state.

        Args:
            session_id: The session identifier.
            workflow_state: A ``WorkflowState`` instance or a dict
                of workflow fields to merge.

        Returns:
            The updated ``SessionData``, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None

        if isinstance(workflow_state, WorkflowState):
            session.workflow_state = workflow_state
        elif isinstance(workflow_state, dict):
            # Merge dict into existing workflow state
            for key, value in workflow_state.items():
                if hasattr(session.workflow_state, key):
                    setattr(session.workflow_state, key, value)

        session.touch()
        await self._checkpoint_store.save_checkpoint(session)
        return session

    async def to_dict(self, session_id: str) -> dict[str, Any] | None:
        """Get a plain dict representation of the session for API responses.

        Args:
            session_id: The session identifier.

        Returns:
            A dict of session data, or None.
        """
        session = await self._checkpoint_store.load_checkpoint(session_id)
        if session is None:
            return None
        return session.to_dict()
