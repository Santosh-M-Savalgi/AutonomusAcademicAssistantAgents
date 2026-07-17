"""Lesson API endpoints (Sprint 3 Phase F).

POST /api/v2/lessons/lesson — generate a lesson for a topic
Uses TutorService behind the WorkflowOrchestrator.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.llm.tutor_service import TutorService
from app.services.workflow_orchestrator import StudyContext, WorkflowOrchestrator

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


class TeachingCardResponse(BaseModel):
    title: str
    body: str
    card_type: str


class LessonResponse(BaseModel):
    topic_id: str
    topic_name: str
    title: str
    cards: list[TeachingCardResponse]
    estimated_minutes: int
    learning_mode: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/lesson", response_model=LessonResponse)
async def generate_lesson(request: LessonRequest) -> LessonResponse:
    """Generate a structured lesson for the given topic."""
    orchestrator = WorkflowOrchestrator()
    ctx = StudyContext(
        topic_id=request.topic_id,
        topic_name=request.topic_name,
        topic_description=request.topic_description,
        topic_difficulty=request.topic_difficulty,
        learning_mode=request.learning_mode,
        mastery_score=request.mastery_score,
        prerequisite_context=request.prerequisite_context,
        student_preferences=request.student_preferences,
        user_id=request.user_id,
    )

    result = await orchestrator.generate_lesson(ctx)

    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    if result.lesson is None:
        raise HTTPException(status_code=500, detail="Lesson generation returned empty result")

    lesson = result.lesson
    return LessonResponse(
        topic_id=lesson.topic_id,
        topic_name=lesson.topic_name,
        title=lesson.title,
        cards=[
            TeachingCardResponse(title=c.title, body=c.body, card_type=c.card_type)
            for c in lesson.cards
        ],
        estimated_minutes=lesson.estimated_minutes,
        learning_mode=lesson.learning_mode,
    )
