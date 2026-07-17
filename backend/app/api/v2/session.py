"""Session API endpoints — durable session persistence (Sprint 5, Sprint 6).

Sprint 6: all endpoints require authentication; session ownership is validated
before any operation. Only the owning student (or admin) may access a session.

Endpoints:
- POST   /sessions               — create a new learning session
- GET    /sessions/{id}          — get session state
- POST   /sessions/{id}/resume   — resume a session (recover state)
- POST   /sessions/{id}/checkpoint — save a checkpoint
- DELETE /sessions/{id}          — delete a session
- GET    /sessions/{id}/state    — get full session state dict
- POST   /sessions/{id}/complete — mark session as completed
- POST   /sessions/{id}/timeout  — check for timeout / mark idle
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_student
from app.db.models import User
from app.session.session_manager import SessionManager
from app.session.session_models import SessionData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── Singleton manager instance ─────────────────────────────────────────────


def _get_manager() -> SessionManager:
    """Return a SessionManager instance.

    Catches Redis connection errors gracefully so the API can report
    503 when the session backend is unavailable.
    """
    try:
        return SessionManager()
    except (ConnectionError, RuntimeError, Exception) as exc:
        logger.warning("Failed to initialize SessionManager: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Session persistence backend is unavailable",
        )


# ── Request / Response schemas ──────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    syllabus_id: str = Field("", description="Optional syllabus / curriculum ID")
    session_id: str | None = Field(None, description="Optional explicit session ID")
    metadata: dict[str, Any] | None = Field(None, description="Optional custom metadata")


class SessionResponse(BaseModel):
    session_id: str
    student_id: str
    syllabus_id: str
    current_topic: str = ""
    current_topic_id: str = ""
    lesson_state: dict[str, Any] = {}
    quiz_state: dict[str, Any] = {}
    workflow_state: dict[str, Any] = {}
    mastery_snapshot: dict[str, Any] = {}
    retrieval_context: dict[str, Any] = {}
    last_activity: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str = "active"
    metadata: dict[str, Any] = {}


class ResumeResponse(BaseModel):
    session: SessionResponse
    recovered: list[str] = []
    """List of recovered state components."""


class CheckpointResponse(BaseModel):
    saved: bool
    session_id: str


class CompleteResponse(BaseModel):
    completed: bool
    session_id: str
    status: str


class TimeoutResponse(BaseModel):
    session_id: str
    status: str


class StateResponse(BaseModel):
    session_id: str
    state: dict[str, Any]


class DeleteResponse(BaseModel):
    deleted: bool
    session_id: str


# ── Helper ─────────────────────────────────────────────────────────────────


def _build_session_response(session: SessionData) -> SessionResponse:
    """Build an API response from a SessionData instance."""
    return SessionResponse(
        session_id=session.session_id,
        student_id=session.student_id,
        syllabus_id=session.syllabus_id,
        current_topic=session.current_topic,
        current_topic_id=session.current_topic_id,
        lesson_state=session.current_lesson.to_dict(),
        quiz_state=session.quiz_state.to_dict(),
        workflow_state=session.workflow_state.to_dict(),
        mastery_snapshot=session.mastery_snapshot,
        retrieval_context=session.retrieval_context,
        last_activity=session.last_activity,
        created_at=session.created_at,
        updated_at=session.updated_at,
        status=session.status.value,
        metadata=session.metadata,
    )


def _validate_session_ownership(session: SessionData | None, session_id: str, user: User) -> SessionData:
    """Validate that a session exists and belongs to the current user (or admin).

    Args:
        session: The session data (may be None).
        session_id: The requested session ID (for error messaging).
        user: The authenticated user.

    Returns:
        The validated SessionData.

    Raises:
        HTTPException 404 if session not found.
        HTTPException 403 if session belongs to another user (and user is not admin).
    """
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Admin can access any session
    if user.role == "admin":
        return session

    # Student can only access own sessions
    if session.student_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this session",
        )

    return session


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_student),
) -> SessionResponse:
    """Create a new learning session for the authenticated student.

    The student_id is taken from the authenticated user, not from the request.
    """
    manager = _get_manager()
    session = await manager.create_session(
        student_id=str(current_user.id),
        syllabus_id=request.syllabus_id,
        session_id=request.session_id,
        metadata=request.metadata,
    )
    return _build_session_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> SessionResponse:
    """Get the current state of a session.

    Session must belong to the authenticated student.
    """
    manager = _get_manager()
    session = await manager.get_session(session_id)
    validated = _validate_session_ownership(session, session_id, current_user)
    return _build_session_response(validated)


@router.post("/{session_id}/resume", response_model=ResumeResponse)
async def resume_session(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> ResumeResponse:
    """Resume a session and recover its full state.

    Session must belong to the authenticated student.

    Recovers:
    - Lesson state (unfinished lesson can continue)
    - Quiz state (unfinished quiz can continue)
    - Workflow state (graph node position)
    - Routing state (last routing decision)
    - Knowledge graph state (mastery snapshot)
    - Retrieval context

    The session TTL is refreshed on resume.
    """
    manager = _get_manager()
    session = await manager.get_session(session_id)
    _validate_session_ownership(session, session_id, current_user)

    session = await manager.resume_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    recovered: list[str] = []
    if session.current_lesson and session.current_lesson.generated_at:
        recovered.append("lesson")
    if session.quiz_state and session.quiz_state.generated_at:
        recovered.append("quiz")
    if session.workflow_state and session.workflow_state.current_node:
        recovered.append("workflow")
    if session.workflow_state and session.workflow_state.routing_decision:
        recovered.append("routing")
    if session.mastery_snapshot:
        recovered.append("mastery")
    if session.retrieval_context:
        recovered.append("retrieval_context")

    return ResumeResponse(
        session=_build_session_response(session),
        recovered=recovered,
    )


@router.post("/{session_id}/checkpoint", response_model=CheckpointResponse)
async def save_checkpoint(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> CheckpointResponse:
    """Save a checkpoint for the given session.

    Session must belong to the authenticated student.
    This refreshes the session TTL and persists the current state.
    """
    manager = _get_manager()
    session = await manager.get_session(session_id)
    _validate_session_ownership(session, session_id, current_user)

    session.touch()
    saved = await manager.save_checkpoint(session)
    return CheckpointResponse(saved=saved, session_id=session_id)


@router.delete("/{session_id}", response_model=DeleteResponse)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> DeleteResponse:
    """Delete a session and its checkpoint data.

    Session must belong to the authenticated student.
    Admin can delete any session.

    Removes the session from both Redis and (optionally) Postgres.
    Returns 200 even if the session didn't exist (idempotent).
    """
    manager = _get_manager()

    # Admin bypass: if admin, skip ownership check
    if current_user.role != "admin":
        session = await manager.get_session(session_id)
        _validate_session_ownership(session, session_id, current_user)

    deleted = await manager.delete_session(session_id)
    return DeleteResponse(deleted=deleted, session_id=session_id)


@router.get("/{session_id}/state", response_model=StateResponse)
async def get_session_state(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> StateResponse:
    """Get the full session state as a plain dict.

    Session must belong to the authenticated student.

    Returns the raw serialized session data for debugging
    and frontend inspection.
    """
    manager = _get_manager()

    # Validate ownership first
    session = await manager.get_session(session_id)
    validated = _validate_session_ownership(session, session_id, current_user)

    # Use validated session to build state
    state = validated.to_dict()
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return StateResponse(session_id=session_id, state=state)


@router.post("/{session_id}/complete", response_model=CompleteResponse)
async def complete_session(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> CompleteResponse:
    """Mark a session as completed.

    Session must belong to the authenticated student.

    Once completed, the session cannot be resumed for further study
    (though its data remains accessible for review).
    """
    manager = _get_manager()
    session = await manager.get_session(session_id)
    _validate_session_ownership(session, session_id, current_user)

    completed = await manager.complete_session(session_id)
    return CompleteResponse(
        completed=completed,
        session_id=session_id,
        status="completed",
    )


@router.post("/{session_id}/timeout", response_model=TimeoutResponse)
async def check_timeout(
    session_id: str,
    current_user: User = Depends(get_current_student),
) -> TimeoutResponse:
    """Check if a session has timed out due to inactivity.

    Session must belong to the authenticated student.

    Returns the current status after the check:
    - active: session is still active
    - idle: session was marked idle (recoverable)
    - expired: session was expired (deleted from hot storage)
    """
    manager = _get_manager()

    # Validate ownership
    session = await manager.get_session(session_id)
    _validate_session_ownership(session, session_id, current_user)

    status_value = await manager.check_timeout(session_id)
    return TimeoutResponse(session_id=session_id, status=status_value.value)



