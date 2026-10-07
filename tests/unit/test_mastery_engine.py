"""Pure Sprint 3.4 Beta mastery and replay coverage."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from packages.domain.enums import LearningEventType
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.domain.mastery import (
    ConceptRoleSnapshot,
    EvidenceInput,
    EvidenceRecord,
    MasteryState,
)
from packages.mastery import (
    apply_evidence,
    calculate_weight_snapshot,
    classify_status,
    decay_state,
    initial_state,
    replay,
)


def _evidence(
    *,
    evidence_id: UUID | None = None,
    question_id: UUID | None = None,
    occurred_at: datetime | None = None,
    correct: float = 1.0,
    kind: str = "DIRECT",
    is_review: bool = False,
    difficulty: int = 3,
    question_type: str = "NUMERIC",
    n_options: int | None = None,
    hints_used: int = 0,
    tag_confidence: float = 1.0,
) -> EvidenceInput:
    return EvidenceInput(
        evidence_id=evidence_id or uuid4(),
        learner_id=uuid4(),
        actor_id=None,
        course_id=uuid4(),
        question_id=question_id or uuid4(),
        question_version_id=uuid4(),
        attempt_id=uuid4(),
        correct=correct,
        difficulty=difficulty,  # type: ignore[arg-type]
        question_type=question_type,  # type: ignore[arg-type]
        n_options=n_options,
        hints_used=hints_used,
        grader_level="L0_RULE",
        grader_confidence=1.0,
        kind=kind,  # type: ignore[arg-type]
        occurred_at=occurred_at or datetime(2026, 1, 1, tzinfo=UTC),
        graph_version_id=uuid4(),
        concept_roles=(ConceptRoleSnapshot(stable_concept_id=CONCEPT, role="PRIMARY"),),
        tag_confidence=tag_confidence,
        is_review=is_review,
        idempotency_key=str(evidence_id or uuid4()),
    )


CONCEPT = uuid4()


def test_prior_and_weight_factors() -> None:
    assert initial_state().alpha == 1.0
    assert initial_state().beta == 1.0
    evidence = _evidence(difficulty=1, hints_used=2, tag_confidence=0.1)
    weights = calculate_weight_snapshot(evidence)
    assert weights.correct_difficulty_weight == 0.7
    assert weights.incorrect_difficulty_weight == 1.3
    assert weights.correct_hint_factor == 0.25
    assert weights.tag_confidence == 0.5
    assert weights.w_correct == pytest.approx(0.0875)
    assert weights.w_incorrect == pytest.approx(0.65)


def test_mcq_factor_is_used_for_both_components() -> None:
    evidence = _evidence(question_type="MCQ", n_options=4)
    weights = calculate_weight_snapshot(evidence)
    assert weights.type_weight == pytest.approx(0.45)
    assert weights.w_correct == pytest.approx(0.45)
    assert weights.w_incorrect == pytest.approx(0.45)


def test_partial_credit_and_negative_mass_conservation() -> None:
    evidence = _evidence(correct=0.25)
    application = apply_evidence({CONCEPT: initial_state()}, evidence)
    contribution = application.contributions[0]
    assert contribution.alpha_delta == pytest.approx(0.25)
    assert contribution.beta_delta == pytest.approx(0.75)
    assert sum(item.beta_delta for item in application.contributions) == pytest.approx(0.75)


def test_zero_denominator_uses_role_fallback() -> None:
    second = uuid4()
    evidence = _evidence(correct=0.0)
    evidence = evidence.model_copy(update={
        "concept_roles": (
            ConceptRoleSnapshot(stable_concept_id=CONCEPT, role="PRIMARY"),
            ConceptRoleSnapshot(stable_concept_id=second, role="PREREQUISITE"),
        )
    })
    application = apply_evidence({
        CONCEPT: MasteryState(alpha=10, beta=0),
        second: MasteryState(alpha=10, beta=0),
    }, evidence)
    deltas = {item.stable_concept_id: item.beta_delta for item in application.contributions}
    assert deltas[CONCEPT] == pytest.approx(1.0 / 1.5)
    assert deltas[second] == pytest.approx(1.0 / 3.0)
    assert sum(deltas.values()) == pytest.approx(1.0)


def test_inferred_partial_is_auditable_and_unapplied() -> None:
    evidence = _evidence(kind="INFERRED", correct=0.5)
    application = apply_evidence({CONCEPT: initial_state()}, evidence)
    assert application.states == {CONCEPT: initial_state()}
    assert not application.contributions[0].applied
    assert application.contributions[0].reason == "INFERRED_PARTIAL_OR_INCORRECT_AUDIT_ONLY"


def test_inferred_positive_does_not_count_direct() -> None:
    evidence = _evidence(kind="INFERRED")
    application = apply_evidence({CONCEPT: initial_state()}, evidence)
    state = application.states[CONCEPT]
    assert state.alpha == pytest.approx(1.3)
    assert state.n_direct == 0
    assert not state.distinct_direct_question_ids


def test_status_precedence_and_direct_counts() -> None:
    question_a = uuid4()
    question_b = uuid4()
    state = MasteryState(
        alpha=5,
        beta=1,
        n_direct=3,
        distinct_direct_question_ids=(question_a, question_b),
        has_qualifying_review=True,
    )
    assert classify_status(state) == "MASTERED"
    assert classify_status(state, False) == "PROFICIENT"
    application = apply_evidence(
        {CONCEPT: state},
        _evidence(question_id=question_a),
    )
    assert application.states[CONCEPT].n_direct == 4
    assert application.states[CONCEPT].distinct_direct_question_ids == (question_a, question_b)


def test_lazy_forgetting_requires_explicit_time() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    state = MasteryState(alpha=5, beta=1, last_occurred_at=start)
    decayed = decay_state(state, start + timedelta(days=21))
    assert decayed.alpha == pytest.approx(3.0)
    with pytest.raises(ValueError, match="backwards"):
        decay_state(state, start - timedelta(seconds=1))


def test_replay_is_arrival_order_independent_at_same_as_of() -> None:
    as_of = datetime(2026, 2, 1, tzinfo=UTC)
    first = _evidence(evidence_id=UUID("00000000-0000-0000-0000-000000000001"))
    second = _evidence(
        evidence_id=UUID("00000000-0000-0000-0000-000000000002"),
        correct=0.0,
    )
    first = first.model_copy(update={"occurred_at": datetime(2026, 1, 1, tzinfo=UTC)})
    second = second.model_copy(update={"occurred_at": datetime(2026, 1, 1, tzinfo=UTC)})
    left = replay([first, second], as_of)
    right = replay([second, first], as_of)
    assert left.evidence_set_digest == right.evidence_set_digest
    assert left.projections == right.projections


def test_digest_matches_base_input_and_is_independent_of_projection_time() -> None:
    evidence = _evidence()
    persisted = EvidenceRecord(
        **evidence.model_dump(), recorded_at=evidence.occurred_at + timedelta(days=1),
        applied_at=evidence.occurred_at + timedelta(days=2),
    )
    first = replay([evidence], evidence.occurred_at)
    later = replay([persisted], evidence.occurred_at + timedelta(days=21))
    assert first.evidence_set_digest == later.evidence_set_digest
    assert first.max_occurred_at == later.max_occurred_at == evidence.occurred_at
    assert first.projections[0].state.alpha != later.projections[0].state.alpha
    changed = replay([evidence.model_copy(update={"correct": 0.0})], evidence.occurred_at)
    assert changed.evidence_set_digest != first.evidence_set_digest


def test_sequential_concept_updates_preserve_other_concept_posteriors() -> None:
    second_concept = UUID("00000000-0000-0000-0000-000000000004")
    direct = _evidence()
    inferred = _evidence(kind="INFERRED").model_copy(update={
        "concept_roles": (ConceptRoleSnapshot(
            stable_concept_id=second_concept, role="PREREQUISITE",
        ),),
        "occurred_at": direct.occurred_at + timedelta(seconds=1),
    })
    result = replay([direct, inferred], inferred.occurred_at)
    projections = {item.stable_concept_id: item for item in result.projections}
    assert set(projections) == {CONCEPT, second_concept}
    assert projections[CONCEPT].state.n_direct == 1
    assert projections[CONCEPT].state.alpha > 1
    assert projections[second_concept].state.alpha == pytest.approx(1.15)
    assert projections[second_concept].state.n_direct == 0
    assert projections[second_concept].state.review_successes == 0


def test_replay_digest_uses_immutable_evidence_not_receipts() -> None:
    evidence = _evidence(evidence_id=UUID("00000000-0000-0000-0000-000000000003"))
    first = EvidenceRecord(
        **evidence.model_dump(),
        recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
        applied_at=None,
    )
    second = first.model_copy(update={
        "recorded_at": datetime(2026, 2, 2, tzinfo=UTC),
        "applied_at": datetime(2026, 2, 3, tzinfo=UTC),
    })
    left = replay([first], datetime(2026, 3, 1, tzinfo=UTC))
    right = replay([second], datetime(2026, 3, 1, tzinfo=UTC))
    assert left.evidence_set_digest == right.evidence_set_digest
    assert left.projections == right.projections


def test_review_success_uses_concept_event_clock() -> None:
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    review_time = first_time + timedelta(hours=24)
    first = _evidence(occurred_at=first_time)
    review = _evidence(occurred_at=review_time, is_review=True)
    event = ConceptLearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=uuid4(),
        actor_subject="actor",
        learner_id=first.learner_id,
        course_id=first.course_id,
        occurred_at=first_time,
        payload=LearningEventPayload(kind="answer_graded", data={}),
        correlation_id=uuid4(),
        idempotency_key="clock-event",
        stable_concept_ids=(CONCEPT,),
    )
    review = review.model_copy(update={
        "learner_id": first.learner_id,
        "course_id": first.course_id,
    })
    result = replay([first, review], review_time, [event])
    assert result.projections[0].state.review_successes == 1
    assert result.projections[0].state.review_rung == 1
