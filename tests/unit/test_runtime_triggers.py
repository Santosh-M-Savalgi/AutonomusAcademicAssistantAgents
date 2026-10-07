"""Pure trigger thresholds, source accounting and explicit readiness guards."""

from datetime import timedelta
from uuid import uuid4

import pytest

from packages.domain.runtime import SourceIdentity, SourceKind
from packages.domain.triggers import (
    GradeObservation,
    GuardCode,
    TriggerFacts,
    TriggerKind,
    TriggerStatus,
    TriggerSubmission,
)
from packages.planner.triggers import evaluate_trigger
from tests.unit.test_runtime_contracts import AT


def facts_for(kind, **changes):
    request = TriggerSubmission(
        learner_id=uuid4(), session_id=uuid4(), source=SourceIdentity(
            kind=SourceKind.EVENT, source_id=uuid4(),
        ), source_event_id=uuid4(), kind=kind, expected_session_version=1,
        window_id=uuid4(), evidence_id=uuid4(),
    )
    return TriggerFacts(submission=request, session_version=1, **changes)


def grade(facts, *, source=False, **changes):
    return GradeObservation(
        evidence_id=facts.submission.evidence_id if source else uuid4(),
        attempt_id=uuid4(), event_id=uuid4(), window_id=facts.submission.window_id,
        concept_id=uuid4(), correct=0, weight=0.5, direct=True, qualified_impact=True,
    ).model_copy(update=changes)


def test_single_wrong_answer_has_no_unconditional_replan_even_when_state_missing():
    facts = facts_for(TriggerKind.SINGLE_WRONG_ANSWER, guards=(GuardCode.MISSING_PROJECTION,))
    facts = facts.model_copy(update={"observations": (grade(facts, source=True),)})
    result = evaluate_trigger(facts, AT)
    assert result.status == TriggerStatus.EVIDENCE_ONLY
    assert not result.material and result.eligible_after is None


@pytest.mark.parametrize("change,material", [
    ({}, True), ({"weight": 0.499}, False), ({"correct": 1}, False),
    ({"window_id": uuid4()}, False), ({"concept_id": uuid4()}, False),
    ({"direct": False}, False), ({"qualified_impact": False}, False),
])
def test_repeated_failure_requires_distinct_qualified_items_in_one_concept_window(change, material):
    facts = facts_for(TriggerKind.SINGLE_WRONG_ANSWER)
    first = grade(facts, source=True)
    second_changes = {"concept_id": first.concept_id, **change}
    second = grade(facts, **second_changes)
    facts = facts.model_copy(update={"observations": (first, second)})
    assert evaluate_trigger(facts, AT).material == material
    assert evaluate_trigger(facts, AT) == evaluate_trigger(facts, AT)


def test_duplicate_item_and_read_replay_cannot_add_an_attempt():
    facts = facts_for(TriggerKind.REPEATED_FAILURE)
    first = grade(facts, source=True)
    replay = first.model_copy(update={"evidence_id": uuid4()})
    facts = facts.model_copy(update={"observations": (first, replay, first)})
    assert not evaluate_trigger(facts, AT).material


@pytest.mark.parametrize("confidence,material", [(0.299, False), (0.3, True)])
def test_entry_into_weak_is_the_approved_alternative(confidence, material):
    facts = facts_for(TriggerKind.SINGLE_WRONG_ANSWER)
    facts = facts.model_copy(update={"observations": (
        grade(facts, source=True, entered_weak=True, confidence=confidence),
    )})
    assert evaluate_trigger(facts, AT).material == material


@pytest.mark.parametrize("kind,changes,material", [
    (TriggerKind.BATCH_COMPLETED, {"batch_completed": True}, True),
    (TriggerKind.STRONG_PERFORMANCE, {
        "batch_completed": True, "batch_is_quiz": True, "batch_score": 0.9,
        "batch_item_count": 3, "gate_satisfied": True,
    }, True),
    (TriggerKind.STRONG_PERFORMANCE, {
        "batch_completed": True, "batch_is_quiz": True, "batch_score": 0.899,
        "batch_item_count": 3, "gate_satisfied": True,
    }, False),
    (TriggerKind.STRONG_PERFORMANCE, {
        "batch_completed": True, "batch_is_quiz": True, "batch_score": 1,
        "batch_item_count": 2, "gate_satisfied": True,
    }, False),
    (TriggerKind.STRONG_PERFORMANCE, {
        "batch_completed": True, "batch_is_quiz": True, "batch_score": 1,
        "batch_item_count": 3, "gate_satisfied": False,
    }, False),
    (TriggerKind.CURRICULUM_EDITED, {}, True),
    (TriggerKind.NIGHTLY_DECAY, {"review_available": True}, True),
    (TriggerKind.NIGHTLY_DECAY, {}, False),
    (TriggerKind.EXPLICIT_DIRECTIVE, {"directive_valid": True}, True),
    (TriggerKind.DEADLINE_CHANGED, {}, True),
])
def test_every_approved_material_trigger(kind, changes, material):
    result = evaluate_trigger(facts_for(kind, **changes), AT)
    assert result.material == material


def test_student_cooldown_boundary_and_directive_exception():
    facts = facts_for(TriggerKind.BATCH_COMPLETED, batch_completed=True, last_plan_trigger_at=AT)
    deferred = evaluate_trigger(facts, AT + timedelta(seconds=59))
    assert deferred.status == TriggerStatus.DEFERRED
    assert deferred.eligible_after == AT + timedelta(seconds=60)
    assert evaluate_trigger(facts, deferred.eligible_after).status == TriggerStatus.ADMITTED
    directive = facts_for(TriggerKind.EXPLICIT_DIRECTIVE,
                          directive_valid=True, last_plan_trigger_at=AT)
    assert evaluate_trigger(directive, AT).status == TriggerStatus.ADMITTED


@pytest.mark.parametrize("guard", [
    GuardCode.STALE_SESSION, GuardCode.STALE_GRAPH, GuardCode.MISSING_PROJECTION,
    GuardCode.MISSING_REVISION, GuardCode.STALE_EVIDENCE_SET, GuardCode.MISSING_GRAPH_CONTEXT,
    GuardCode.UNAVAILABLE_REQUIRED_STATE, GuardCode.TERMINAL_SESSION,
])
def test_unavailable_state_has_a_typed_result(guard):
    facts = facts_for(TriggerKind.BATCH_COMPLETED, batch_completed=True, guards=(guard,))
    result = evaluate_trigger(facts, AT)
    assert guard in result.guards
    assert result.status in {TriggerStatus.BLOCKED, TriggerStatus.REJECTED}
    assert result.eligible_after is None


def test_active_remediation_suppresses_review_but_does_not_invent_a_global_pause():
    facts = facts_for(TriggerKind.NIGHTLY_DECAY, review_available=True, active_remediation=True)
    assert GuardCode.ACTIVE_REMEDIATION in evaluate_trigger(facts, AT).guards
    assessment = facts_for(TriggerKind.BATCH_COMPLETED,
                           batch_completed=True, active_remediation=True)
    assert evaluate_trigger(assessment, AT).status == TriggerStatus.ADMITTED


def test_invalid_expired_and_duplicate_directives_do_not_use_a_cooldown_slot():
    for changes, expected in (
        ({}, GuardCode.INVALID_DIRECTIVE),
        ({"directive_valid": True, "directive_expired": True}, GuardCode.EXPIRED_DIRECTIVE),
        ({"directive_valid": True, "duplicate": True}, GuardCode.DUPLICATE_TRIGGER),
    ):
        result = evaluate_trigger(facts_for(TriggerKind.EXPLICIT_DIRECTIVE, **changes), AT)
        assert result.status == TriggerStatus.REJECTED and expected in result.guards
