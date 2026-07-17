"""Session API endpoints (Sprint 3 Phase F).

POST /api/v2/session/study — execute a full study workflow
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.workflow_orchestrator import StudyContext, WorkflowOrchestrator

router = APIRouter(prefix="/session", tags=["session"])


# ── Request / Response schemas ──────────────────────────────────────────────


class StudyRequest(BaseModel):
    topic_id: str = Field(..., description="UUID of the topic to study")
    topic_name: str = Field(..., description="Name of the topic")
    topic_description: str = Field("", description="Description of the topic")
    topic_difficulty: str = Field("beginner", description="Difficulty level")
    learning_mode: str = Field("journey", description="sprint | journey | mastery")
    mastery_score: float = Field(0.0, ge=0.0, le=1.0, description="Current mastery score")
    attempts_on_current: int = Field(0, ge=0, description="Number of prior attempts")
    prerequisite_context: str = Field("", description="Text describing prerequisites already covered")
    prerequisite_topics: list[dict] | None = Field(None, description="Prerequisite topic data")
    student_preferences: dict | None = Field(None, description="Optional learning preferences")
    user_id: str = Field("", description="User identifier")
    evaluate: bool = Field(False, description="If True, expects quiz_answers for evaluation")
    quiz_answers: list[dict] | None = Field(None, description="Answers for evaluation")


class StudyCardResponse(BaseModel):
    title: str
    body: str
    card_type: str


class StudyLessonResponse(BaseModel):
    topic_id: str
    topic_name: str
    title: str
    cards: list[StudyCardResponse]
    estimated_minutes: int
    learning_mode: str


class StudyQuestionResponse(BaseModel):
    id: str
    question: str
    options: list[str]
    difficulty: str
    concept_tag: str
    bloom_level: str
    estimated_time_seconds: int


class StudyQuizResponse(BaseModel):
    topic_id: str
    topic_name: str
    questions: list[StudyQuestionResponse]
    total_questions: int
    difficulty_breakdown: dict


class StudyEvaluationResponse(BaseModel):
    score: float
    total_questions: int
    correct_count: int
    incorrect_count: int
    weak_concept_tags: list[str]
    strong_concept_tags: list[str]
    feedback: str


class StudyRoutingResponse(BaseModel):
    decision: str
    reason: str
    next_topic_id: str | None
    weak_concepts: list[str]


class StudyResponse(BaseModel):
    lesson: StudyLessonResponse | None = None
    quiz: StudyQuizResponse | None = None
    evaluation: StudyEvaluationResponse | None = None
    routing: StudyRoutingResponse | None = None
    phase_completed: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/study", response_model=StudyResponse)
async def study_session(request: StudyRequest) -> StudyResponse:
    """Execute a full study workflow for a topic.

    Without evaluation (evaluate=False): returns lesson + quiz.
    With evaluation (evaluate=True): returns lesson + quiz + evaluation + routing.
    """
    orchestrator = WorkflowOrchestrator()
    ctx = StudyContext(
        topic_id=request.topic_id,
        topic_name=request.topic_name,
        topic_description=request.topic_description,
        topic_difficulty=request.topic_difficulty,
        learning_mode=request.learning_mode,
        mastery_score=request.mastery_score,
        attempts_on_current=request.attempts_on_current,
        prerequisite_context=request.prerequisite_context,
        prerequisite_topics=request.prerequisite_topics,
        student_preferences=request.student_preferences,
        user_id=request.user_id,
    )

    quiz_answers = request.quiz_answers if request.evaluate else None
    result = await orchestrator.run_full_study(ctx, quiz_answers=quiz_answers)

    if result.error and result.phase_completed == "error":
        raise HTTPException(status_code=502, detail=result.error)

    # Build response
    lesson_resp = None
    if result.lesson:
        lesson_resp = StudyLessonResponse(
            topic_id=result.lesson.topic_id,
            topic_name=result.lesson.topic_name,
            title=result.lesson.title,
            cards=[
                StudyCardResponse(title=c.title, body=c.body, card_type=c.card_type)
                for c in result.lesson.cards
            ],
            estimated_minutes=result.lesson.estimated_minutes,
            learning_mode=result.lesson.learning_mode,
        )

    quiz_resp = None
    if result.quiz:
        quiz_resp = StudyQuizResponse(
            topic_id=result.quiz.topic_id,
            topic_name=result.quiz.topic_name,
            questions=[
                StudyQuestionResponse(
                    id=q.id,
                    question=q.question,
                    options=q.options,
                    difficulty=q.difficulty,
                    concept_tag=q.concept_tag,
                    bloom_level=q.bloom_level,
                    estimated_time_seconds=q.estimated_time_seconds,
                )
                for q in result.quiz.questions
            ],
            total_questions=result.quiz.total_questions,
            difficulty_breakdown=result.quiz.difficulty_breakdown,
        )

    eval_resp = None
    if result.evaluation:
        eval_resp = StudyEvaluationResponse(
            score=result.evaluation.score,
            total_questions=result.evaluation.total_questions,
            correct_count=result.evaluation.correct_count,
            incorrect_count=result.evaluation.incorrect_count,
            weak_concept_tags=result.evaluation.weak_concept_tags,
            strong_concept_tags=result.evaluation.strong_concept_tags,
            feedback=result.evaluation.feedback,
        )

    routing_resp = None
    if result.routing:
        routing_resp = StudyRoutingResponse(
            decision=result.routing.decision,
            reason=result.routing.reason,
            next_topic_id=result.routing.next_topic_id,
            weak_concepts=result.routing.weak_concepts,
        )

    return StudyResponse(
        lesson=lesson_resp,
        quiz=quiz_resp,
        evaluation=eval_resp,
        routing=routing_resp,
        phase_completed=result.phase_completed,
    )
