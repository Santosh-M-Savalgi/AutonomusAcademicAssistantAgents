"""Lesson API endpoints.

POST /api/v2/lessons/lesson — generate a lesson for a topic.
Invokes the LangGraph StateGraph internally (retrieve → tutor → quiz → checkpoint).
The graph checkpoints after quiz generation so /quiz/evaluate can resume from here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_student
from app.db.models import User
from app.db.postgres import get_db
from app.db.repository import get_topic_by_id

from app.graph import get_graph, initial_state
import logging
import re
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["lessons"])


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
    state["phase"] = "retrieve"
    state["mastery_scores"] = {request.topic_id: request.mastery_score}

    # Invoke the graph
    graph = get_graph()
    thread_id = request.session_id or request.topic_id
    config = {"configurable": {"thread_id": thread_id}}

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

    # Extract YouTube suggestions from retrieval_web state
    youtube_suggestions = None
    retrieval_web = result.get("retrieval_web")
    if retrieval_web and isinstance(retrieval_web, dict):
        yt_results = retrieval_web.get("youtube_results", [])
        if yt_results:
            youtube_suggestions = [
                YouTubeSuggestion(
                    title=y.get("title", ""),
                    url=y.get("url", ""),
                    video_id=y.get("video_id", ""),
                )
                for y in yt_results
            ]

    # Extract quiz questions (without correct_answer) from the graph result.
    # The graph generates the quiz during the same run — we return it so
    # the frontend can display it instantly without a second API call.
    # /quiz/evaluate reads the same quiz from the checkpoint, so the
    # question IDs and correct answers are guaranteed to match.
    generated_quiz: list[QuizQuestionForStudent] | None = None
    quiz_data = result.get("quiz")
    if quiz_data and isinstance(quiz_data, dict):
        quiz_questions = quiz_data.get("questions", [])
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
        topic_id=lesson.get("topic_id", request.topic_id),
        topic_name=lesson.get("topic_name", request.topic_name),
        title=lesson.get("title", ""),
        cards=[
            TeachingCardResponse(
                title=c.get("title", ""),
                body=c.get("body", ""),
                card_type=c.get("card_type", "concept"),
            )
            for c in lesson.get("cards", [])
        ],
        estimated_minutes=lesson.get("estimated_minutes", 5),
        learning_mode=lesson.get("learning_mode", request.learning_mode),
        youtube_suggestions=youtube_suggestions,
        generated_quiz=generated_quiz,
    )
