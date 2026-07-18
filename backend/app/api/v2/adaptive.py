"""Adaptive Learning Engine — API endpoints (Sprint 8 Part 9).

Provides:
- GET  /adaptive/status          — overview of learner's adaptive state
- GET  /adaptive/plan            — personalized learning plan
- GET  /adaptive/diagnosis       — root-cause diagnosis for a topic
- GET  /adaptive/recommendations — adaptive recommendations
- POST /adaptive/evaluate        — evaluate mastery for a topic
- POST /adaptive/remediate       — generate remediation plan
- GET  /adaptive/path            — adaptive learning path

Authorization:
- Students: access only their own data
- Admins: can inspect any learner via optional user_id query param
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.diagnostics import DiagnosisEngine
from app.adaptive.engine import AdaptiveEngine
from app.adaptive.models import (
    AdaptiveStatus,
    DecisionType,
    DiagnosisReport,
    LearningPlan,
    MasteryEvaluation,
    MasteryState,
    RemediationPlan,
)
from app.adaptive.planner import AdaptivePlanner, RemediationPlanner
from app.adaptive.recommendations import AdaptiveRecommender
from app.adaptive.rules import AdaptiveRuleEngine, RuleContext
from app.adaptive.schemas import (
    AdaptiveStatusResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExplanationSchema,
    LearningPlanResponse,
    MasteryEvaluationSchema,
    PathRequest,
    PathResponse,
    PathStepSchema,
    PlanStepSchema,
    RecommendationResponse,
    RecommendationSchema,
    RemediateRequest,
    RemediateResponse,
)
from app.auth.dependencies import get_current_user, require_admin
from app.db.models import (
    ConceptMastery,
    QuizAttempt,
    Session,
    Topic,
    TopicEdge,
    User,
)
from app.db.postgres import get_db
from app.db.repository import get_mastery, get_session_by_id, get_topic_by_id
from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    build_graph_from_models,
)

router = APIRouter(prefix="/adaptive", tags=["adaptive"])


# ── Singleton Engines ──────────────────────────────────────────────────────

_engine = AdaptiveEngine()
_rule_engine = AdaptiveRuleEngine()
_diagnosis_engine = DiagnosisEngine()
_planner = AdaptivePlanner()
_remediation_planner = RemediationPlanner()
_recommender = AdaptiveRecommender()


# ── Helpers ────────────────────────────────────────────────────────────────


async def _build_graph(db: AsyncSession) -> KnowledgeGraph:
    """Build an in-memory KnowledgeGraph from database data."""
    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())

    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    return build_graph_from_models(topics, edges)


async def _get_user_mastery_map(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic_ids: list[uuid.UUID],
) -> dict[uuid.UUID, MasteryEvaluation]:
    """Build a mastery evaluation map for a set of topic IDs."""
    mastery_map: dict[uuid.UUID, MasteryEvaluation] = {}
    for tid in topic_ids:
        cm = await get_mastery(db, user_id, tid)
        # Get quiz attempts for this topic
        quiz_result = await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.user_id == user_id,
                QuizAttempt.topic_id == tid,
            )
            .order_by(QuizAttempt.submitted_at.desc())
        )
        quiz_attempts = list(quiz_result.scalars().all())

        topic = await get_topic_by_id(db, tid)
        topic_name = topic.name if topic else f"topic-{tid}"
        threshold = topic.mastery_threshold if topic else 0.75

        evaluation = _engine.evaluate(
            topic_id=tid,
            topic_name=topic_name,
            mastery_row=cm,
            quiz_attempts=quiz_attempts,
            threshold=threshold,
        )
        mastery_map[tid] = evaluation
    return mastery_map


async def _resolve_user_id(
    current_user: User,
    requested_user_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> uuid.UUID:
    """Resolve the target user ID respecting authorization rules.

    Students can only access their own data.
    Admins can specify any user via query param.
    """
    if current_user.role == "admin" and requested_user_id is not None:
        return requested_user_id
    return current_user.id


# ── Status ─────────────────────────────────────────────────────────────────


@router.get("/status", response_model=AdaptiveStatusResponse)
async def get_adaptive_status(
    user_id: uuid.UUID | None = Query(None, description="Optional: admin override for target user"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdaptiveStatusResponse:
    """Get the learner's adaptive state overview across all topics.

    Returns total topics, mastered count, current topic, and state distribution.
    """
    target_user_id = await _resolve_user_id(current_user, user_id)

    # Get the user's current session
    session_result = await db.execute(
        select(Session)
        .where(Session.user_id == target_user_id)
        .order_by(Session.last_active_at.desc())
        .limit(1)
    )
    session = session_result.scalar_one_or_none()

    current_topic_id = session.current_topic_id if session else None

    # Get all topics
    graph = await _build_graph(db)

    # Get all mastery rows for this user
    mastery_result = await db.execute(
        select(ConceptMastery).where(ConceptMastery.user_id == target_user_id)
    )
    mastery_rows = list(mastery_result.scalars().all())

    # Build mastery evaluations
    mastery_map = await _get_user_mastery_map(
        db, target_user_id, list(graph.nodes.keys())
    )

    # Count by state
    state_counts: dict[MasteryState, int] = {s: 0 for s in MasteryState}
    total = 0
    for meval in mastery_map.values():
        state_counts[meval.mastery_state] += 1
        total += 1

    # Determine current state
    current_state = MasteryState.NOT_STARTED
    if current_topic_id and current_topic_id in mastery_map:
        current_state = mastery_map[current_topic_id].mastery_state

    last_activity = None
    if session:
        last_activity = session.last_active_at

    return AdaptiveStatusResponse(
        user_id=target_user_id,
        total_topics=total,
        mastered_topics=state_counts.get(MasteryState.MASTERED, 0),
        current_topic_id=current_topic_id,
        current_state=current_state,
        topics_by_state={s.value: c for s, c in state_counts.items()},
        last_activity=last_activity,
        active_rules=_rule_engine.get_rule_names(),
    )


# ── Plan ───────────────────────────────────────────────────────────────────


@router.get("/plan", response_model=LearningPlanResponse)
async def get_adaptive_plan(
    mode: str = Query("standard", description="Learning mode: beginner | standard | fast_track"),
    user_id: uuid.UUID | None = Query(None, description="Optional: admin override"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LearningPlanResponse:
    """Generate a personalized adaptive learning plan."""
    target_user_id = await _resolve_user_id(current_user, user_id)
    graph = await _build_graph(db)

    # Get all topics (for simplicity, use all graph nodes as syllabus)
    all_topic_ids = list(graph.nodes.keys())
    mastery_map = await _get_user_mastery_map(db, target_user_id, all_topic_ids)

    # Get current session
    session_result = await db.execute(
        select(Session)
        .where(Session.user_id == target_user_id)
        .order_by(Session.last_active_at.desc())
        .limit(1)
    )
    session = session_result.scalar_one_or_none()

    plan = _planner.plan(
        user_id=target_user_id,
        graph=graph,
        syllabus_topic_ids=all_topic_ids,
        mastery_map=mastery_map,
        current_topic_id=session.current_topic_id if session else None,
        mode=mode,
    )

    return LearningPlanResponse(
        user_id=plan.user_id,
        steps=[
            PlanStepSchema(
                topic_id=s.topic_id,
                topic_name=s.topic_name,
                action=s.action,
                priority=s.priority,
                estimated_minutes=s.estimated_minutes,
                reason=s.reason,
            )
            for s in plan.steps
        ],
        total_estimated_minutes=plan.total_estimated_minutes,
        completion_path=plan.completion_path,
        explanation=_to_explanation_schema(plan.explanation),
    )


# ── Diagnosis ──────────────────────────────────────────────────────────────


@router.get("/diagnosis", response_model=DiagnosisResponse)
async def get_diagnosis(
    topic_id: uuid.UUID = Query(..., description="Topic ID to diagnose"),
    user_id: uuid.UUID | None = Query(None, description="Optional: admin override"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DiagnosisResponse:
    """Get root-cause diagnosis for a topic the learner is struggling with."""
    target_user_id = await _resolve_user_id(current_user, user_id)
    graph = await _build_graph(db)

    topic = await get_topic_by_id(db, topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found.",
        )

    # Build mastery evaluations for transitive prerequisites
    prereq_depths = graph.get_transitive_prerequisites(topic_id)
    prereq_ids = list(prereq_depths.keys())
    mastery_map = await _get_user_mastery_map(db, target_user_id, prereq_ids + [topic_id])

    report = _diagnosis_engine.diagnose(
        topic_id=topic_id,
        topic_name=topic.name,
        graph=graph,
        mastery_map=mastery_map,
    )

    return DiagnosisResponse(
        topic_id=report.topic_id,
        topic_name=report.topic_name,
        root_concept_id=report.root_concept_id,
        root_concept_name=report.root_concept_name,
        supporting_concepts=report.supporting_concepts,
        missing_prerequisites=report.missing_prerequisites,
        reasoning_chain=report.reasoning_chain,
        confidence=report.confidence,
        explanation=_to_explanation_schema(report.explanation),
    )


# ── Recommendations ────────────────────────────────────────────────────────


@router.get("/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    topic_id: uuid.UUID | None = Query(None, description="Optional: focus recommendations on a specific topic"),
    user_id: uuid.UUID | None = Query(None, description="Optional: admin override"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationResponse:
    """Get personalized adaptive recommendations."""
    target_user_id = await _resolve_user_id(current_user, user_id)
    graph = await _build_graph(db)

    all_topic_ids = list(graph.nodes.keys())
    mastery_map = await _get_user_mastery_map(db, target_user_id, all_topic_ids)

    # Resolve current topic
    current_topic_id = topic_id
    if current_topic_id is None:
        session_result = await db.execute(
            select(Session)
            .where(Session.user_id == target_user_id)
            .order_by(Session.last_active_at.desc())
            .limit(1)
        )
        session = session_result.scalar_one_or_none()
        if session:
            current_topic_id = session.current_topic_id

    recs = _recommender.recommend(
        user_id=target_user_id,
        graph=graph,
        current_topic_id=current_topic_id,
        mastery_map=mastery_map,
        syllabus_topic_ids=all_topic_ids,
    )

    return RecommendationResponse(
        user_id=target_user_id,
        recommendations=[
            RecommendationSchema(
                type=r.type,
                topic_id=r.topic_id,
                topic_name=r.topic_name,
                priority=r.priority,
                reason=r.reason,
                explanation=_to_explanation_schema(r.explanation),
            )
            for r in recs
        ],
    )


# ── Evaluate ───────────────────────────────────────────────────────────────


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_mastery(
    body: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvaluateResponse:
    """Evaluate mastery for a topic and return an adaptive decision."""
    graph = await _build_graph(db)

    # Resolve topic
    topic_id = body.topic_id
    if topic_id is None:
        session_result = await db.execute(
            select(Session)
            .where(Session.user_id == current_user.id)
            .order_by(Session.last_active_at.desc())
            .limit(1)
        )
        session = session_result.scalar_one_or_none()
        topic_id = session.current_topic_id if session else None

    if topic_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No topic_id provided and no active session found.",
        )

    topic = await get_topic_by_id(db, topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found.",
        )

    # Evaluate
    mastery_map = await _get_user_mastery_map(db, current_user.id, [topic_id])
    evaluation = mastery_map.get(topic_id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate mastery.",
        )

    # Evaluate prerequisites
    prereq_ids = graph.get_prerequisites(topic_id)
    prereq_mastery = await _get_user_mastery_map(db, current_user.id, list(prereq_ids))

    # Apply rules
    context = RuleContext(
        evaluation=evaluation,
        prerequisite_mastery=prereq_mastery,
        graph=graph,
    )
    decision, explanation = _rule_engine.evaluate(context)

    return EvaluateResponse(
        evaluation=MasteryEvaluationSchema(
            topic_id=evaluation.topic_id,
            topic_name=evaluation.topic_name,
            mastery_state=evaluation.mastery_state,
            score=evaluation.score,
            confidence=evaluation.confidence,
            quiz_scores=evaluation.quiz_scores,
            attempt_count=evaluation.attempt_count,
            time_since_last_study_hours=evaluation.time_since_last_study_hours,
            historical_trend=evaluation.historical_trend,
            repeated_failures=evaluation.repeated_failures,
            trend_direction=evaluation.trend_direction,
            recent_activity=evaluation.recent_activity,
            factors=evaluation.factors,
        ),
        decision=decision,
        explanation=_to_explanation_schema(explanation),
    )


# ── Remediate ──────────────────────────────────────────────────────────────


@router.post("/remediate", response_model=RemediateResponse)
async def remediate_topic(
    body: RemediateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediateResponse:
    """Generate a remediation plan for a struggling topic."""
    graph = await _build_graph(db)

    topic = await get_topic_by_id(db, body.topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {body.topic_id} not found.",
        )

    # Get prerequisite mastery
    prereq_ids = list(graph.get_prerequisites(body.topic_id))
    mastery_map = await _get_user_mastery_map(
        db, current_user.id, prereq_ids + [body.topic_id]
    )

    plan = _remediation_planner.plan(
        topic_id=body.topic_id,
        topic_name=topic.name,
        graph=graph,
        mastery_map=mastery_map,
    )

    return RemediateResponse(
        topic_id=plan.topic_id,
        topic_name=plan.topic_name,
        weak_concepts=plan.weak_concepts,
        practice_recommendations=plan.practice_recommendations,
        suggested_review_sequence=plan.suggested_review_sequence,
        estimated_remediation_minutes=plan.estimated_remediation_minutes,
        required_quizzes=plan.required_quizzes,
        target_mastery=plan.target_mastery,
        explanation=_to_explanation_schema(plan.explanation),
    )


# ── Path ───────────────────────────────────────────────────────────────────


@router.get("/path", response_model=PathResponse)
async def get_adaptive_path(
    mode: str = Query("standard", description="Learning mode: beginner | standard | fast_track"),
    user_id: uuid.UUID | None = Query(None, description="Optional: admin override"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PathResponse:
    """Get the adaptive learning path with mastery states."""
    target_user_id = await _resolve_user_id(current_user, user_id)
    graph = await _build_graph(db)

    all_topic_ids = list(graph.nodes.keys())
    mastery_map = await _get_user_mastery_map(db, target_user_id, all_topic_ids)

    # Build raw scores for topo
    raw_scores = {tid: m.score for tid, m in mastery_map.items()}

    from app.services.learning_path_service import (
        LearningMode,
        LearningPathService,
    )
    path_svc = LearningPathService()

    lm = LearningMode.STANDARD
    if mode == "beginner":
        lm = LearningMode.BEGINNER
    elif mode == "fast_track":
        lm = LearningMode.FAST_TRACK

    base_path = path_svc.generate(
        graph=graph,
        syllabus_topic_ids=all_topic_ids,
        mastery_scores=raw_scores,
        mode=lm,
    )

    steps = []
    for ps in base_path.steps:
        meval = mastery_map.get(ps.topic_id)
        state = meval.mastery_state if meval else MasteryState.NOT_STARTED
        score = meval.score if meval else 0.0

        steps.append(PathStepSchema(
            topic_id=ps.topic_id,
            topic_name=ps.topic_name,
            topic_slug=ps.topic_slug,
            difficulty=ps.difficulty,
            mastery_state=state,
            score=score,
            is_blocked=ps.is_blocked,
            unmet_prerequisites=ps.unmet_prerequisites,
            estimated_minutes=15,
        ))

    completed = sum(1 for s in steps if s.mastery_state == MasteryState.MASTERED)

    return PathResponse(
        user_id=target_user_id,
        steps=steps,
        total_topics=len(steps),
        completed_topics=completed,
        remaining_topics=len(steps) - completed,
        next_topic_id=base_path.next_topic_id,
    )


# ── Serialization Helpers ──────────────────────────────────────────────────


def _to_explanation_schema(explanation: object | None) -> ExplanationSchema | None:
    """Convert an Explanation domain object to its Pydantic schema."""
    if explanation is None:
        return None
    from app.adaptive.models import Explanation
    if not isinstance(explanation, Explanation):
        return None
    return ExplanationSchema(
        decision=explanation.decision,
        reason=explanation.reason,
        evidence=explanation.evidence,
        metrics_used=explanation.metrics_used,
        confidence=explanation.confidence,
        rules_triggered=explanation.rules_triggered,
        prerequisites_examined=explanation.prerequisites_examined,
    )
