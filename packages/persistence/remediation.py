"""Stage 8 durable remediation frame, attempt and return orchestration."""

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload
from packages.domain.remediation import (
    RemediationOutcome,
    RemediationProgressEvaluation,
    RemediationRuntimeResult,
    evaluate_remediation_progress,
)
from packages.domain.runtime import (
    FrameAttempt,
    FrameState,
    RemediationFrameSnapshot,
    SessionTransition,
)
from packages.persistence.learning_events import insert_learning_event
from packages.persistence.mastery import get_current_projection
from packages.persistence.models import (
    LearningEventRecord,
    MasteryAttempt,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    StudentIdentity,
)
from packages.persistence.runtime import (
    RuntimeStaleError,
    RuntimeValidationError,
    _prior_result,
    _record_result,
    canonical_request,
    create_remediation_frame,
    locked_session,
    record_frame_attempt,
    transition_learning_session,
    update_remediation_frame,
)
from packages.persistence.runtime_models import FrameAttemptRecord, RemediationFrameRecord


def _frame_snapshot(row: RemediationFrameRecord) -> RemediationFrameSnapshot:
    return RemediationFrameSnapshot.model_validate({
        "frame_id": row.id,
        **{
            field: getattr(row, field)
            for field in RemediationFrameSnapshot.model_fields
            if field != "frame_id"
        },
    })


def _attempt_snapshot(row: FrameAttemptRecord) -> FrameAttempt:
    return FrameAttempt.model_validate({
        field: getattr(row, field) for field in FrameAttempt.model_fields
    })


def _replayed_evaluation(
    frame: RemediationFrameSnapshot, attempt: FrameAttempt,
) -> RemediationProgressEvaluation:
    outcome = (
        RemediationOutcome.RETURN if frame.state == FrameState.COMPLETE
        else RemediationOutcome.BLOCKED
        if frame.state == FrameState.BLOCKED_NEEDS_HUMAN
        else RemediationOutcome.CONTINUE
    )
    return RemediationProgressEvaluation(
        frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
        observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
        progress_delta=attempt.observed_mastery - frame.baseline_mastery,
        threshold=frame.min_progress_delta, next_attempt_count=frame.attempt_count,
        max_attempts=frame.max_attempts, outcome=outcome, next_state=frame.state,
        next_rung=frame.rung, next_strategy=frame.strategy,
        next_baseline_mastery=frame.baseline_mastery, replayed=True,
    )


async def push_remediation_frame(
    session: AsyncSession,
    learner_id: UUID,
    value: RemediationFrameSnapshot,
    *,
    expected_session_version: int,
    created_at: datetime,
) -> RemediationFrameSnapshot:
    """Create a frame and make it the active session head in one transaction."""

    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({
        "value": value.model_dump(mode="json"),
        "expected_session_version": expected_session_version,
        "created_at": created_at.isoformat(),
    })
    prior = await _prior_result(
        session, learner_id, "frame-push", value.session_id, value.frame_id, request,
    )
    if prior is not None:
        return RemediationFrameSnapshot.model_validate_json(prior)
    result = await create_remediation_frame(
        session, learner_id, value,
        expected_session_version=expected_session_version, created_at=created_at,
    )
    if owner.active_frame_id not in (None, value.parent_frame_id, value.frame_id):
        raise RuntimeStaleError("A newer remediation frame already owns the session head")
    owner.active_frame_id = value.frame_id
    await session.flush()
    await _record_result(
        session, learner_id, "frame-push", value.session_id, value.frame_id,
        request, result.canonical_bytes(),
    )
    return result


async def _blocked_event(
    session: AsyncSession, learner_id: UUID, course_id: UUID, frame: RemediationFrameSnapshot,
    attempt: FrameAttempt, evaluation: RemediationProgressEvaluation,
) -> LearningEventRecord:
    actor = await session.get(StudentIdentity, learner_id, populate_existing=True)
    if actor is None:
        raise RuntimeValidationError("Remediation event actor identity is missing")
    key = f"remediation-loop-blocked:v1:{frame.frame_id.hex}:{evaluation.next_rung}"
    event_id = uuid5(NAMESPACE_URL, key)
    return await insert_learning_event(session, LearningEventInput(
        event_id=event_id, type=LearningEventType.REMEDIATION_LOOP_BLOCKED,
        actor_id=learner_id, actor_subject=actor.external_subject,
        learner_id=learner_id, course_id=course_id,
        occurred_at=attempt.occurred_at,
        payload=LearningEventPayload(kind="remediation_loop_blocked", data={
            "frame_id": str(frame.frame_id), "target_concept_id": str(frame.target_concept_id),
            "rung": evaluation.next_rung, "strategy": evaluation.next_strategy,
            "attempt_count": evaluation.next_attempt_count,
            "source_attempt_id": str(attempt.source_attempt_id),
        }),
        causation_id=attempt.event_id,
        correlation_id=uuid5(NAMESPACE_URL, f"{key}:correlation"),
        idempotency_key=key,
    ))


async def record_remediation_attempt(
    session: AsyncSession,
    learner_id: UUID,
    session_id: UUID,
    attempt: FrameAttempt,
    *,
    expected_frame_version: int,
    allow_model_escalation: bool = False,
) -> RemediationRuntimeResult:
    """Persist one learner attempt and apply the per-rung guard exactly once."""

    owner = await locked_session(session, learner_id, session_id)
    request = canonical_request({
        "attempt": attempt.model_dump(mode="json"),
        "expected_frame_version": expected_frame_version,
        "allow_model_escalation": allow_model_escalation,
    })
    prior = await _prior_result(
        session, learner_id, "remediation-attempt", attempt.frame_id,
        attempt.source_attempt_id, request,
    )
    if prior is not None:
        return RemediationRuntimeResult.model_validate_json(prior)
    frame_row = await session.scalar(select(RemediationFrameRecord).where(
        RemediationFrameRecord.id == attempt.frame_id,
    ).with_for_update().execution_options(populate_existing=True))
    if frame_row is None or frame_row.session_id != owner.id:
        raise RuntimeValidationError("Remediation frame is missing")
    frame = _frame_snapshot(frame_row)
    source_attempt = await session.get(
        MasteryAttempt, attempt.source_attempt_id, populate_existing=True,
    )
    if source_attempt is None or source_attempt.occurred_at != attempt.occurred_at:
        raise RuntimeValidationError("Remediation attempt time does not match its source attempt")
    projection_revision = await session.scalar(select(MasteryProjectionRevision).join(
        MasteryProjectionHead,
        MasteryProjectionHead.current_projection_id == MasteryProjectionRevision.id,
    ).where(
        MasteryProjectionHead.learner_identity_id == learner_id,
        MasteryProjectionHead.course_id == owner.course_id,
        MasteryProjectionHead.stable_concept_id == frame.target_concept_id,
    ))
    if projection_revision is None:
        raise RuntimeValidationError("Remediation attempt has no authoritative mastery projection")
    projection_as_of = max(
        attempt.occurred_at,
        projection_revision.max_occurred_at or attempt.occurred_at,
        projection_revision.created_at,
    )
    projection = await get_current_projection(
        session, learner_id, owner.course_id, frame.target_concept_id,
        as_of=projection_as_of,
    )
    if projection is None:
        raise RuntimeValidationError(
            "Remediation attempt has no authoritative mastery projection",
        )
    if abs(projection.metrics.mastery - attempt.observed_mastery) > 1e-12:
        raise RuntimeValidationError(
            "Remediation attempt mastery is not the authoritative projection",
        )
    persisted = await record_frame_attempt(
        session, learner_id, session_id, attempt,
        expected_frame_version=expected_frame_version,
    )
    # record_frame_attempt locks and flushes the same frame; refresh it before
    # evaluating so no concurrent caller can advance this rung twice.
    await session.refresh(frame_row)
    frame = _frame_snapshot(frame_row)
    evaluation = evaluate_remediation_progress(
        frame, persisted, allow_model_escalation=allow_model_escalation,
    )
    last_event_id = persisted.event_id
    if evaluation.outcome == RemediationOutcome.BLOCKED:
        blocked = await _blocked_event(
            session, learner_id, owner.course_id, frame, persisted, evaluation,
        )
        last_event_id = blocked.event_id
    updated = frame.model_copy(update={
        "state": evaluation.next_state,
        "version": frame.version + 1,
        "rung": evaluation.next_rung,
        "strategy": evaluation.next_strategy,
        "attempt_count": evaluation.next_attempt_count,
        "baseline_mastery": evaluation.next_baseline_mastery,
        "latest_mastery": persisted.observed_mastery,
        "last_event_id": last_event_id,
    })
    updated = await update_remediation_frame(
        session, learner_id, updated,
        expected_version=frame.version,
        expected_session_version=owner.version,
        updated_at=persisted.occurred_at,
    )
    result = RemediationRuntimeResult(
        attempt=persisted, frame=updated, evaluation=evaluation,
    )
    await _record_result(
        session, learner_id, "remediation-attempt", attempt.frame_id,
        attempt.source_attempt_id, request, result.canonical_bytes(),
    )
    return result


async def return_remediation_frame(
    session: AsyncSession,
    learner_id: UUID,
    value: RemediationFrameSnapshot,
    *,
    expected_session_version: int,
    transition: SessionTransition,
) -> RemediationFrameSnapshot:
    """Close a complete frame and restore its saved topic/parent context."""

    owner = await locked_session(session, learner_id, value.session_id)
    request = canonical_request({
        "value": value.model_dump(mode="json"),
        "expected_session_version": expected_session_version,
        "transition": transition.model_dump(mode="json"),
    })
    prior = await _prior_result(
        session, learner_id, "frame-return", value.session_id, value.frame_id, request,
    )
    if prior is not None:
        return RemediationFrameSnapshot.model_validate_json(prior)
    frame_row = await session.scalar(select(RemediationFrameRecord).where(
        RemediationFrameRecord.id == value.frame_id,
    ).with_for_update().execution_options(populate_existing=True))
    if frame_row is None or frame_row.session_id != owner.id:
        raise RuntimeValidationError("Remediation frame is missing")
    current = _frame_snapshot(frame_row)
    if owner.active_frame_id != current.frame_id:
        raise RuntimeStaleError("Remediation frame is no longer the active session head")
    if current != value:
        raise RuntimeStaleError("Remediation frame snapshot is stale")
    if current.state != FrameState.COMPLETE or transition.execution_id is None:
        raise RuntimeValidationError("A return requires a complete frame and execution")
    returned = current.model_copy(update={
        "state": FrameState.RETURNED,
        "version": value.version + 1,
        "last_event_id": transition.event_id,
        "returned_by_execution_id": transition.execution_id,
        "returned_at": transition.occurred_at,
    })
    returned = await update_remediation_frame(
        session, learner_id, returned,
        expected_version=value.version,
        expected_session_version=expected_session_version,
        updated_at=transition.occurred_at,
    )
    owner.active_frame_id = None
    await session.flush()
    await transition_learning_session(
        session, learner_id, transition,
        graph_version_id=returned.graph_version_id,
        topic_id=returned.return_to_topic_id,
        change_position=True,
    )
    owner.active_frame_id = returned.parent_frame_id
    await session.flush()
    await _record_result(
        session, learner_id, "frame-return", value.session_id, value.frame_id,
        request, returned.canonical_bytes(),
    )
    return returned
