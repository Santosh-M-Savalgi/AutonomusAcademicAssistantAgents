"""Runtime boundaries reject mismatched provenance and illegal lifecycle facts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from packages.domain.adaptation import DiagnosticState, PlanningState
from packages.domain.runtime import (
    SESSION_TRANSITIONS,
    DiagnosticReservation,
    DiagnosticRunSnapshot,
    DiagnosticRunState,
    DurablePlanVersion,
    ExecutionIdentity,
    ExecutionReceipt,
    ExecutionState,
    FrameState,
    LearningPlan,
    LearningSessionSnapshot,
    PlanVersionIdentity,
    RemediationFrameSnapshot,
    ReservationState,
    SessionState,
    SessionTransition,
    SourceIdentity,
    SourceKind,
    TriggerIdentity,
    WorkerAttemptIdentity,
)
from packages.planner import decide

AT = datetime(2026, 10, 5, tzinfo=UTC)


def plan_contract(*, session_id=None, learner_id=None, course_id=None, source_event_id=None):
    event_id = source_event_id or uuid4()
    plan = LearningPlan(
        plan_id=uuid4(), session_id=session_id or uuid4(), learner_id=learner_id or uuid4(),
        course_id=course_id or uuid4(), created_at=AT,
    )
    source = SourceIdentity(kind=SourceKind.EVENT, source_id=event_id)
    trigger = TriggerIdentity(
        learner_id=plan.learner_id, source=source, trigger_kind="SESSION_START",
    )
    identity = PlanVersionIdentity(
        session_id=plan.session_id, trigger_id=trigger.trigger_id, version=1,
    )
    snapshot = PlanningState(
        learner_id=plan.learner_id, course_id=plan.course_id, session_id=plan.session_id,
        plan_version=1, planner_policy_version="planner_v1", session_complete=True,
        source_event_ids=(event_id,),
    )
    return DurablePlanVersion(
        plan=plan, identity=identity, source=source, source_event_id=event_id, session_version=1,
        mastery_policy_version="mastery_v1", snapshot=snapshot,
        decision=decide(snapshot), created_at=AT,
    )


def test_identities_are_deterministic_distinct_and_delivery_independent() -> None:
    source = SourceIdentity(kind=SourceKind.EVENT, source_id=uuid4())
    trigger = TriggerIdentity(learner_id=uuid4(), source=source, trigger_kind="BATCH_COMPLETE")
    identity = PlanVersionIdentity(session_id=uuid4(), trigger_id=trigger.trigger_id, version=1)
    execution = ExecutionIdentity(plan_version_id=identity.plan_version_id)
    job = uuid4()
    attempts = [WorkerAttemptIdentity(job_id=job, attempt=n) for n in (1, 2)]
    values = (source.identity_id, trigger.trigger_id, identity.plan_version_id,
              execution.execution_id, *(attempt.worker_attempt_id for attempt in attempts))
    assert len(set(values)) == len(values)
    assert execution.execution_id == ExecutionIdentity.model_validate_json(
        execution.model_dump_json(),
    ).execution_id
    assert identity.plan_version_id != PlanVersionIdentity(
        session_id=identity.session_id, trigger_id=trigger.trigger_id, version=2,
    ).plan_version_id
    assert source.identity_id != SourceIdentity(
        kind=SourceKind.OUTCOME, source_id=source.source_id,
    ).identity_id


@pytest.mark.parametrize("from_state,to_state", [
    (SessionState.CREATED, SessionState.PLANNING),
    (SessionState.TEACHING, SessionState.CHECKPOINT),
    (SessionState.ASSESSING, SessionState.DIAGNOSING),
    (SessionState.REPLANNING, SessionState.TEACHING),
    (SessionState.REPLANNING, SessionState.ADVANCE),
    (SessionState.TEACHING, SessionState.PAUSED),
    (SessionState.PAUSED, SessionState.PLANNING),
    (SessionState.NEEDS_STATE, SessionState.PLANNING),
    (SessionState.PLANNING, SessionState.PLANNING),
    (SessionState.REPLANNING, SessionState.COMPLETE),
])
def test_spec_progression_pause_resume_and_metadata_transitions(from_state, to_state) -> None:
    transition = SessionTransition(
        session_id=uuid4(), event_id=uuid4(), from_state=from_state, to_state=to_state,
        from_version=2, to_version=3, occurred_at=AT,
    )
    assert transition.to_version == 3


@pytest.mark.parametrize("from_state,to_state", [
    (SessionState.CREATED, SessionState.TEACHING),
    (SessionState.PAUSED, SessionState.TEACHING),
    (SessionState.NEEDS_STATE, SessionState.COMPLETE),
    (SessionState.COMPLETE, SessionState.PLANNING),
    (SessionState.COMPLETE, SessionState.COMPLETE),
])
def test_illegal_and_terminal_transitions_are_rejected(from_state, to_state) -> None:
    with pytest.raises(ValidationError, match="Illegal session transition"):
        SessionTransition(
            session_id=uuid4(), event_id=uuid4(), from_state=from_state, to_state=to_state,
            from_version=1, to_version=2, occurred_at=AT,
        )
    assert SESSION_TRANSITIONS[SessionState.COMPLETE] == frozenset()


def test_snapshot_and_decision_bytes_round_trip_without_mutable_history() -> None:
    original = plan_contract()
    restored = DurablePlanVersion.model_validate_json(original.model_dump_json())
    assert restored.snapshot_bytes == original.snapshot_bytes
    assert restored.decision_bytes == original.decision_bytes
    assert restored.decision_digest == original.decision_digest
    with pytest.raises(ValidationError, match="frozen"):
        original.decision.plan_version = 2
    with pytest.raises(ValidationError, match="frozen"):
        original.snapshot.session_complete = False
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DurablePlanVersion.model_validate({**original.model_dump(), "database": object()})


@pytest.mark.parametrize("change", [
    {"session_version": 0},
    {"frame_id": UUID(int=1)},
    {"graph_version_id": UUID(int=1)},
    {"supersedes_version_id": UUID(int=1)},
    {"created_at": AT - timedelta(seconds=1)},
])
def test_plan_rejects_invalid_versions_and_provenance(change) -> None:
    original = plan_contract()
    with pytest.raises(ValidationError):
        DurablePlanVersion.model_validate({**original.model_dump(), **change})


def test_plan_rejects_cross_learner_decision_and_changed_snapshot_digest() -> None:
    original = plan_contract()
    data = original.model_dump()
    data["decision"]["provenance"]["learner_id"] = uuid4()
    with pytest.raises(ValidationError, match="exact planning snapshot"):
        DurablePlanVersion.model_validate(data)
    data = original.model_dump()
    data["snapshot"]["user_paused"] = True
    with pytest.raises(ValidationError, match="exact planning snapshot"):
        DurablePlanVersion.model_validate(data)


def test_session_versions_and_timestamps_are_explicit() -> None:
    args = dict(
        session_id=uuid4(), learner_id=uuid4(), course_id=uuid4(), state=SessionState.CREATED,
        version=1, last_event_id=uuid4(), created_at=AT, updated_at=AT,
    )
    with pytest.raises(ValidationError, match="timezone-aware"):
        LearningSessionSnapshot(**{**args, "created_at": AT.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="completion timestamp"):
        LearningSessionSnapshot(**{**args, "state": SessionState.COMPLETE})
    with pytest.raises(ValidationError, match="increment the version"):
        SessionTransition(
            session_id=args["session_id"], event_id=uuid4(), from_state=SessionState.CREATED,
            to_state=SessionState.PLANNING, from_version=1, to_version=3, occurred_at=AT,
        )


def test_frame_retains_return_target_and_separates_guard_attempts_from_delivery() -> None:
    frame = RemediationFrameSnapshot(
        frame_id=uuid4(), session_id=uuid4(), graph_version_id=uuid4(), target_concept_id=uuid4(),
        return_to_topic_id=uuid4(), created_by_execution_id=uuid4(),
        depth=1, state=FrameState.ACTIVE,
        version=1, rung=0, strategy="reteach", guard_policy_version="guard_v1", attempt_count=2,
        max_attempts=3, min_progress_delta=0.05, baseline_mastery=0.2, latest_mastery=0.25,
        last_event_id=uuid4(),
    )
    assert frame.progress_delta == pytest.approx(0.05)
    for change in ({"attempt_count": 4}, {"parent_frame_id": frame.frame_id},
                   {"state": FrameState.RETURNED}, {"baseline_mastery": float("nan")}):
        with pytest.raises(ValidationError):
            RemediationFrameSnapshot.model_validate({**frame.model_dump(), **change})
    assert "worker_attempt" not in RemediationFrameSnapshot.model_fields


def test_execution_result_and_original_plan_are_not_worker_retry_identities() -> None:
    plan = plan_contract()
    receipt = ExecutionReceipt(
        identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id), plan=plan,
        state=ExecutionState.COMPLETED, version=1, result_bytes=b'{"complete":true}',
        created_at=AT, completed_at=AT,
    )
    assert receipt.plan.decision_bytes == plan.decision_bytes
    for change in ({"result_bytes": None}, {"completed_at": None},
                   {"child_job_ids": (UUID(int=1), UUID(int=1))}):
        with pytest.raises(ValidationError):
            ExecutionReceipt.model_validate({**receipt.model_dump(), **change})
    assert "worker_attempt" not in ExecutionReceipt.model_fields


def test_block_and_confirmation_are_receipt_admission_constraints() -> None:
    original = plan_contract()
    for outcome in ("BLOCK", "REQUIRE_CONFIRMATION"):
        data = original.model_dump()
        data["decision"]["policy_outcome"] = outcome
        plan = DurablePlanVersion.model_validate(data)
        with pytest.raises(ValidationError, match="blocked decision|confirmation event"):
            ExecutionReceipt(
                identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id),
                plan=plan,
                state=ExecutionState.DISPATCHED, version=1, created_at=AT, child_job_ids=(uuid4(),),
            )


def test_diagnostic_run_has_original_completion_provenance() -> None:
    run = DiagnosticRunSnapshot(
        diagnostic=DiagnosticState(
            diagnostic_run_id=uuid4(), learner_id=uuid4(), course_id=uuid4(),
            graph_version_id=uuid4(),
            diagnostic_policy_version="diagnostic_v1",
        ), session_id=uuid4(), source=SourceIdentity(kind=SourceKind.EVENT, source_id=uuid4()),
        source_event_id=uuid4(), state=DiagnosticRunState.OPEN, version=1, created_at=AT,
    )
    with pytest.raises(ValidationError, match="completion time and event"):
        DiagnosticRunSnapshot.model_validate({
            **run.model_dump(), "state": DiagnosticRunState.COMPLETE,
        })


def test_reservation_budget_and_completion_require_original_source_identities() -> None:
    reservation = DiagnosticReservation(
        reservation_id=uuid4(), diagnostic_run_id=uuid4(), graph_version_id=uuid4(),
        execution_id=uuid4(), question_version_id=uuid4(), target_concept_id=uuid4(), item_budget=2,
        slot=1, state=ReservationState.RESERVED, version=1, reserved_at=AT,
    )
    for change in ({"slot": 3}, {"item_budget": 13}, {"state": ReservationState.ATTEMPTED},
                   {"state": ReservationState.ASSESSED}, {"source_evidence_id": uuid4()}):
        with pytest.raises(ValidationError):
            DiagnosticReservation.model_validate({**reservation.model_dump(), **change})
