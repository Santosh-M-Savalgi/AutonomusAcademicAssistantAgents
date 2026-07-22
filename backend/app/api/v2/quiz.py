"""Quiz API endpoints.

POST /api/v2/quiz/generate — generate a quiz for a topic (calls QuizService directly).
POST /api/v2/quiz/evaluate — evaluate quiz answers directly (no graph invocation).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_student
from app.db.models import User
from app.db.postgres import get_db
from app.db.repository import get_topic_by_id
from app.graph import get_checkpointer, initial_state
from app.llm.evaluation_service import EvaluationService
from app.llm.quiz_service import QuizService

_log = logging.getLogger(__name__)

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
    # correct_answer is NOT included in quiz output to the student


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
        description="List of answer dicts with keys: question_id, selected_answer",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session UUID for checkpoint lookup — REQUIRED. "
        "The checkpoint was saved under this session_id during lesson generation. "
        "Using topic_id as a fallback loads the wrong checkpoint and silently "
        "scores every answer as incorrect.",
    )
    syllabus_id: str = Field("", description="Syllabus UUID from /learning/goal")
    learning_goal: str = Field("", description="Original learning goal")
    topics: list[dict] = Field(default_factory=list, description="Parsed topic list from goal endpoint")


class NextTopicInfo(BaseModel):
    """Metadata about the next topic when the graph routes to NEXT_TOPIC.

    Does not include a pre-generated lesson (that would add ~8s latency).
    The frontend calls /lessons/lesson to generate the actual lesson.
    """
    topic_id: str
    topic_name: str
    topic_description: str
    topic_difficulty: str


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
    next_lesson: NextTopicInfo | None = None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/generate", response_model=QuizResponse)
async def generate_quiz(
    request: QuizGenerateRequest,
    current_user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
) -> QuizResponse:
    """Generate a multiple-choice quiz for the given topic.

    Calls QuizService directly — does not go through the graph.
    """
    topic_name = await _resolve_topic_name(db, request.topic_id, request.topic_name)

    quiz_service = QuizService()
    quiz = await quiz_service.generate_quiz(
        topic_name=topic_name,
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
async def evaluate_quiz(
    request: EvaluateRequest,
    current_user: User = Depends(get_current_student),
) -> EvaluateResponse:
    """Evaluate quiz answers directly — NO graph invocation.

    Reads the quiz (with correct answers) from the checkpoint created
    by /lessons/lesson, enriches each submitted answer with its
    correct_answer and is_correct flag, then calls EvaluationService
    for scoring + LLM feedback.

    This avoids restarting the full graph (parse → retrieve → tutor →
    quiz → evaluate) which would regenerate a different quiz with
    different correct answers, breaking scoring entirely.
    """
    # session_id is now required (Field(..., min_length=1)) so it can never
    # be empty at this point.  We use it directly as the thread_id — no
    # silent fallback to topic_id, which would load the wrong checkpoint.
    thread_id = request.session_id

    _log.info(
        "Evaluate: thread_id=%s topic_id=%s",
        thread_id, request.topic_id,
    )

    # ── 1. Read quiz from the checkpoint ───────────────────────────────
    checkpointer = get_checkpointer()
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    quiz_from_checkpoint: dict[str, Any] = {}

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None and checkpoint_tuple.checkpoint:
            channel_values = checkpoint_tuple.checkpoint.get("channel_values", {}) or {}
            quiz_from_checkpoint = channel_values.get("quiz", {}) or {}
            _log.info(
                "Checkpoint loaded: thread_id=%s quiz_questions=%d",
                thread_id,
                len(quiz_from_checkpoint.get("questions", [])),
            )
        else:
            _log.critical(
                "NO checkpoint for thread_id=%s (checkpoint_tuple=%s)",
                thread_id,
                "None" if checkpoint_tuple is None else "present but no checkpoint",
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"No checkpoint found for thread_id={thread_id}. "
                    f"The lesson+quiz was never saved, or was saved under a different "
                    f"thread_id. Verify that /lessons/lesson was called with the same "
                    f"session_id ({request.session_id}) before submitting answers."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        _log.exception("Could not read checkpoint for thread_id=%s", thread_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read checkpoint for thread_id={thread_id}",
        )

    # ── 2. Build correct-answer lookup from checkpoint quiz ────────────
    quiz_questions = quiz_from_checkpoint.get("questions", [])
    correct_map: dict[str, dict[str, str]] = {}
    for q in quiz_questions:
        qid = q.get("id", "")
        if qid:
            correct_map[qid] = {
                "correct_answer": q.get("correct_answer", ""),
                "concept_tag": q.get("concept_tag", "general"),
                "question": q.get("question", ""),
            }

    _log.info(
        "Correct map built: %d questions from checkpoint",
        len(correct_map),
    )

    # ── 3. Enrich submitted answers with correct_answer + is_correct ───
    enriched_answers: list[dict[str, Any]] = []
    for a in request.answers:
        qid = a.get("question_id", a.get("questionId", ""))
        stored = correct_map.get(qid, {})
        selected = a.get("selected_answer", a.get("selectedAnswer", ""))
        correct = stored.get("correct_answer", "")
        if not correct:
            _log.critical(
                "Scoring error: correct_answer is empty for qid=%r — in_map=%s map_keys=%s",
                qid,
                qid in correct_map,
                list(correct_map.keys()),
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Scoring error: correct_answer is empty for question {qid}. "
                    f"The checkpoint at thread_id={thread_id} may have been saved "
                    f"with an empty or incomplete quiz. "
                    f"correct_map keys: {list(correct_map.keys())}. "
                    f"This is a server-side bug — no answer can be scored against empty data."
                ),
            )
        is_correct = bool(selected.strip().lower() == correct.strip().lower())
        _log.info(
            "Evaluate answer: qid=%s selected=%r correct=%r is_correct=%s",
            qid, selected, correct, is_correct,
        )
        enriched_answers.append({
            "question_id": qid,
            "question": stored.get("question", a.get("question", "")),
            "selected_answer": selected,
            "correct_answer": correct,
            "is_correct": is_correct,
            "concept_tag": stored.get("concept_tag", "general"),
            "time_taken_seconds": a.get("time_taken_seconds", 30),
        })

    # ── 4. Evaluate: deterministic scoring + LLM feedback ──────────────
    evaluator = EvaluationService()
    evaluation = await evaluator.evaluate(
        topic_name=request.topic_name,
        questions=enriched_answers,
    )

    # ── 5. Simple score-based routing ──────────────────────────────────
    score = evaluation.score
    routing = "NEXT_TOPIC"
    routing_reason = f"Score: {score:.0%}"
    if score < 0.5:
        routing = "REPEAT_TOPIC"
        routing_reason = f"Score below 50% ({score:.0%}) — review recommended"

    return EvaluateResponse(
        score=round(score, 4),
        total_questions=evaluation.total_questions,
        correct_count=evaluation.correct_count,
        incorrect_count=evaluation.incorrect_count,
        weak_concept_tags=evaluation.weak_concept_tags,
        strong_concept_tags=evaluation.strong_concept_tags,
        feedback=evaluation.feedback,
        routing_decision=routing,
        routing_reason=routing_reason,
        next_topic_id=None,
        next_lesson=None,
    )


async def _resolve_topic_name(db: AsyncSession, topic_id: str, fallback: str) -> str:
    """Resolve a topic name from the database if the provided name is empty or looks like a UUID."""
    if not topic_id:
        return fallback
    try:
        tid = uuid.UUID(topic_id)
        needs_resolve = (
            not fallback
            or fallback == topic_id
            or re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', fallback, re.IGNORECASE)
        )
        if needs_resolve:
            topic_row = await get_topic_by_id(db, tid)
            if topic_row is not None:
                return topic_row.name
    except (ValueError, AttributeError):
        pass
    return fallback
