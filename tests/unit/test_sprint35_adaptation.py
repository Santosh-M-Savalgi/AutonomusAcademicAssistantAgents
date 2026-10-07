"""Pure Sprint 3.5 scheduling, diagnostics, provenance, and planner coverage."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from packages.curriculum import (
    confirmed_transitive_prerequisites,
    diagnostic_inference_provenance,
    inferred_evidence_for_prerequisite,
    select_diagnostic_candidates,
)
from packages.domain import (
    Concept,
    DiagnosticConceptState,
    DiagnosticState,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphDefinition,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphSource,
    PlanningState,
    ReviewCandidate,
    ReviewDueReason,
    SelfReportPriorContribution,
)
from packages.domain.enums import LearningEventType, PlannerAction
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.domain.mastery import ConceptMastery, ConceptRoleSnapshot, EvidenceInput, MasteryState
from packages.mastery import (
    apply_evidence,
    confidence_value,
    metrics_for,
    recompute_after_success,
    replay,
    seed_initial_schedule,
    select_review_candidates,
)
from packages.planner import decide

START = datetime(2026, 1, 1, tzinfo=UTC)
LEARNER = uuid4()
COURSE = uuid4()
CONCEPT = uuid4()
GRAPH = uuid4()


def _evidence(
    *,
    evidence_id: UUID | None = None,
    attempt_id: UUID | None = None,
    occurred_at: datetime = START,
    is_review: bool = False,
) -> EvidenceInput:
    return EvidenceInput(
        evidence_id=evidence_id or uuid4(),
        learner_id=LEARNER,
        course_id=COURSE,
        question_id=uuid4(),
        question_version_id=uuid4(),
        attempt_id=attempt_id or uuid4(),
        correct=1.0,
        difficulty=3,
        question_type="NUMERIC",
        hints_used=0,
        grader_level="L0_RULE",
        grader_confidence=1.0,
        kind="DIRECT",
        occurred_at=occurred_at,
        graph_version_id=GRAPH,
        concept_roles=(ConceptRoleSnapshot(stable_concept_id=CONCEPT, role="PRIMARY"),),
        tag_confidence=1.0,
        is_review=is_review,
        idempotency_key=f"evidence:{evidence_id or uuid4()}",
    )


def _graph(*, edges: tuple[tuple[UUID, UUID, UUID], ...] = ()) -> GraphDefinition:
    concept_ids = {CONCEPT}
    for source, target, _ in edges:
        concept_ids.update((source, target))
    concepts = tuple(
        Concept(
            id=concept_id,
            key=f"concept-{index}",
            title=f"Concept {index}",
            source=GraphSource.USER_DEFINED,
            confidence=1.0,
            verified=True,
        )
        for index, concept_id in enumerate(sorted(concept_ids, key=lambda value: value.bytes))
    )
    nodes = tuple(
        GraphNode(
            id=concept.id,
            node_type=GraphNodeType.CONCEPT,
            label=concept.title,
            source=GraphSource.USER_DEFINED,
            confidence=1.0,
        )
        for concept in concepts
    )
    return GraphDefinition(
        nodes=nodes,
        concepts=concepts,
        mappings=(),
        edges=tuple(
            GraphEdge(
                edge_id=edge_id,
                edge_type=EdgeType.PREREQUISITE_OF,
                source_node_id=source,
                target_node_id=target,
                source=EdgeSource.USER_CONFIRMED,
                confidence=1.0,
                status=EdgeStatus.CONFIRMED,
            )
            for source, target, edge_id in edges
        ),
    )


def test_self_report_uses_actual_beta_confidence_and_remains_diagnostic_pending() -> None:
    prior = SelfReportPriorContribution(
        assertion_id=uuid4(),
        learner_id=LEARNER,
        course_id=COURSE,
        stable_concept_id=CONCEPT,
        occurred_at=START,
        policy_version="review_diagnostic_v1",
    )
    result = replay([], START + timedelta(days=1), self_report_priors=(prior,))
    state = result.projections[0].state
    assert (state.alpha, state.beta) == (2.0, 1.0)
    assert confidence_value(state) == pytest.approx(0.2)


def test_initial_one_day_schedule_then_three_day_success_interval() -> None:
    event_id = uuid4()
    schedule = seed_initial_schedule(
        learner_id=LEARNER,
        course_id=COURSE,
        stable_concept_id=CONCEPT,
        graph_version_id=GRAPH,
        first_event_id=event_id,
        first_event_at=START,
    )
    assert schedule.due_at == START + timedelta(days=1)
    projection = ConceptMastery(
        stable_concept_id=CONCEPT,
        state=MasteryState(alpha=2, beta=1, last_occurred_at=START),
        metrics=metrics_for(MasteryState(alpha=2, beta=1, last_occurred_at=START)),
    )
    selected = select_review_candidates(
        (schedule,), {CONCEPT: projection}, as_of=START + timedelta(days=1),
    )
    assert selected.candidates[0].reasons == (ReviewDueReason.REVIEW_OVERDUE,)
    advanced = recompute_after_success(
        schedule,
        review_occurred_at=START + timedelta(days=1),
        review_evidence_id=uuid4(),
        review_event_id=uuid4(),
        review_rung=1,
        review_successes=1,
        projection_revision_id=uuid4(),
        evidence_set_digest="a" * 64,
        evidence_count=2,
    )
    assert advanced.due_at == START + timedelta(days=4)


def test_diagnostic_score_uses_self_report_confidence() -> None:
    graph = _graph()
    state = DiagnosticState(
        diagnostic_run_id=uuid4(),
        learner_id=LEARNER,
        course_id=COURSE,
        graph_version_id=GRAPH,
        diagnostic_policy_version="diagnostic_v1",
    )
    candidates = select_diagnostic_candidates(
        graph,
        {CONCEPT: DiagnosticConceptState(
            stable_concept_id=CONCEPT, confidence=0.2, diagnostic_assessed=False,
        )},
        {CONCEPT: (uuid4(),)},
        state,
    )
    assert candidates[0].score == pytest.approx(0.8)
    assert candidates[0].confidence == pytest.approx(0.2)


def test_confirmed_transitive_prerequisites_deduplicate_diamond() -> None:
    left = uuid4()
    right = uuid4()
    target = uuid4()
    root = uuid4()
    graph = _graph(edges=(
        (root, left, uuid4()),
        (root, right, uuid4()),
        (left, target, uuid4()),
        (right, target, uuid4()),
    ))
    result = confirmed_transitive_prerequisites(graph, (target,))
    assert set(result) == {root, left, right}
    assert len(result[root]) == 2


def test_inferred_prerequisite_evidence_is_deterministic_and_uses_role_weight() -> None:
    prerequisite = uuid4()
    source = _evidence()
    provenance = diagnostic_inference_provenance(
        diagnostic_run_id=uuid4(),
        learner_id=LEARNER,
        source_attempt_id=source.attempt_id,
        source_question_version_id=source.question_version_id,
        source_evidence_id=source.evidence_id,
        source_graph_version_id=GRAPH,
        prerequisite_edge_ids={prerequisite: (uuid4(),)},
    )[0].model_copy(update={"target_prerequisite_concept_id": prerequisite})
    inferred = inferred_evidence_for_prerequisite(source, provenance)
    result = apply_evidence({prerequisite: MasteryState(alpha=1, beta=1)}, inferred)
    assert inferred.kind == "INFERRED"
    assert inferred.diagnostic_provenance == provenance
    assert inferred.evidence_id == inferred_evidence_for_prerequisite(
        source, provenance,
    ).evidence_id
    assert result.states[prerequisite].alpha == pytest.approx(1.15)
    assert result.states[prerequisite].n_direct == 0


def test_current_attempt_event_is_excluded_but_prior_event_remains() -> None:
    first = _evidence(evidence_id=UUID("00000000-0000-0000-0000-000000000001"))
    review = _evidence(
        evidence_id=UUID("00000000-0000-0000-0000-000000000002"),
        attempt_id=UUID("00000000-0000-0000-0000-000000000003"),
        occurred_at=START + timedelta(hours=24),
        is_review=True,
    )
    actor_id = uuid4()
    first_event = ConceptLearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=actor_id,
        actor_subject="student",
        learner_id=LEARNER,
        course_id=COURSE,
        occurred_at=START,
        payload=LearningEventPayload(kind="answer_graded", data={}),
        correlation_id=uuid4(),
        idempotency_key="first-event",
        stable_concept_ids=(CONCEPT,),
        source_evidence_id=first.evidence_id,
        source_attempt_id=first.attempt_id,
    )
    current_event = first_event.model_copy(update={
        "event_id": uuid4(),
        "occurred_at": START + timedelta(hours=23),
        "idempotency_key": "current-event",
        "source_evidence_id": review.evidence_id,
        "source_attempt_id": review.attempt_id,
    })
    result = replay(
        [first, review],
        START + timedelta(days=2),
        [first_event, current_event],
    )
    assert result.projections[0].state.review_successes == 1


def test_planner_review_does_not_override_active_remediation() -> None:
    candidate = ReviewCandidate(
        learner_id=LEARNER,
        course_id=COURSE,
        stable_concept_id=CONCEPT,
        reasons=(ReviewDueReason.REVIEW_OVERDUE,),
        due_at=START,
        decayed_mastery=0.4,
        confidence=0.5,
        mastery_status="DEVELOPING",
        review_successes=1,
        review_rung=1,
        review_policy_version="review_diagnostic_v1",
    )
    decision = decide(PlanningState(
        learner_id=LEARNER,
        course_id=COURSE,
        session_id=uuid4(),
        plan_version=1,
        planner_policy_version="planner_v1",
        active_remediation_frame=True,
        remediation_target_id=CONCEPT,
        review_candidates=(candidate,),
    ))
    assert decision.action == PlannerAction.PRACTICE_CONCEPT
