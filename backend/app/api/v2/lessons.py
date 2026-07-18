"""Lesson API endpoints.

POST /api/v2/lessons/lesson — generate a lesson for a topic.
Invokes the LangGraph StateGraph internally (retrieve → tutor → quiz → checkpoint).
The graph checkpoints after quiz generation so /quiz/evaluate can resume from here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_student
from app.db.models import User
import logging

from app.graph import get_graph, initial_state

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


class LessonResponse(BaseModel):
    topic_id: str
    topic_name: str
    title: str
    cards: list[TeachingCardResponse]
    estimated_minutes: int
    learning_mode: str
    youtube_suggestions: list[YouTubeSuggestion] | None = None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/lesson", response_model=LessonResponse)
async def generate_lesson(
    request: LessonRequest,
    current_user: User = Depends(get_current_student),
) -> LessonResponse:
    """Generate a structured lesson for the given topic via the LangGraph.

    The graph runs: retrieve → tutor → quiz, then checkpoints.
    The quiz is stored in the checkpoint so /quiz/evaluate can resume
    with the same session_id.

    Frontend contract is preserved identically — same request fields,
    same response shape.
    """
    # Build graph state from request
    state = initial_state(
        session_id=request.session_id,
        syllabus_id=request.syllabus_id,
        learning_goal=request.learning_goal,
        current_topic_id=request.topic_id,
        current_topic_name=request.topic_name,
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
    )
