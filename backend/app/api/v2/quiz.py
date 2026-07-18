"""Quiz API endpoints.

POST /api/v2/quiz/generate — generate a quiz for a topic (calls QuizService directly).
POST /api/v2/quiz/evaluate — evaluate quiz answers via the LangGraph.

/quiz/evaluate invokes the graph internally: evaluate → route.
The graph resumes from the checkpoint left by /lessons/lesson,
so the same session_id must be used across both calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_student
from app.db.models import User
from app.graph import get_graph, initial_state
from app.llm.quiz_service import QuizService

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
        description="List of answer dicts with keys: question_id, question, "
        "selected_answer, correct_answer, is_correct, concept_tag, time_taken_seconds",
    )
    session_id: str = Field("", description="Session UUID for graph checkpoint resumption")
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
async def generate_quiz(request: QuizGenerateRequest) -> QuizResponse:
    """Generate a multiple-choice quiz for the given topic.

    Calls QuizService directly — does not go through the graph.
    Use the same session_id in /quiz/evaluate to resume from
    the graph checkpoint created by /lessons/lesson.
    """
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
async def evaluate_quiz(
    request: EvaluateRequest,
    current_user: User = Depends(get_current_student),
) -> EvaluateResponse:
    """Evaluate quiz answers via the LangGraph.

    The graph resumes from the checkpoint created by /lessons/lesson
    using the same session_id. It runs: evaluate → route.

    When the routing decision is NEXT_TOPIC, ``next_lesson`` contains
    the next topic's metadata (no pre-generated lesson — the frontend
    calls /lessons/lesson for that).
    """
    # Build graph state from request
    state = initial_state(
        session_id=request.session_id,
        syllabus_id=request.syllabus_id,
        learning_goal=request.learning_goal,
        current_topic_id=request.topic_id,
        current_topic_name=request.topic_name,
        current_topic_difficulty=request.topic_difficulty,
        topics=request.topics,
    )
    state["phase"] = "evaluate"
    state["answers"] = request.answers
    state["attempts_on_current"] = request.attempts_on_current
    state["mastery_scores"] = {request.topic_id: request.mastery_score}

    # Invoke the graph — resumes from checkpoint
    graph = get_graph()
    config = {"configurable": {"thread_id": request.session_id or request.topic_id}}

    try:
        result = await graph.ainvoke(state, config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Graph invocation failed: {exc}") from exc

    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])

    evaluation = result.get("evaluation", {})
    routing = result.get("routing_decision", "")
    next_topic = result.get("next_topic_id")

    # Build next_lesson info if advancing
    next_lesson = None
    if routing == "NEXT_TOPIC" and next_topic:
        # Find the next topic in the topic list
        topics = result.get("topics", request.topics)
        for t in topics:
            if t.get("id") == next_topic or t.get("slug") == next_topic:
                next_lesson = NextTopicInfo(
                    topic_id=next_topic,
                    topic_name=t.get("name", ""),
                    topic_description=t.get("description", ""),
                    topic_difficulty=t.get("difficulty", "beginner"),
                )
                break
        if next_lesson is None:
            # Fallback: just the ID
            next_lesson = NextTopicInfo(
                topic_id=next_topic,
                topic_name=next_topic,
                topic_description="",
                topic_difficulty="beginner",
            )

    return EvaluateResponse(
        score=evaluation.get("score", 0.0),
        total_questions=evaluation.get("total_questions", 0),
        correct_count=evaluation.get("correct_count", 0),
        incorrect_count=evaluation.get("incorrect_count", 0),
        weak_concept_tags=evaluation.get("weak_concept_tags", []),
        strong_concept_tags=evaluation.get("strong_concept_tags", []),
        feedback=evaluation.get("feedback", ""),
        routing_decision=routing,
        routing_reason=result.get("routing_reason", ""),
        next_topic_id=next_topic,
        next_lesson=next_lesson,
    )
