"""Lesson API endpoints.

POST /api/v2/lessons/lesson — generate a lesson for a topic.
Invokes the LangGraph StateGraph internally (retrieve → tutor → quiz → checkpoint).
The graph checkpoints after quiz generation so /quiz/evaluate can resume from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_student
from app.db.models import User
from app.db.postgres import get_db
from app.db.redis import get_redis
from app.db.repository import get_topic_by_id

from app.graph import get_checkpointer, get_graph, initial_state
import logging
import re
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["lessons"])

_LESSON_LOCK_PREFIX = "aaa:v2:lessons:inflight"
_LESSON_LOCK_TTL_SECONDS = 180


# ── Request / Response schemas ──────────────────────────────────────────────


class LessonRequest(BaseModel):
    topic_id: str = Field(..., description="UUID of the topic to teach")
    topic_name: str = Field(..., description="Name of the topic")
    topic_description: str = Field("", description="Description of the topic")
    topic_difficulty: str = Field("beginner", description="Difficulty level")
    learning_mode: str = Field("journey", description="sprint | journey | mastery")
    mastery_score: float = Field(0.0, ge=0.0, le=1.0, description="Current mastery score")
    prerequisite_context: str = Field("", description="Text describing prerequisites already covered")
    student_preferences: dict | None = Field(None, description="Optional learning preferences")
    user_id: str = Field("", description="User identifier")
    session_id: str = Field("", description="Session UUID for graph checkpointing")
    syllabus_id: str = Field("", description="Syllabus UUID")
    learning_goal: str = Field("", description="Original learning goal from /learning/goal")
    topics: list[dict] = Field(default_factory=list, description="Parsed topic list from goal endpoint")
    retry_on_error: bool = Field(
        False,
        description="If true, allows rerunning graph after a prior checkpointed error for this topic",
    )


class TeachingCardResponse(BaseModel):
    title: str
    body: str
    card_type: str


class YouTubeSuggestion(BaseModel):
    """A single YouTube video suggestion from Tavily search."""
    title: str
    url: str
    video_id: str


class QuizQuestionForStudent(BaseModel):
    """A quiz question as returned to the student — correct_answer is excluded."""
    id: str
    question: str
    options: list[str]
    difficulty: str
    concept_tag: str
    bloom_level: str
    estimated_time_seconds: int


class LessonResponse(BaseModel):
    topic_id: str
    topic_name: str
    title: str
    cards: list[TeachingCardResponse]
    estimated_minutes: int
    learning_mode: str
    youtube_suggestions: list[YouTubeSuggestion] | None = None
    generated_quiz: list[QuizQuestionForStudent] | None = None


@dataclass
class _LessonRunGuardDecision:
    should_return_checkpoint: bool
    checkpoint_channel_values: dict[str, Any] | None
    reason: str


def _lesson_lock_key(thread_id: str, topic_id: str) -> str:
    return f"{_LESSON_LOCK_PREFIX}:{thread_id}:{topic_id}"


async def _acquire_lesson_inflight_lock(thread_id: str, topic_id: str, lock_token: str) -> bool:
    redis = get_redis()
    key = _lesson_lock_key(thread_id, topic_id)
    acquired = await redis.set(
        key,
        lock_token,
        ex=_LESSON_LOCK_TTL_SECONDS,
        nx=True,
    )
    return bool(acquired)


async def _release_lesson_inflight_lock(thread_id: str, topic_id: str, lock_token: str) -> None:
    redis = get_redis()
    key = _lesson_lock_key(thread_id, topic_id)
    try:
        owner = await redis.get(key)
        if owner == lock_token:
            await redis.delete(key)
    except Exception:
        logger.exception(
            "Failed to release lesson in-flight lock: thread_id=%s topic_id=%s",
            thread_id,
            topic_id,
        )


def _checkpoint_channel_values(checkpoint_tuple: Any) -> dict[str, Any]:
    if checkpoint_tuple is None or not checkpoint_tuple.checkpoint:
        return {}
    checkpoint = checkpoint_tuple.checkpoint
    if not isinstance(checkpoint, dict):
        return {}
    channel_values = checkpoint.get("channel_values", {}) or {}
    if not isinstance(channel_values, dict):
        return {}
    return channel_values


def _should_resume_from_checkpoint(
    *,
    request: LessonRequest,
    checkpoint_channel_values: dict[str, Any],
) -> _LessonRunGuardDecision:
    if not checkpoint_channel_values:
        return _LessonRunGuardDecision(
            should_return_checkpoint=False,
            checkpoint_channel_values=None,
            reason="no-checkpoint",
        )

    checkpoint_topic_id = str(checkpoint_channel_values.get("current_topic_id", "") or "")
    requested_topic_id = str(request.topic_id or "")
    if checkpoint_topic_id != requested_topic_id:
        return _LessonRunGuardDecision(
            should_return_checkpoint=False,
            checkpoint_channel_values=None,
            reason="topic-changed",
        )

    lesson = checkpoint_channel_values.get("lesson")
    if not lesson:
        return _LessonRunGuardDecision(
            should_return_checkpoint=False,
            checkpoint_channel_values=None,
            reason="no-lesson-in-checkpoint",
        )

    checkpoint_error = checkpoint_channel_values.get("error")
    if checkpoint_error:
        if request.retry_on_error:
            return _LessonRunGuardDecision(
                should_return_checkpoint=False,
                checkpoint_channel_values=None,
                reason="explicit-retry-after-error",
            )
        return _LessonRunGuardDecision(
            should_return_checkpoint=True,
            checkpoint_channel_values=checkpoint_channel_values,
            reason="checkpoint-error-no-explicit-retry",
        )

    checkpoint_phase = str(checkpoint_channel_values.get("phase", "") or "")
    if checkpoint_phase in {"quiz", "evaluate", "route", "complete"}:
        return _LessonRunGuardDecision(
            should_return_checkpoint=True,
            checkpoint_channel_values=checkpoint_channel_values,
            reason=f"resume-existing-{checkpoint_phase}",
        )

    return _LessonRunGuardDecision(
        should_return_checkpoint=False,
        checkpoint_channel_values=None,
        reason=f"phase-not-resumable:{checkpoint_phase}",
    )


def _build_lesson_response_from_state(
    *,
    request: LessonRequest,
    lesson_state: dict[str, Any],
    retrieval_web_state: dict[str, Any] | None,
    quiz_state: dict[str, Any] | None,
) -> LessonResponse:
    youtube_suggestions = None
    if retrieval_web_state and isinstance(retrieval_web_state, dict):
        yt_results = retrieval_web_state.get("youtube_results", [])
        if yt_results:
            youtube_suggestions = [
                YouTubeSuggestion(
                    title=y.get("title", ""),
                    url=y.get("url", ""),
                    video_id=y.get("video_id", ""),
                )
                for y in yt_results
            ]

    generated_quiz: list[QuizQuestionForStudent] | None = None
    if quiz_state and isinstance(quiz_state, dict):
        quiz_questions = quiz_state.get("questions", [])
        if quiz_questions:
            generated_quiz = [
                QuizQuestionForStudent(
                    id=q.get("id", ""),
                    question=q.get("question", ""),
                    options=q.get("options", []),
                    difficulty=q.get("difficulty", "beginner"),
                    concept_tag=q.get("concept_tag", "general"),
                    bloom_level=q.get("bloom_level", "remember"),
                    estimated_time_seconds=q.get("estimated_time_seconds", 30),
                )
                for q in quiz_questions
            ]

    return LessonResponse(
        topic_id=lesson_state.get("topic_id", request.topic_id),
        topic_name=lesson_state.get("topic_name", request.topic_name),
        title=lesson_state.get("title", ""),
        cards=[
            TeachingCardResponse(
                title=c.get("title", ""),
                body=c.get("body", ""),
                card_type=c.get("card_type", "concept"),
            )
            for c in lesson_state.get("cards", [])
        ],
        estimated_minutes=lesson_state.get("estimated_minutes", 5),
        learning_mode=lesson_state.get("learning_mode", request.learning_mode),
        youtube_suggestions=youtube_suggestions,
        generated_quiz=generated_quiz,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/lesson", response_model=LessonResponse)
async def generate_lesson(
    request: LessonRequest,
    current_user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
) -> LessonResponse:
    """Generate a structured lesson for the given topic via the LangGraph.

    The graph runs: retrieve → tutor → quiz, then checkpoints.
    The quiz is stored in the checkpoint so /quiz/evaluate can resume
    with the same session_id.

    Frontend contract is preserved identically — same request fields,
    same response shape.
    """
    # ── Resolve topic_name when the frontend sends a UUID ──────────
    resolved_name: str = request.topic_name
    try:
        tid = uuid.UUID(request.topic_id)
        # If topic_name is empty, equals topic_id (both UUIDs), or matches
        # a UUID pattern, look up the real name from the database.
        if (
            not resolved_name
            or resolved_name == request.topic_id
            or re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', resolved_name, re.IGNORECASE)
        ):
            topic_row = await get_topic_by_id(db, tid)
            if topic_row is not None:
                resolved_name = topic_row.name
                logger.info(
                    "Resolved topic_name from DB: '%s' -> '%s'",
                    request.topic_name, resolved_name,
                )
            else:
                logger.warning(
                    "Could not resolve topic_name — no DB row for topic_id=%s",
                    request.topic_id,
                )
    except (ValueError, AttributeError):
        pass  # topic_id not a valid UUID; keep request.topic_name as-is

    # Build graph state from request
    state = initial_state(
        session_id=request.session_id,
        syllabus_id=request.syllabus_id,
        learning_goal=request.learning_goal,
        current_topic_id=request.topic_id,
        current_topic_name=resolved_name,
        current_topic_description=request.topic_description,
        current_topic_difficulty=request.topic_difficulty,
        learning_mode=request.learning_mode,
        topics=request.topics,
    )
    state["phase"] = "parse"
    state["mastery_scores"] = {request.topic_id: request.mastery_score}

    # Invoke the graph
    graph = get_graph()
    # session_id must be valid — the checkpoint is keyed by session_id so
    # /quiz/evaluate (which uses session_id) can find the stored quiz.
    # Never fall back to topic_id — that creates two separate checkpoint
    # namespaces and silently breaks scoring.
    thread_id = request.session_id
    config = {"configurable": {"thread_id": thread_id}}

    # ── Checkpoint idempotency/resume guard ───────────────────────────────
    checkpointer = get_checkpointer()
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    checkpoint_channel_values = _checkpoint_channel_values(checkpoint_tuple)
    guard = _should_resume_from_checkpoint(
        request=request,
        checkpoint_channel_values=checkpoint_channel_values,
    )
    if guard.should_return_checkpoint and guard.checkpoint_channel_values is not None:
        logger.info(
            "Lesson checkpoint resume hit: thread_id=%s topic_id=%s reason=%s",
            thread_id,
            request.topic_id,
            guard.reason,
        )
        if guard.reason == "checkpoint-error-no-explicit-retry":
            checkpoint_error = guard.checkpoint_channel_values.get("error")
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Previous lesson generation failed for this topic: {checkpoint_error}. "
                    "Set retry_on_error=true to retry generation."
                ),
            )

        lesson_from_checkpoint = guard.checkpoint_channel_values.get("lesson")
        if not isinstance(lesson_from_checkpoint, dict):
            raise HTTPException(
                status_code=500,
                detail="Checkpoint resume failed: lesson payload is invalid",
            )
        return _build_lesson_response_from_state(
            request=request,
            lesson_state=lesson_from_checkpoint,
            retrieval_web_state=guard.checkpoint_channel_values.get("retrieval_web"),
            quiz_state=guard.checkpoint_channel_values.get("quiz"),
        )

    # ── In-flight guard: prevent duplicate concurrent runs for same thread/topic ──
    lock_token = f"{time.time_ns()}-{uuid.uuid4()}"
    try:
        acquired = await _acquire_lesson_inflight_lock(thread_id, request.topic_id, lock_token)
    except Exception as exc:
        logger.exception(
            "Could not acquire lesson in-flight lock: thread_id=%s topic_id=%s",
            thread_id,
            request.topic_id,
        )
        raise HTTPException(status_code=503, detail="Could not acquire generation lock") from exc

    if not acquired:
        raise HTTPException(
            status_code=409,
            detail=(
                "Lesson generation already in progress for this session/topic. "
                "Please wait for the current generation to finish."
            ),
        )

    logger.info(
        "Invoking graph: thread_id=%s session_id=%s topic_id=%s phase=%s state_keys=%s",
        thread_id, request.session_id, request.topic_id, state.get("phase"),
        sorted(state.keys()),
    )
    logger.info(
        "Pre-invoke config: %s",
        repr(config),
    )

    try:
        try:
            result = await graph.ainvoke(state, config)
            # ── DEBUG: raw dump before any processing ──────────────────────
            logger.info(
                "Graph returned: type=%s repr=%s len=%s",
                type(result).__name__,
                repr(result)[:500] if result is not None else "None",
                len(result) if hasattr(result, "__len__") else "N/A",
            )
            if isinstance(result, dict):
                logger.info(
                    "Graph result keys: %s phase=%s error=%s",
                    sorted(result.keys()),
                    result.get("phase"),
                    result.get("error"),
                )
        except Exception as exc:
            logger.exception("Graph invocation failed: %s", repr(exc))
            raise HTTPException(status_code=502, detail=f"Graph invocation failed: {type(exc).__name__}: {exc}") from exc

        if result is None:
            raise HTTPException(
                status_code=502,
                detail="Graph returned no result — checkpointer may have failed. "
                       "Ensure the session was created by POST /learning/goal before calling /lessons/lesson.",
            )

        if result.get("error"):
            raise HTTPException(status_code=502, detail=result["error"])

        lesson = result.get("lesson")
        if lesson is None:
            raise HTTPException(status_code=500, detail="Lesson generation returned empty result")

        return _build_lesson_response_from_state(
            request=request,
            lesson_state=lesson,
            retrieval_web_state=result.get("retrieval_web"),
            quiz_state=result.get("quiz"),
        )
    finally:
        await _release_lesson_inflight_lock(thread_id, request.topic_id, lock_token)
