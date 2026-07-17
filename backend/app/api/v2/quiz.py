"""Quiz API endpoints (Sprint 3 Phase F).

POST /api/v2/quiz/generate — generate a quiz for a topic
POST /api/v2/quiz/evaluate — evaluate quiz answers
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.llm.evaluation_service import EvaluationService
from app.llm.quiz_service import QuizService
from app.services.workflow_orchestrator import StudyContext, WorkflowOrchestrator

router = APIRouter(prefix="/quiz", tags=["quiz"])


# ── Request / Response schemas ──────────────────────────────────────────────


class QuizGenerateRequest(BaseModel):
    topic_id: str = Field(..., description="UUID of the topic")
    topic_name: str = Field(..., description="Name of the topic")
    topic_description: str = Field("", description="Description of the topic")
    topic_difficulty: str = Field("beginner", description="Difficulty level")
    mastery_score: float = Field(0.0, ge=0.0, le=1.0, description="Current mastery score")
    num_questions: int = Field(5, ge=1, le=20, description="Number of questions")
    prerequisite_topics: list[dict] | None = Field(None, description="List of {id, name, mastery} dicts")


class QuizQuestionResponse(BaseModel):
    id: str
    question: str
    options: list[str]
    difficulty: str
    concept_tag: str
    bloom_level: str
    estimated_time_seconds: int
    # Note: correct_answer is NOT included in quiz output to the student
    # It's only used during evaluation. The quiz endpoint returns questions
    # without revealing the answer.


class QuizResponse(BaseModel):
    topic_id: str
    topic_name: str
    questions: list[QuizQuestionResponse]
    total_questions: int
    difficulty_breakdown: dict


class EvaluateRequest(BaseModel):
    topic_id: str = Field(..., description="UUID of the topic")
    topic_name: str = Field(..., description="Name of the topic")
    topic_difficulty: str = Field("beginner", description="Difficulty level")
    attempts_on_current: int = Field(0, ge=0, description="Number of prior attempts")
    mastery_score: float = Field(0.0, ge=0.0, le=1.0, description="Prior mastery score")
    prerequisite_topics: list[dict] | None = Field(None, description="Prerequisite topic data")
    answers: list[dict] = Field(
        ...,
        description="List of answer dicts with keys: question_id, question, "
        "selected_answer, correct_answer, is_correct, concept_tag, time_taken_seconds",
    )


class EvaluateResponse(BaseModel):
    score: float
    total_questions: int
    correct_count: int
    incorrect_count: int
    weak_concept_tags: list[str]
    strong_concept_tags: list[str]
    feedback: str
    routing_decision: str
    routing_reason: str
    next_topic_id: str | None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/generate", response_model=QuizResponse)
async def generate_quiz(request: QuizGenerateRequest) -> QuizResponse:
    """Generate a multiple-choice quiz for the given topic."""
    quiz_service = QuizService()
    quiz = await quiz_service.generate_quiz(
        topic_name=request.topic_name,
        topic_description=request.topic_description,
        topic_difficulty=request.topic_difficulty,
        mastery_score=request.mastery_score,
        num_questions=request.num_questions,
        prerequisite_topics=request.prerequisite_topics,
    )
    quiz.topic_id = request.topic_id

    return QuizResponse(
        topic_id=quiz.topic_id,
        topic_name=quiz.topic_name,
        questions=[
            QuizQuestionResponse(
                id=q.id,
                question=q.question,
                options=q.options,
                difficulty=q.difficulty,
                concept_tag=q.concept_tag,
                bloom_level=q.bloom_level,
                estimated_time_seconds=q.estimated_time_seconds,
            )
            for q in quiz.questions
        ],
        total_questions=quiz.total_questions,
        difficulty_breakdown=quiz.difficulty_breakdown,
    )


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_quiz(request: EvaluateRequest) -> EvaluateResponse:
    """Evaluate quiz answers and produce a routing decision."""
    orchestrator = WorkflowOrchestrator()
    ctx = StudyContext(
        topic_id=request.topic_id,
        topic_name=request.topic_name,
        topic_description="",
        topic_difficulty=request.topic_difficulty,
        mastery_score=request.mastery_score,
        attempts_on_current=request.attempts_on_current,
        prerequisite_topics=request.prerequisite_topics,
    )

    # Run evaluation-only (no lesson/quiz generation)
    evaluation = await orchestrator.evaluator.evaluate(
        topic_name=request.topic_name,
        questions=request.answers,
    )

    # Compute routing
    routing = orchestrator._compute_routing(ctx, evaluation)

    return EvaluateResponse(
        score=evaluation.score,
        total_questions=evaluation.total_questions,
        correct_count=evaluation.correct_count,
        incorrect_count=evaluation.incorrect_count,
        weak_concept_tags=evaluation.weak_concept_tags,
        strong_concept_tags=evaluation.strong_concept_tags,
        feedback=evaluation.feedback,
        routing_decision=routing.decision,
        routing_reason=routing.reason,
        next_topic_id=routing.next_topic_id,
    )
