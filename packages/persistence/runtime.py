"""Explicit caller-owned Stage 3 writes. No planner, dispatcher or hidden commit."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.adaptation import DiagnosticState
from packages.domain.runtime import (
    TERMINAL_EXECUTION_STATES,
    DiagnosticInferenceLink,
    DiagnosticReservation,
    DiagnosticRunSnapshot,
    DurablePlanVersion,
    ExecutionReceipt,
    ExecutionState,
    FrameAttempt,
    FrameState,
    LearningSessionSnapshot,
    RemediationFrameSnapshot,
    ReservationState,
    SessionState,
    SessionTransition,
)
from packages.domain.runtime_state import (
    AssessmentBatch,
    DirectiveState,
    RuntimeDirective,
    TopicWindow,
    WorkerExecutionLink,
)
from packages.domain.triggers import TriggerEvaluation, TriggerFacts, TriggerStatus
from packages.persistence.models import (
    CurriculumGraphConcept,
    CurriculumGraphMapping,
    CurriculumGraphNode,
    CurriculumGraphVersion,
    Job,
    LearningEventConceptAssociation,
    LearningEventRecord,
    MasteryAttempt,
    MasteryEvidenceRecord,
    StudentIdentity,
)
from packages.persistence.runtime_models import (
    DiagnosticInferenceLinkRecord,
    DiagnosticReservationRecord,
    DiagnosticRunRecord,
    ExecutionReceiptRecord,
    FrameAttemptRecord,
    LearningPlanRecord,
    LearningPlanVersionRecord,
    LearningSessionRecord,
    RemediationFrameRecord,
    SessionTransitionRecord,
)
from packages.persistence.runtime_support_models import (
    AssessmentBatchRecord,
    RuntimeDirectiveRecord,
    RuntimeOperationRecord,
    RuntimeTriggerRecord,
    TopicWindowRecord,
    WorkerExecutionLinkRecord,
)
from packages.planner.triggers import evaluate_trigger


class RuntimeConflictError(ValueError):
    """A logical identity was reused with different immutable content."""


class RuntimeStaleError(ValueError):
    """An operation's expected dependency version is no longer current."""


class RuntimeValidationError(ValueError):
    """Missing, illegal or incompatible authoritative runtime state."""


def canonical_request(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


async def lock_runtime_learner(session: AsyncSession, learner_id: UUID) -> None:
    if not session.in_transaction():
        raise RuntimeValidationError("An explicit caller transaction is required")
    identity = await session.scalar(select(StudentIdentity).where(
        StudentIdentity.id == learner_id,
    ).with_for_update().execution_options(populate_existing=True))
    if identity is None:
        raise RuntimeValidationError("Learner identity does not exist")


async def locked_session(
    session: AsyncSession, learner_id: UUID, session_id: UUID,
) -> LearningSessionRecord:
    await lock_runtime_learner(session, learner_id)
    row = await session.scalar(select(LearningSessionRecord).where(
        LearningSessionRecord.id == session_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None or row.learner_identity_id != learner_id:
        raise RuntimeValidationError("Session is missing or belongs to another learner")
    return row


async def validate_runtime_event(
    session: AsyncSession, event_id: UUID, owner: LearningSessionRecord,
) -> LearningEventRecord:
    row = await session.scalar(select(LearningEventRecord).where(
        LearningEventRecord.event_id == event_id,
    ).execution_options(populate_existing=True))
    if row is None or row.learner_identity_id not in (None, owner.learner_identity_id) or (
        row.course_id not in (None, owner.course_id)
    ):
        raise RuntimeValidationError("Runtime event scope is missing or conflicting")
    return row


def session_snapshot(row: LearningSessionRecord) -> LearningSessionSnapshot:
    return LearningSessionSnapshot(
        session_id=row.id, learner_id=row.learner_identity_id, course_id=row.course_id,
        state=SessionState(row.state), version=row.version, graph_version_id=row.graph_version_id,
        current_topic_id=row.current_topic_id, current_plan_version_id=row.current_plan_version_id,
        active_frame_id=row.active_frame_id, last_event_id=row.last_event_id,
        created_at=row.created_at, updated_at=row.updated_at, completed_at=row.completed_at,
    )


async def get_learning_session(
    session: AsyncSession, learner_id: UUID, session_id: UUID,
) -> LearningSessionSnapshot | None:
    row = await session.scalar(select(LearningSessionRecord).where(
        LearningSessionRecord.id == session_id,
        LearningSessionRecord.learner_identity_id == learner_id,
    ).execution_options(populate_existing=True))
    return None if row is None else session_snapshot(row)


async def _prior_result(
    session: AsyncSession, learner_id: UUID, kind: str, scope_id: UUID,
    source_id: UUID, request: bytes,
) -> bytes | None:
    row = await session.get(RuntimeOperationRecord, (kind, scope_id, source_id),
                            populate_existing=True)
    if row is None:
        return None
    if row.learner_id != learner_id or row.request_bytes != request:
        raise RuntimeConflictError(f"Conflicting {kind} retry")
    return row.result_bytes


async def _record_result(
    session: AsyncSession, learner_id: UUID, kind: str, scope_id: UUID,
    source_id: UUID, request: bytes, result: bytes,
) -> None:
    # Called only after the explicit operation validates and performs its own write.
    session.add(RuntimeOperationRecord(
        kind=kind, scope_id=scope_id, source_id=source_id, learner_id=learner_id,
        request_bytes=request, result_bytes=result,
    ))
    await session.flush()


def _version(observed: int, expected: int) -> None:
    if observed != expected:
        raise RuntimeStaleError(f"Expected version {expected}; current version is {observed}")


async def _graph_position(
    session: AsyncSession, owner: LearningSessionRecord,
    graph_id: UUID | None, topic_id: UUID | None,
) -> None:
    if graph_id is None:
        if topic_id is not None:
            raise RuntimeValidationError("Topic position requires a graph")
        return
    graph = await session.get(CurriculumGraphVersion, graph_id, populate_existing=True)
    if graph is None or graph.course_id != owner.course_id or graph.status != "PUBLISHED":
        raise RuntimeValidationError("Position requires a published graph for this course")
    if topic_id is not None and await session.scalar(select(CurriculumGraphNode.id).where(
        CurriculumGraphNode.graph_id == graph_id, CurriculumGraphNode.stable_node_id == topic_id,
        CurriculumGraphNode.node_type == "TOPIC",
    )) is None:
        raise RuntimeValidationError("Position topic is absent from the graph")


async def create_learning_session(
    session: AsyncSession, value: LearningSessionSnapshot,
) -> LearningSessionSnapshot:
    await lock_runtime_learner(session, value.learner_id)
    request = value.canonical_bytes()
    prior = await _prior_result(session, value.learner_id, "session-create",
                                value.session_id, value.session_id, request)
    if prior is not None:
        return LearningSessionSnapshot.model_validate_json(prior)
    if value.version != 1 or value.state != SessionState.CREATED or (
        value.current_plan_version_id is not None or value.active_frame_id is not None
    ):
        raise RuntimeValidationError("A new session starts CREATED at version one without heads")
    existing = await session.get(LearningSessionRecord, value.session_id, populate_existing=True)
    if existing is not None:
        raise RuntimeConflictError("Session already exists without this creation receipt")
    row = LearningSessionRecord(
        id=value.session_id, learner_identity_id=value.learner_id, course_id=value.course_id,
        state=value.state, version=value.version, graph_version_id=value.graph_version_id,
        current_topic_id=value.current_topic_id, last_event_id=value.last_event_id,
        created_at=value.created_at, updated_at=value.updated_at,
    )
    await validate_runtime_event(session, value.last_event_id, row)
    await _graph_position(session, row, value.graph_version_id, value.current_topic_id)
    session.add(row)
    await session.flush()
    await _record_result(session, value.learner_id, "session-create", value.session_id,
                         value.session_id, request, value.canonical_bytes())
    return value


async def transition_learning_session(
    session: AsyncSession, learner_id: UUID, transition: SessionTransition,
    *, graph_version_id: UUID | None = None, topic_id: UUID | None = None,
    change_position: bool = False,
) -> LearningSessionSnapshot:
    owner = await locked_session(session, learner_id, transition.session_id)
    request = canonical_request({
        "transition": transition.model_dump(mode="json"), "change_position": change_position,
        "graph_id": str(graph_version_id) if graph_version_id else None,
        "topic_id": str(topic_id) if topic_id else None,
    })
    prior = await _prior_result(session, learner_id, "session-transition", owner.id,
                                transition.event_id, request)
    if prior is not None:
        return LearningSessionSnapshot.model_validate_json(prior)
    _version(owner.version, transition.from_version)
    if owner.state != transition.from_state:
        raise RuntimeStaleError("Session source state changed")
    await validate_runtime_event(session, transition.event_id, owner)
    if transition.plan_version_id is not None:
        plan = await session.get(
            LearningPlanVersionRecord, transition.plan_version_id, populate_existing=True,
        )
        if plan is None or plan.session_id != owner.id or owner.current_plan_version_id != plan.id:
            raise RuntimeStaleError("Transition plan is not the current authorized session head")
    if transition.execution_id is not None:
        receipt = await session.get(
            ExecutionReceiptRecord, transition.execution_id, populate_existing=True,
        )
        if receipt is None or receipt.session_id != owner.id or (
            receipt.state != ExecutionState.COMPLETED
        ):
            raise RuntimeValidationError(
                "Successful session transition requires a completed execution",
            )
        if transition.plan_version_id != receipt.plan_version_id:
            raise RuntimeConflictError("Transition execution and plan identities conflict")
    if transition.occurred_at < owner.updated_at:
        raise RuntimeStaleError("Session transition precedes its current state")
    if change_position:
        await _graph_position(session, owner, graph_version_id, topic_id)
        if owner.active_frame_id is not None:
            raise RuntimeValidationError("Position cannot replace an active frame's saved target")
        owner.graph_version_id, owner.current_topic_id = graph_version_id, topic_id
    session.add(SessionTransitionRecord(**transition.model_dump()))
    owner.state, owner.version = transition.to_state, transition.to_version
    owner.last_event_id, owner.updated_at = transition.event_id, transition.occurred_at
    owner.completed_at = (transition.occurred_at if transition.to_state == SessionState.COMPLETE
                          else None)
    await session.flush()
    result = session_snapshot(owner)
    await _record_result(session, learner_id, "session-transition", owner.id,
                         transition.event_id, request, result.canonical_bytes())
    return result


async def store_plan_version(
    session: AsyncSession, value: DurablePlanVersion,
) -> DurablePlanVersion:
    """Store a supplied detached version only; never allocate, publish or move a head."""
    owner = await locked_session(session, value.plan.learner_id, value.plan.session_id)
    request = value.model_dump_json().encode()
    prior = await _prior_result(session, owner.learner_identity_id, "plan-version",
                                value.plan.plan_id,
                                value.identity.plan_version_id, request)
    if prior is not None:
        return DurablePlanVersion.model_validate_json(prior)
    _version(owner.version, value.session_version)
    if value.plan.course_id != owner.course_id or owner.state == SessionState.COMPLETE:
        raise RuntimeStaleError("Plan scope/session is no longer available")
    if value.graph_version_id is not None and value.graph_version_id != owner.graph_version_id:
        raise RuntimeStaleError("Plan graph does not match the session graph")
    await validate_runtime_event(session, value.source_event_id, owner)
    if value.frame_id is not None:
        frame = await session.get(RemediationFrameRecord, value.frame_id, populate_existing=True)
        if frame is None or owner.active_frame_id != frame.id or (
            frame.version != value.frame_version
        ):
            raise RuntimeStaleError("Plan remediation frame changed")
    existing = await session.get(LearningPlanRecord, value.plan.plan_id, populate_existing=True)
    if existing is None:
        if value.identity.version != 1:
            raise RuntimeValidationError("A plan aggregate starts at version one")
        session.add(LearningPlanRecord(id=value.plan.plan_id, session_id=owner.id,
                                       created_at=value.plan.created_at))
        await session.flush()
    elif existing.session_id != owner.id or existing.created_at != value.plan.created_at:
        raise RuntimeConflictError("Immutable plan aggregate conflicts")
    versions = (await session.scalars(select(LearningPlanVersionRecord).where(
        LearningPlanVersionRecord.plan_id == value.plan.plan_id,
    ).order_by(LearningPlanVersionRecord.version))).all()
    if value.identity.version != len(versions) + 1 or (
        value.supersedes_version_id != (versions[-1].id if versions else None)
    ):
        raise RuntimeStaleError("Plan predecessor is no longer current")
    session.add(LearningPlanVersionRecord(
        id=value.identity.plan_version_id, plan_id=value.plan.plan_id, session_id=owner.id,
        version=value.identity.version, trigger_id=value.identity.trigger_id,
        source_kind=value.source.kind, source_id=value.source.source_id,
        source_event_id=value.source_event_id, session_version=value.session_version,
        frame_id=value.frame_id, frame_version=value.frame_version,
        curriculum_revision_id=value.curriculum_revision_id,
        graph_version_id=value.graph_version_id,
        snapshot_bytes=value.snapshot_bytes, snapshot_digest=value.snapshot_digest,
        decision_bytes=value.decision_bytes, decision_digest=value.decision_digest,
        action=value.decision.action, target_id=value.decision.target_id,
        policy_outcome=value.decision.policy_outcome,
        mastery_policy_version=value.mastery_policy_version,
        planner_policy_version=value.decision.planner_policy_version,
        schema_version=value.schema_version,
        supersedes_version_id=value.supersedes_version_id,
        source_snapshot_fingerprint=value.source_snapshot_fingerprint,
        created_at=value.created_at,
    ))
    await session.flush()
    await _record_result(session, owner.learner_identity_id, "plan-version", value.plan.plan_id,
                         value.identity.plan_version_id, request, request)
    return value


async def get_plan_version(
    session: AsyncSession, learner_id: UUID, version_id: UUID,
) -> DurablePlanVersion | None:
    receipt = await session.scalar(select(RuntimeOperationRecord).where(
        RuntimeOperationRecord.kind == "plan-version",
        RuntimeOperationRecord.source_id == version_id,
        RuntimeOperationRecord.learner_id == learner_id,
    ).execution_options(populate_existing=True))
    return None if receipt is None else DurablePlanVersion.model_validate_json(receipt.result_bytes)


def _frame_values(value: RemediationFrameSnapshot) -> dict[str, Any]:
    return {**value.model_dump(exclude={"frame_id"}), "id": value.frame_id}


async def create_remediation_frame(
    session: AsyncSession, learner_id: UUID, value: RemediationFrameSnapshot,
    *, expected_session_version: int, created_at: datetime,
) -> RemediationFrameSnapshot:
    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "session_version": expected_session_version,
                                 "created_at": created_at.isoformat()})
    prior = await _prior_result(session, learner_id, "frame-create", value.frame_id,
                                value.created_by_execution_id, request)
    if prior is not None:
        return RemediationFrameSnapshot.model_validate_json(prior)
    _version(owner.version, expected_session_version)
    if value.version != 1 or value.state != FrameState.ACTIVE or value.attempt_count != 0:
        raise RuntimeValidationError("New frame must be active at version one without attempts")
    if owner.graph_version_id != value.graph_version_id:
        raise RuntimeStaleError("Frame graph changed")
    if value.parent_frame_id != owner.active_frame_id:
        raise RuntimeStaleError("Frame parent must match the current stack head")
    if value.parent_frame_id is not None:
        parent = await session.get(
            RemediationFrameRecord, value.parent_frame_id, populate_existing=True,
        )
        if parent is None or value.depth != parent.depth + 1:
            raise RuntimeValidationError("Frame stack depth is incompatible")
    receipt = await session.get(ExecutionReceiptRecord, value.created_by_execution_id,
                                populate_existing=True)
    if receipt is None or receipt.session_id != owner.id:
        raise RuntimeValidationError("Frame creation execution is missing or incompatible")
    await validate_runtime_event(session, value.last_event_id, owner)
    session.add(RemediationFrameRecord(
        **_frame_values(value), created_at=created_at, updated_at=created_at,
    ))
    await session.flush()
    await _record_result(session, learner_id, "frame-create", value.frame_id,
                         value.created_by_execution_id, request, value.canonical_bytes())
    return value


async def update_remediation_frame(
    session: AsyncSession, learner_id: UUID, value: RemediationFrameSnapshot,
    *, expected_version: int, expected_session_version: int, updated_at: datetime,
) -> RemediationFrameSnapshot:
    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "expected": expected_version,
                                 "session_version": expected_session_version,
                                 "updated_at": updated_at.isoformat()})
    prior = await _prior_result(session, learner_id, "frame-update", value.frame_id,
                                value.last_event_id, request)
    if prior is not None:
        return RemediationFrameSnapshot.model_validate_json(prior)
    _version(owner.version, expected_session_version)
    frame = await session.scalar(select(RemediationFrameRecord).where(
        RemediationFrameRecord.id == value.frame_id,
    ).with_for_update().execution_options(populate_existing=True))
    if frame is None or frame.session_id != owner.id:
        raise RuntimeValidationError("Frame is missing or belongs to another session")
    _version(frame.version, expected_version)
    if value.version != expected_version + 1 or frame.state == FrameState.RETURNED:
        raise RuntimeStaleError("Frame version/state changed")
    immutable = ("session_id", "graph_version_id", "target_concept_id", "return_to_topic_id",
                 "parent_frame_id", "depth", "created_by_execution_id", "guard_policy_version",
                 "max_attempts", "min_progress_delta")
    if any(getattr(frame, field) != getattr(value, field) for field in immutable):
        raise RuntimeConflictError("Immutable frame provenance conflicts")
    await validate_runtime_event(session, value.last_event_id, owner)
    for field in ("state", "version", "rung", "strategy", "attempt_count", "baseline_mastery",
                  "latest_mastery", "last_event_id", "returned_by_execution_id", "returned_at"):
        setattr(frame, field, getattr(value, field))
    frame.updated_at = updated_at
    await session.flush()
    await _record_result(session, learner_id, "frame-update", value.frame_id,
                         value.last_event_id, request, value.canonical_bytes())
    return value


async def record_frame_attempt(
    session: AsyncSession, learner_id: UUID, session_id: UUID, value: FrameAttempt,
    *, expected_frame_version: int,
) -> FrameAttempt:
    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "expected": expected_frame_version})
    prior = await _prior_result(session, learner_id, "frame-attempt", value.frame_id,
                                value.source_attempt_id, request)
    if prior is not None:
        return FrameAttempt.model_validate_json(prior)
    frame = await session.scalar(select(RemediationFrameRecord).where(
        RemediationFrameRecord.id == value.frame_id,
    ).with_for_update().execution_options(populate_existing=True))
    attempt = await session.get(MasteryAttempt, value.source_attempt_id, populate_existing=True)
    if frame is None or frame.session_id != owner.id or frame.state != FrameState.ACTIVE:
        raise RuntimeValidationError("Attempt requires an active session frame")
    _version(frame.version, expected_frame_version)
    await validate_runtime_event(session, value.event_id, owner)
    if attempt is None or attempt.learner_identity_id != learner_id or (
        attempt.course_id != owner.course_id
    ):
        raise RuntimeValidationError("Frame attempt source context conflicts")
    associations = (await session.scalars(select(LearningEventConceptAssociation).where(
        LearningEventConceptAssociation.event_id == value.event_id,
        LearningEventConceptAssociation.source_attempt_id == value.source_attempt_id,
        LearningEventConceptAssociation.stable_concept_id == frame.target_concept_id,
        LearningEventConceptAssociation.concept_impact == "AFFECTS_CONCEPT",
    ))).all()
    if not associations or value.rung != frame.rung:
        raise RuntimeValidationError("Frame attempt requires matching concept-impact provenance")
    session.add(FrameAttemptRecord(**value.model_dump()))
    await session.flush()
    await _record_result(session, learner_id, "frame-attempt", value.frame_id,
                         value.source_attempt_id, request, value.canonical_bytes())
    return value


async def get_remediation_frame(
    session: AsyncSession, learner_id: UUID, session_id: UUID, frame_id: UUID,
) -> RemediationFrameSnapshot | None:
    owner = await get_learning_session(session, learner_id, session_id)
    if owner is None:
        return None
    row = await session.get(RemediationFrameRecord, frame_id, populate_existing=True)
    if row is None or row.session_id != session_id:
        return None
    return RemediationFrameSnapshot.model_validate({
        "frame_id": row.id,
        **{field: getattr(row, field) for field in RemediationFrameSnapshot.model_fields
           if field != "frame_id"},
    })


async def get_execution_receipt(
    session: AsyncSession, learner_id: UUID, execution_id: UUID,
) -> ExecutionReceipt | None:
    rows = (await session.scalars(select(RuntimeOperationRecord).where(
        RuntimeOperationRecord.kind == "execution-receipt",
        RuntimeOperationRecord.scope_id == execution_id,
        RuntimeOperationRecord.learner_id == learner_id,
    ).execution_options(populate_existing=True))).all()
    if not rows:
        return None
    values = [ExecutionReceipt.model_validate_json(row.result_bytes) for row in rows]
    result = max(values, key=lambda value: value.version)
    row = await session.get(ExecutionReceiptRecord, execution_id, populate_existing=True)
    if row is None or row.version != result.version or row.state != result.state:
        raise RuntimeStaleError("Execution head does not match its durable operation result")
    return result


async def list_diagnostic_reservations(
    session: AsyncSession, learner_id: UUID, session_id: UUID, run_id: UUID,
) -> tuple[DiagnosticReservation, ...]:
    owner = await get_learning_session(session, learner_id, session_id)
    if owner is None:
        return ()
    rows = (await session.scalars(select(DiagnosticReservationRecord).where(
        DiagnosticReservationRecord.session_id == session_id,
        DiagnosticReservationRecord.diagnostic_run_id == run_id,
    ).order_by(DiagnosticReservationRecord.slot)
      .execution_options(populate_existing=True))).all()
    return tuple(reservation_snapshot(row) for row in rows)


async def list_runtime_directives(
    session: AsyncSession, learner_id: UUID, session_id: UUID,
) -> tuple[RuntimeDirective, ...]:
    owner = await get_learning_session(session, learner_id, session_id)
    if owner is None:
        return ()
    rows = (await session.scalars(select(RuntimeDirectiveRecord).where(
        RuntimeDirectiveRecord.session_id == session_id,
    ).order_by(RuntimeDirectiveRecord.id).execution_options(populate_existing=True))).all()
    return tuple(RuntimeDirective.model_validate_json(row.value_bytes) for row in rows)


async def record_execution_receipt(
    session: AsyncSession, value: ExecutionReceipt,
    *, event_id: UUID, expected_version: int | None = None,
    expected_session_version: int | None = None,
) -> ExecutionReceipt:
    owner = await locked_session(session, value.plan.plan.learner_id, value.plan.plan.session_id)
    execution_id = value.identity.execution_id
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "expected": expected_version, "event_id": str(event_id),
                                 "session_version": expected_session_version})
    prior = await _prior_result(session, owner.learner_identity_id, "execution-receipt",
                                execution_id, event_id, request)
    if prior is not None:
        return ExecutionReceipt.model_validate_json(prior)
    _version(owner.version, expected_session_version or value.plan.session_version)
    stored_plan = await session.get(LearningPlanVersionRecord, value.identity.plan_version_id,
                                    populate_existing=True)
    if stored_plan is None or stored_plan.decision_bytes != value.plan.decision_bytes or (
        stored_plan.snapshot_bytes != value.plan.snapshot_bytes
    ):
        raise RuntimeConflictError("Execution must retain the exact stored plan")
    await validate_runtime_event(session, event_id, owner)
    row = await session.get(ExecutionReceiptRecord, execution_id, populate_existing=True)
    if row is None:
        if expected_version is not None or value.version != 1:
            raise RuntimeStaleError("New execution receipt requires version one")
        _version(owner.version, value.plan.session_version)
        row = ExecutionReceiptRecord(
            id=execution_id, plan_version_id=value.identity.plan_version_id, session_id=owner.id,
            session_version=value.plan.session_version, action=value.plan.decision.action,
            target_id=value.plan.decision.target_id,
            policy_outcome=value.plan.decision.policy_outcome,
            state=value.state, version=value.version,
            confirmation_event_id=value.confirmation_event_id,
            child_job_ids=[str(item) for item in value.child_job_ids],
            emitted_event_ids=[str(item) for item in value.emitted_event_ids],
            request_bytes=value.request_bytes, request_digest=value.request_digest,
            result_bytes=value.result_bytes, result_digest=value.result_digest,
            receipt_digest=value.receipt_fingerprint,
            created_at=value.created_at,
            completed_at=value.completed_at,
        )
        session.add(row)
    else:
        if expected_version is None:
            raise RuntimeConflictError("Execution already exists; an update needs its version")
        _version(row.version, expected_version)
        if row.request_bytes is not None and row.request_bytes != value.request_bytes:
            raise RuntimeConflictError("Execution identity was reused with changed immutable input")
        if value.version != expected_version + 1 or (
            ExecutionState(row.state) in TERMINAL_EXECUTION_STATES
        ):
            raise RuntimeStaleError("Terminal execution result cannot be overwritten")
        if row.created_at != value.created_at or (
            row.plan_version_id != value.identity.plan_version_id
        ):
            raise RuntimeConflictError("Immutable execution identity conflicts")
    for child in value.child_job_ids:
        if await session.get(Job, child, populate_existing=True) is None:
            raise RuntimeValidationError("Execution child job is not persisted")
    for emitted in value.emitted_event_ids:
        await validate_runtime_event(session, emitted, owner)
    row.state, row.version = value.state, value.version
    row.confirmation_event_id = value.confirmation_event_id
    row.child_job_ids = [str(item) for item in value.child_job_ids]
    row.emitted_event_ids = [str(item) for item in value.emitted_event_ids]
    row.request_bytes, row.request_digest = value.request_bytes, value.request_digest
    row.result_bytes, row.completed_at = value.result_bytes, value.completed_at
    row.result_digest, row.receipt_digest = value.result_digest, value.receipt_fingerprint
    await session.flush()
    result = value.model_dump_json().encode()
    await _record_result(session, owner.learner_identity_id, "execution-receipt", execution_id,
                         event_id, request, result)
    return value


async def create_diagnostic_run(
    session: AsyncSession, value: DiagnosticRunSnapshot,
) -> DiagnosticRunSnapshot:
    owner = await locked_session(session, value.diagnostic.learner_id, value.session_id)
    request = value.canonical_bytes()
    run_id = value.diagnostic.diagnostic_run_id
    prior = await _prior_result(session, owner.learner_identity_id, "diagnostic-create",
                                run_id, value.source.identity_id, request)
    if prior is not None:
        return DiagnosticRunSnapshot.model_validate_json(prior)
    if value.version != 1 or value.state != "OPEN" or (
        value.diagnostic.course_id != owner.course_id
        or value.diagnostic.graph_version_id != owner.graph_version_id
        or value.diagnostic.selected_concept_ids or value.diagnostic.attempted_question_version_ids
        or value.diagnostic.diagnostic_assessed_concept_ids
        or value.diagnostic.remaining_item_budget != value.diagnostic.item_budget
    ):
        raise RuntimeValidationError("New diagnostic run requires matching empty source state")
    await validate_runtime_event(session, value.source_event_id, owner)
    session.add(DiagnosticRunRecord(
        id=run_id, session_id=owner.id, learner_identity_id=owner.learner_identity_id,
        course_id=owner.course_id, graph_version_id=value.diagnostic.graph_version_id,
        diagnostic_policy_version=value.diagnostic.diagnostic_policy_version,
        item_budget=value.diagnostic.item_budget, source_kind=value.source.kind,
        source_id=value.source.source_id, source_event_id=value.source_event_id,
        state=value.state, version=1, created_at=value.created_at,
    ))
    await session.flush()
    await _record_result(session, owner.learner_identity_id, "diagnostic-create",
                         run_id, value.source.identity_id, request, request)
    return value


def reservation_snapshot(row: DiagnosticReservationRecord) -> DiagnosticReservation:
    return DiagnosticReservation(
        reservation_id=row.id, diagnostic_run_id=row.diagnostic_run_id,
        graph_version_id=row.graph_version_id, execution_id=row.execution_id,
        question_version_id=row.question_version_id, target_concept_id=row.target_concept_id,
        item_budget=row.item_budget, slot=row.slot,
        state=ReservationState(row.state), version=row.version,
        source_attempt_id=row.source_attempt_id, source_evidence_id=row.source_evidence_id,
        completion_event_id=row.completion_event_id,
        assessed_concept_ids=tuple(UUID(item) for item in row.assessed_concept_ids),
        reserved_at=row.reserved_at, attempted_at=row.attempted_at, assessed_at=row.assessed_at,
    )


async def reserve_diagnostic_question(
    session: AsyncSession, learner_id: UUID, session_id: UUID, *,
    run_id: UUID, reservation_id: UUID,
    execution_id: UUID, question_version_id: UUID, target_concept_id: UUID,
    expected_run_version: int, reserved_at: datetime,
) -> DiagnosticReservation:
    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({"run_id": str(run_id), "reservation_id": str(reservation_id),
                                 "execution_id": str(execution_id),
                                 "question": str(question_version_id),
                                 "concept": str(target_concept_id),
                                 "expected": expected_run_version,
                                 "reserved_at": reserved_at.isoformat()})
    prior = await _prior_result(session, learner_id, "diagnostic-reserve",
                                run_id, question_version_id, request)
    if prior is not None:
        return DiagnosticReservation.model_validate_json(prior)
    run = await session.scalar(select(DiagnosticRunRecord).where(
        DiagnosticRunRecord.id == run_id,
    ).with_for_update().execution_options(populate_existing=True))
    if run is None or run.session_id != owner.id or run.state != "OPEN":
        raise RuntimeValidationError("Reservation requires an open session diagnostic run")
    _version(run.version, expected_run_version)
    if owner.graph_version_id != run.graph_version_id:
        raise RuntimeStaleError("Diagnostic graph no longer matches the session")
    rows = (await session.scalars(select(DiagnosticReservationRecord).where(
        DiagnosticReservationRecord.diagnostic_run_id == run_id,
    ).order_by(DiagnosticReservationRecord.slot).execution_options(populate_existing=True))).all()
    if len(rows) >= run.item_budget:
        raise RuntimeValidationError("Diagnostic reservation capacity exhausted")
    if any(row.question_version_id == question_version_id for row in rows):
        raise RuntimeConflictError("Question is already reserved under another request")
    value = DiagnosticReservation(
        reservation_id=reservation_id, diagnostic_run_id=run_id,
        graph_version_id=run.graph_version_id, execution_id=execution_id,
        question_version_id=question_version_id, target_concept_id=target_concept_id,
        item_budget=run.item_budget, slot=len(rows) + 1, state=ReservationState.RESERVED,
        version=1, reserved_at=reserved_at,
    )
    session.add(DiagnosticReservationRecord(
        **value.model_dump(exclude={"reservation_id", "assessed_concept_ids"}), id=reservation_id,
        session_id=owner.id, assessed_concept_ids=[],
    ))
    await session.flush()
    await _record_result(session, learner_id, "diagnostic-reserve", run_id, question_version_id,
                         request, value.canonical_bytes())
    return value


async def mark_diagnostic_reservation_attempted(
    session: AsyncSession, learner_id: UUID, session_id: UUID,
    reservation_id: UUID, *, source_attempt_id: UUID, event_id: UUID,
    expected_version: int, attempted_at: datetime,
) -> DiagnosticReservation:
    """Advance a reservation to ATTEMPTED without applying learner evidence."""

    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({
        "reservation_id": str(reservation_id),
        "source_attempt_id": str(source_attempt_id),
        "event_id": str(event_id),
        "expected": expected_version,
        "attempted_at": attempted_at.isoformat(),
    })
    prior = await _prior_result(
        session, learner_id, "diagnostic-attempt", reservation_id,
        source_attempt_id, request,
    )
    if prior is not None:
        return DiagnosticReservation.model_validate_json(prior)
    row = await session.scalar(select(DiagnosticReservationRecord).where(
        DiagnosticReservationRecord.id == reservation_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None or row.session_id != owner.id:
        raise RuntimeValidationError("Diagnostic reservation is missing")
    _version(row.version, expected_version)
    if row.state != ReservationState.RESERVED.value:
        raise RuntimeStaleError("Diagnostic reservation is no longer reservable")
    source_attempt = await session.get(MasteryAttempt, source_attempt_id, populate_existing=True)
    if source_attempt is None or source_attempt.learner_identity_id != learner_id:
        raise RuntimeValidationError("Diagnostic source attempt is missing or out of scope")
    await validate_runtime_event(session, event_id, owner)
    value = reservation_snapshot(row).model_copy(update={
        "state": ReservationState.ATTEMPTED,
        "version": expected_version + 1,
        "source_attempt_id": source_attempt_id,
        "attempted_at": attempted_at,
    })
    row.state = value.state
    row.version = value.version
    row.source_attempt_id = source_attempt_id
    row.attempted_at = attempted_at
    await session.flush()
    await _record_result(
        session, learner_id, "diagnostic-attempt", reservation_id,
        source_attempt_id, request, value.canonical_bytes(),
    )
    return value


async def acknowledge_diagnostic_reservation(
    session: AsyncSession, learner_id: UUID, session_id: UUID, value: DiagnosticReservation,
    *, expected_version: int, event_id: UUID,
) -> DiagnosticReservation:
    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "expected": expected_version})
    prior = await _prior_result(session, learner_id, "diagnostic-ack",
                                value.reservation_id, event_id, request)
    if prior is not None:
        return DiagnosticReservation.model_validate_json(prior)
    row = await session.get(
        DiagnosticReservationRecord, value.reservation_id, populate_existing=True,
    )
    if row is None or row.session_id != owner.id:
        raise RuntimeValidationError("Diagnostic reservation is missing")
    _version(row.version, expected_version)
    if row.state == "ASSESSED" or value.version != expected_version + 1:
        raise RuntimeStaleError("Diagnostic reservation is already terminal or changed")
    before = reservation_snapshot(row)
    immutable = ("reservation_id", "diagnostic_run_id", "graph_version_id", "execution_id",
                 "question_version_id", "target_concept_id", "item_budget", "slot", "reserved_at")
    if any(getattr(before, field) != getattr(value, field) for field in immutable):
        raise RuntimeConflictError("Reservation identity cannot change")
    await validate_runtime_event(session, event_id, owner)
    for field in ("state", "version", "source_attempt_id", "source_evidence_id",
                  "completion_event_id",
                  "attempted_at", "assessed_at"):
        setattr(row, field, getattr(value, field))
    row.assessed_concept_ids = [str(item) for item in value.assessed_concept_ids]
    await session.flush()
    await _record_result(session, learner_id, "diagnostic-ack", value.reservation_id, event_id,
                         request, value.canonical_bytes())
    return value


async def link_diagnostic_inference(
    session: AsyncSession, learner_id: UUID, session_id: UUID, value: DiagnosticInferenceLink,
) -> DiagnosticInferenceLink:
    owner = await locked_session(session, learner_id, session_id)
    request = value.canonical_bytes()
    prior = await _prior_result(session, learner_id, "diagnostic-inference", value.reservation_id,
                                value.evidence_id, request)
    if prior is not None:
        return DiagnosticInferenceLink.model_validate_json(prior)
    row = await session.get(
        DiagnosticReservationRecord, value.reservation_id, populate_existing=True,
    )
    evidence = await session.get(MasteryEvidenceRecord, value.evidence_id, populate_existing=True)
    if row is None or row.session_id != owner.id or evidence is None or (
        evidence.diagnostic_provenance != value.provenance.model_dump(mode="json")
    ):
        raise RuntimeValidationError("Diagnostic inference must retain original source provenance")
    session.add(DiagnosticInferenceLinkRecord(
        evidence_id=value.evidence_id, reservation_id=value.reservation_id,
        target_concept_id=value.provenance.target_prerequisite_concept_id,
    ))
    await session.flush()
    await _record_result(session, learner_id, "diagnostic-inference", value.reservation_id,
                         value.evidence_id, request, request)
    return value


async def complete_diagnostic_run(
    session: AsyncSession, learner_id: UUID, session_id: UUID, run_id: UUID,
    *, expected_version: int, event_id: UUID, completed_at: datetime, cancelled: bool = False,
) -> DiagnosticRunSnapshot:
    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({"expected": expected_version, "event": str(event_id),
                                 "completed_at": completed_at.isoformat(), "cancelled": cancelled})
    prior = await _prior_result(session, learner_id, "diagnostic-complete",
                                run_id, event_id, request)
    if prior is not None:
        return DiagnosticRunSnapshot.model_validate_json(prior)
    run = await session.get(DiagnosticRunRecord, run_id, populate_existing=True)
    if run is None or run.session_id != owner.id:
        raise RuntimeValidationError("Diagnostic run is missing")
    _version(run.version, expected_version)
    if run.state != "OPEN":
        raise RuntimeStaleError("Diagnostic run is already terminal")
    reservations = (await session.scalars(select(DiagnosticReservationRecord).where(
        DiagnosticReservationRecord.diagnostic_run_id == run_id,
    ).order_by(DiagnosticReservationRecord.slot).execution_options(populate_existing=True))).all()
    if not cancelled and any(row.state != "ASSESSED" for row in reservations):
        raise RuntimeValidationError("Diagnostic completion cannot discard pending reservations")
    await validate_runtime_event(session, event_id, owner)
    from packages.domain.runtime import DiagnosticRunState, SourceIdentity, SourceKind

    state = DiagnosticState(
        diagnostic_run_id=run_id, learner_id=learner_id, course_id=owner.course_id,
        graph_version_id=run.graph_version_id,
        diagnostic_policy_version=run.diagnostic_policy_version,
        item_budget=run.item_budget, remaining_item_budget=run.item_budget - len(reservations),
        selected_concept_ids=tuple(sorted(
            {row.target_concept_id for row in reservations}, key=lambda x: x.bytes,
        )),
        attempted_question_version_ids=tuple(row.question_version_id for row in reservations
                                             if row.source_attempt_id is not None),
        diagnostic_assessed_concept_ids=tuple(sorted(
            {UUID(item) for row in reservations for item in row.assessed_concept_ids},
            key=lambda x: x.bytes,
        )),
    )
    result = DiagnosticRunSnapshot(
        diagnostic=state, session_id=owner.id,
        source=SourceIdentity(kind=SourceKind(run.source_kind), source_id=run.source_id),
        source_event_id=run.source_event_id,
        state=DiagnosticRunState.CANCELLED if cancelled else DiagnosticRunState.COMPLETE,
        version=run.version + 1, created_at=run.created_at,
        completed_at=completed_at, completion_event_id=event_id,
    )
    run.state, run.version = result.state, result.version
    run.completed_at, run.completion_event_id = completed_at, event_id
    await session.flush()
    await _record_result(session, learner_id, "diagnostic-complete", run_id, event_id,
                         request, result.canonical_bytes())
    return result


async def record_worker_execution_link(
    session: AsyncSession, learner_id: UUID, session_id: UUID, value: WorkerExecutionLink,
) -> WorkerExecutionLink:
    await locked_session(session, learner_id, session_id)
    request = value.canonical_bytes()
    prior = await _prior_result(session, learner_id, "worker-link", value.execution_id,
                                value.worker.worker_attempt_id, request)
    if prior is not None:
        return WorkerExecutionLink.model_validate_json(prior)
    row = await session.get(ExecutionReceiptRecord, value.execution_id, populate_existing=True)
    job = await session.get(Job, value.worker.job_id, populate_existing=True)
    if row is None or row.session_id != session_id or job is None or (
        value.worker.attempt > job.attempts or str(job.id) not in row.child_job_ids
    ):
        raise RuntimeValidationError("Worker attempt is not an existing delivery of this execution")
    session.add(WorkerExecutionLinkRecord(
        worker_attempt_id=value.worker.worker_attempt_id, execution_id=value.execution_id,
        job_id=value.worker.job_id, attempt=value.worker.attempt,
    ))
    await session.flush()
    await _record_result(session, learner_id, "worker-link", value.execution_id,
                         value.worker.worker_attempt_id, request, request)
    return value


async def record_topic_window(
    session: AsyncSession, learner_id: UUID, value: TopicWindow,
    *, expected_session_version: int, expected_version: int | None = None,
) -> TopicWindow:
    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "session_version": expected_session_version,
                                 "expected": expected_version})
    prior = await _prior_result(session, learner_id, "topic-window",
                                value.window_id, value.event_id, request)
    if prior is not None:
        return TopicWindow.model_validate_json(prior)
    _version(owner.version, expected_session_version)
    if (owner.current_topic_id, owner.graph_version_id) != (value.topic_id, value.graph_version_id):
        raise RuntimeStaleError("Topic window does not match the session position")
    await validate_runtime_event(session, value.event_id, owner)
    mappings = set((await session.scalars(select(CurriculumGraphMapping.concept_id).where(
        CurriculumGraphMapping.graph_id == value.graph_version_id,
        CurriculumGraphMapping.topic_id == value.topic_id,
    ))).all())
    if not set(value.core_concept_ids) <= mappings:
        raise RuntimeValidationError("Core concepts require actual topic mappings")
    extra_topics = (value.next_topic_id,) if value.next_topic_id else ()
    for topic_id in (*value.mandatory_topic_ids, *extra_topics):
        await _graph_position(session, owner, value.graph_version_id, topic_id)
    row = await session.get(TopicWindowRecord, value.window_id, populate_existing=True)
    if row is None:
        if expected_version is not None or value.version != 1:
            raise RuntimeStaleError("New topic window starts at version one")
        row = TopicWindowRecord(id=value.window_id, session_id=owner.id)
        session.add(row)
    else:
        _version(row.version, expected_version or 0)
        old = TopicWindow.model_validate_json(row.value_bytes)
        if value.version != old.version + 1 or old.closed_at is not None:
            raise RuntimeStaleError("Topic window version/lifecycle changed")
        for field in ("session_id", "topic_id", "graph_version_id", "opened_at",
                      "core_concept_ids"):
            if getattr(old, field) != getattr(value, field):
                raise RuntimeConflictError("Immutable topic window identity conflicts")
    row.version, row.event_id = value.version, value.event_id
    row.closed_at, row.value_bytes = value.closed_at, value.canonical_bytes()
    await session.flush()
    await _record_result(session, learner_id, "topic-window", value.window_id, value.event_id,
                         request, value.canonical_bytes())
    return value


async def record_runtime_directive(
    session: AsyncSession, learner_id: UUID, value: RuntimeDirective,
    *, expected_session_version: int, expected_version: int | None = None,
) -> RuntimeDirective:
    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({"value": value.model_dump(mode="json"),
                                 "session_version": expected_session_version,
                                 "expected": expected_version})
    directive_id = value.directive.directive_id
    prior = await _prior_result(session, learner_id, "directive",
                                directive_id, value.event_id, request)
    if prior is not None:
        return RuntimeDirective.model_validate_json(prior)
    _version(owner.version, expected_session_version)
    if owner.graph_version_id != value.graph_version_id or owner.state == SessionState.COMPLETE:
        raise RuntimeStaleError("Directive graph/session is stale or terminal")
    await validate_runtime_event(session, value.event_id, owner)
    from packages.domain.adaptation import DirectiveKind

    if value.directive.kind in {DirectiveKind.SKIP, DirectiveKind.EXPLAIN_SIMPLER}:
        await _graph_position(session, owner, value.graph_version_id, value.directive.target_id)
    elif await session.scalar(select(CurriculumGraphConcept.id).where(
        CurriculumGraphConcept.graph_id == value.graph_version_id,
        CurriculumGraphConcept.stable_concept_id == value.directive.target_id,
    )) is None:
        raise RuntimeValidationError("Directive concept target is absent")
    row = await session.get(RuntimeDirectiveRecord, directive_id, populate_existing=True)
    if row is None:
        if expected_version is not None or value.version != 1 or (
            value.state != DirectiveState.PENDING
        ):
            raise RuntimeValidationError("A directive starts pending at version one")
        row = RuntimeDirectiveRecord(id=directive_id, session_id=owner.id)
        session.add(row)
    else:
        old = RuntimeDirective.model_validate_json(row.value_bytes)
        _version(row.version, expected_version or 0)
        if old.state != DirectiveState.PENDING or value.version != old.version + 1:
            raise RuntimeStaleError("Directive lifecycle/version is stale")
        if (old.directive, old.session_id, old.graph_version_id, old.valid_from) != (
            value.directive, value.session_id, value.graph_version_id, value.valid_from,
        ):
            raise RuntimeConflictError("Original directive identity cannot change")
    row.version, row.event_id = value.version, value.event_id
    row.value_bytes = value.canonical_bytes()
    await session.flush()
    await _record_result(session, learner_id, "directive", directive_id, value.event_id,
                         request, value.canonical_bytes())
    return value


async def record_assessment_batch(
    session: AsyncSession, learner_id: UUID, session_id: UUID, value: AssessmentBatch,
) -> AssessmentBatch:
    owner = await locked_session(session, learner_id, session_id)
    request = value.canonical_bytes()
    prior = await _prior_result(session, learner_id, "assessment-batch",
                                value.batch_id, value.event_id, request)
    if prior is not None:
        return AssessmentBatch.model_validate_json(prior)
    window_row = await session.get(TopicWindowRecord, value.window_id, populate_existing=True)
    if window_row is None or window_row.session_id != owner.id:
        raise RuntimeValidationError("Assessment batch requires its original topic window")
    window = TopicWindow.model_validate_json(window_row.value_bytes)
    await validate_runtime_event(session, value.event_id, owner)
    scores: list[float] = []
    for attempt_id in value.attempt_ids:
        rows = (await session.scalars(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.attempt_id == attempt_id, MasteryEvidenceRecord.kind == "DIRECT",
            MasteryEvidenceRecord.learner_identity_id == learner_id,
            MasteryEvidenceRecord.course_id == owner.course_id,
        ).execution_options(populate_existing=True))).all()
        if len(rows) != 1 or rows[0].applied_at is None or (
            rows[0].graph_version_id != window.graph_version_id
        ):
            raise RuntimeValidationError("Batch requires one accepted direct grade per source item")
        evidence = rows[0]
        if not window.opened_at <= evidence.occurred_at <= value.completed_at or (
            window.closed_at is not None and value.completed_at > window.closed_at
        ):
            raise RuntimeValidationError("Batch source is outside its topic window")
        scores.append(evidence.correct)
    if value.score != sum(scores) / len(scores):
        raise RuntimeConflictError("Batch score conflicts with accepted grades")
    session.add(AssessmentBatchRecord(id=value.batch_id, window_id=value.window_id,
                                    event_id=value.event_id, value_bytes=request))
    await session.flush()
    await _record_result(session, learner_id, "assessment-batch",
                         value.batch_id, value.event_id, request, request)
    return value


async def evaluate_and_record_trigger(
    session: AsyncSession,
    facts: TriggerFacts,
    *,
    as_of: datetime,
) -> TriggerEvaluation:
    """Evaluate and durably journal one material-trigger identity."""

    owner = await locked_session(session, facts.submission.learner_id, facts.submission.session_id)
    request = facts.canonical_bytes()
    trigger_id = facts.submission.identity.trigger_id
    prior = await _prior_result(
        session, owner.learner_identity_id, "trigger", owner.id, trigger_id, request,
    )
    if prior is not None:
        return TriggerEvaluation.model_validate_json(prior)
    latest = await session.scalar(select(RuntimeTriggerRecord).where(
        RuntimeTriggerRecord.learner_id == owner.learner_identity_id,
        RuntimeTriggerRecord.status == TriggerStatus.ADMITTED,
    ).order_by(RuntimeTriggerRecord.admitted_at.desc()).limit(1)
      .execution_options(populate_existing=True))
    if latest is not None and facts.last_plan_trigger_at is None:
        facts = facts.model_copy(update={"last_plan_trigger_at": latest.admitted_at})
    result = evaluate_trigger(facts, as_of)
    session.add(RuntimeTriggerRecord(
        id=trigger_id, learner_id=owner.learner_identity_id, session_id=owner.id,
        kind=result.kind, source_event_id=facts.submission.source_event_id,
        request_bytes=request, original_result_bytes=result.canonical_bytes(),
        status=result.status, eligible_after=result.eligible_after,
        admitted_at=(as_of if result.status == TriggerStatus.ADMITTED else None),
    ))
    await session.flush()
    await _record_result(
        session, owner.learner_identity_id, "trigger", owner.id, trigger_id,
        request, result.canonical_bytes(),
    )
    return result


async def recover_deferred_trigger(
    session: AsyncSession,
    learner_id: UUID,
    trigger_id: UUID,
    facts: TriggerFacts,
    *,
    as_of: datetime,
) -> TriggerEvaluation:
    """Re-evaluate a deferred trigger under the current learner fence."""

    await locked_session(session, learner_id, facts.submission.session_id)
    row = await session.scalar(select(RuntimeTriggerRecord).where(
        RuntimeTriggerRecord.id == trigger_id,
        RuntimeTriggerRecord.learner_id == learner_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None or row.status != TriggerStatus.DEFERRED:
        raise RuntimeValidationError("Only a durable deferred trigger can be recovered")
    if row.eligible_after is not None and as_of < row.eligible_after:
        raise RuntimeStaleError("Deferred trigger is not eligible yet")
    if facts.submission.identity.trigger_id != trigger_id:
        raise RuntimeConflictError("Deferred trigger identity conflicts")
    result = evaluate_trigger(facts.model_copy(update={"last_plan_trigger_at": None}), as_of)
    if result.status == TriggerStatus.DEFERRED:
        raise RuntimeStaleError("Cooldown remains active after deferred recovery")
    row.status = result.status
    row.admitted_at = as_of if result.status == TriggerStatus.ADMITTED else None
    await session.flush()
    return result
