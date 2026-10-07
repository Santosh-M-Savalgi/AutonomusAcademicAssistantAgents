"""Stage 7 authorization, deterministic educational execution and session linkage."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain import DeterministicEducationalExecutor, EducationalExecutionResult
from packages.domain.enums import PlannerAction
from packages.domain.runtime import (
    SESSION_TRANSITIONS,
    DurablePlanVersion,
    ExecutionIdentity,
    ExecutionReceipt,
    ExecutionState,
    SessionState,
    SessionTransition,
    WorkerAttemptIdentity,
    canonical_execution_request,
)
from packages.domain.runtime_state import RuntimeDirective, WorkerExecutionLink
from packages.persistence.planning_snapshot import assemble_planning_snapshot
from packages.persistence.runtime import (
    RuntimeConflictError,
    RuntimeStaleError,
    RuntimeValidationError,
    get_execution_receipt,
    get_plan_version,
    locked_session,
    record_execution_receipt,
    record_worker_execution_link,
    transition_learning_session,
    validate_runtime_event,
)
from packages.persistence.runtime_models import (
    DiagnosticRunRecord,
    ExecutionReceiptRecord,
    LearningSessionRecord,
)
from packages.persistence.runtime_support_models import (
    RuntimeDirectiveRecord,
    RuntimeTriggerPlanLinkRecord,
    RuntimeTriggerRecord,
)

_ACTION_STATES = {
    PlannerAction.DIAGNOSE: SessionState.DIAGNOSING,
    PlannerAction.GENERATE_MICRO_CHECK: SessionState.CHECKPOINT,
    PlannerAction.GENERATE_QUIZ: SessionState.ASSESSING,
    PlannerAction.ADVANCE_TOPIC: SessionState.ADVANCE,
    PlannerAction.COMPLETE: SessionState.COMPLETE,
}


def _target_state(action: PlannerAction) -> SessionState:
    return _ACTION_STATES.get(action, SessionState.TEACHING)


def _blocked_result(plan_id: UUID, reason: str) -> bytes:
    return json.dumps({
        "adapter": "deterministic-test-v1",
        "plan_version_id": str(plan_id),
        "status": "BLOCKED",
        "reason": reason,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


async def _link_worker(
    session: AsyncSession,
    learner_id: UUID,
    session_id: UUID,
    execution: ExecutionReceipt,
    worker: WorkerAttemptIdentity | None,
) -> None:
    if worker is None:
        return
    await record_worker_execution_link(
        session, learner_id, session_id,
        WorkerExecutionLink(worker=worker, execution_id=execution.identity.execution_id),
    )


def _receipt_for_result(
    plan: DurablePlanVersion,
    result: EducationalExecutionResult,
    *,
    created_at: datetime,
    completed_at: datetime,
    child_job_ids: tuple[UUID, ...],
    event_id: UUID,
    confirmation_event_id: UUID | None,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id),
        plan=plan,
        state=ExecutionState.COMPLETED,
        version=1,
        emitted_event_ids=(event_id,),
        child_job_ids=child_job_ids,
        confirmation_event_id=confirmation_event_id,
        request_bytes=result.request_bytes,
        result_bytes=result.result_bytes,
        created_at=created_at,
        completed_at=completed_at,
    )


async def _validate_published_dependencies(
    session: AsyncSession, owner: LearningSessionRecord, plan: DurablePlanVersion, *,
    as_of: datetime,
) -> None:
    if plan.graph_version_id != owner.graph_version_id:
        raise RuntimeStaleError("Plan graph dependency is stale")
    if plan.snapshot.topic is not None and plan.snapshot.topic.topic_id != owner.current_topic_id:
        raise RuntimeStaleError("Plan topic dependency is stale")
    if plan.frame_id != owner.active_frame_id:
        raise RuntimeStaleError("Plan remediation dependency is stale")
    current_snapshot = await assemble_planning_snapshot(
        session, owner.learner_identity_id, owner.id, as_of=as_of,
    )
    current_state = current_snapshot.planning_state.model_copy(update={
        "plan_version": plan.identity.version,
        "source_event_ids": plan.snapshot.source_event_ids,
    })
    if current_state.canonical_bytes() != plan.snapshot.canonical_bytes():
        raise RuntimeStaleError("Published plan dependencies changed after planning")
    trigger_link = await session.scalar(select(RuntimeTriggerPlanLinkRecord).where(
        RuntimeTriggerPlanLinkRecord.plan_version_id == plan.identity.plan_version_id,
    ).execution_options(populate_existing=True))
    if trigger_link is not None:
        trigger = await session.get(RuntimeTriggerRecord, trigger_link.trigger_id,
                                    populate_existing=True)
        if trigger is None or trigger.status != "ADMITTED" or (
            trigger.learner_id != owner.learner_identity_id
            or trigger.session_id != owner.id
            or trigger.source_event_id != plan.source_event_id
        ):
            raise RuntimeStaleError("Published plan trigger dependency is no longer admitted")
    provenance = plan.decision.provenance
    if provenance is not None and provenance.directive_id is not None:
        directive = await session.get(RuntimeDirectiveRecord, provenance.directive_id,
                                      populate_existing=True)
        if directive is None:
            raise RuntimeStaleError("Published directive dependency is missing")
        directive_value = RuntimeDirective.model_validate_json(directive.value_bytes)
        if directive_value.state.value != "PENDING":
            raise RuntimeStaleError("Published directive dependency is no longer pending")
    diagnostic = plan.snapshot.diagnostic_state
    if diagnostic is not None:
        run = await session.get(DiagnosticRunRecord, diagnostic.diagnostic_run_id,
                                populate_existing=True)
        if run is None or run.state != "OPEN" or run.graph_version_id != owner.graph_version_id:
            raise RuntimeStaleError("Published diagnostic dependency is no longer open")


async def execute_published_plan(
    session: AsyncSession,
    learner_id: UUID,
    plan_version_id: UUID,
    *,
    event_id: UUID,
    started_at: datetime,
    completed_at: datetime | None = None,
    worker: WorkerAttemptIdentity | None = None,
    confirmation_event_id: UUID | None = None,
    executor: DeterministicEducationalExecutor | None = None,
) -> ExecutionReceipt:
    """Execute one current immutable plan with logical exactly-once semantics."""

    owner = await locked_session(session, learner_id, (
        await _plan_session_id(session, learner_id, plan_version_id)
    ))
    plan = await get_plan_version(session, learner_id, plan_version_id)
    if plan is None:
        raise RuntimeValidationError("Published plan is missing its immutable payload")
    execution_id = ExecutionIdentity(plan_version_id=plan_version_id).execution_id
    existing_row = await session.get(ExecutionReceiptRecord, execution_id, populate_existing=True)
    if existing_row is not None:
        existing = await get_execution_receipt(session, learner_id, execution_id)
        if existing is None:
            raise RuntimeValidationError("Execution row is missing its immutable receipt")
        if existing.state in {
            ExecutionState.COMPLETED, ExecutionState.BLOCKED, ExecutionState.STALE,
            ExecutionState.SUPERSEDED, ExecutionState.FAILED,
        }:
            if (
                completed_at is not None
                and existing.completed_at is not None
                and completed_at != existing.completed_at
            ) or (
                confirmation_event_id is not None
                and confirmation_event_id != existing.confirmation_event_id
            ):
                raise RuntimeConflictError(
                    "Terminal execution retry changed immutable completion data",
                )
            await _link_worker(session, learner_id, owner.id, existing, worker)
            return existing
        if existing.state == ExecutionState.AWAITING_CONFIRMATION and confirmation_event_id is None:
            await _link_worker(session, learner_id, owner.id, existing, worker)
            return existing
        expected_execution_version = existing.version
        created_at = existing.created_at
    else:
        expected_execution_version = None
        created_at = started_at

    if owner.current_plan_version_id != plan_version_id:
        raise RuntimeStaleError("Plan is no longer the current authorized session head")
    if owner.version != plan.session_version:
        raise RuntimeStaleError("Plan session fence is stale")
    if owner.state == SessionState.COMPLETE:
        raise RuntimeStaleError("A complete session cannot execute a plan")
    await _validate_published_dependencies(session, owner, plan, as_of=started_at)
    await validate_runtime_event(session, event_id, owner)
    if confirmation_event_id is not None:
        await validate_runtime_event(session, confirmation_event_id, owner)

    if plan.decision.policy_outcome == "BLOCK":
        blocked = ExecutionReceipt(
            identity=ExecutionIdentity(plan_version_id=plan_version_id), plan=plan,
            state=ExecutionState.BLOCKED, version=(expected_execution_version or 0) + 1,
            request_bytes=canonical_execution_request(plan),
            result_bytes=_blocked_result(plan_version_id, "AUTHORITATIVE_POLICY_BLOCK"),
            created_at=created_at, completed_at=completed_at or started_at,
        )
        result = await record_execution_receipt(
            session, blocked, event_id=event_id,
            expected_version=expected_execution_version,
            expected_session_version=owner.version,
        )
        await _link_worker(session, learner_id, owner.id, result, worker)
        return result
    if plan.decision.policy_outcome == "REQUIRE_CONFIRMATION" and confirmation_event_id is None:
        waiting = ExecutionReceipt(
            identity=ExecutionIdentity(plan_version_id=plan_version_id), plan=plan,
            state=ExecutionState.AWAITING_CONFIRMATION,
            version=(expected_execution_version or 0) + 1,
            confirmation_event_id=None,
            request_bytes=canonical_execution_request(plan),
            created_at=created_at,
        )
        result = await record_execution_receipt(
            session, waiting, event_id=event_id,
            expected_version=expected_execution_version,
            expected_session_version=owner.version,
        )
        await _link_worker(session, learner_id, owner.id, result, worker)
        return result
    if plan.decision.action in {PlannerAction.ASK_USER, PlannerAction.PAUSE}:
        raise RuntimeValidationError("This plan has no authorized educational action")

    action_executor = executor or DeterministicEducationalExecutor()
    try:
        action_result = action_executor.execute(plan)
    except Exception:
        failed = ExecutionReceipt(
            identity=ExecutionIdentity(plan_version_id=plan_version_id), plan=plan,
            state=ExecutionState.FAILED, version=(expected_execution_version or 0) + 1,
            confirmation_event_id=confirmation_event_id,
            request_bytes=canonical_execution_request(plan),
            result_bytes=_blocked_result(plan_version_id, "DETERMINISTIC_EXECUTOR_FAILURE"),
            child_job_ids=(() if worker is None else (worker.job_id,)),
            created_at=created_at, completed_at=completed_at or started_at,
        )
        result = await record_execution_receipt(
            session, failed, event_id=event_id,
            expected_version=expected_execution_version,
            expected_session_version=owner.version,
        )
        await _link_worker(session, learner_id, owner.id, result, worker)
        return result
    result = _receipt_for_result(
        plan, action_result, created_at=created_at,
        completed_at=completed_at or started_at,
        child_job_ids=(() if worker is None else (worker.job_id,)), event_id=event_id,
        confirmation_event_id=confirmation_event_id,
    )
    if expected_execution_version is not None:
        result = result.model_copy(update={"version": expected_execution_version + 1})
    receipt = await record_execution_receipt(
        session, result, event_id=event_id,
        expected_version=expected_execution_version,
        expected_session_version=owner.version,
    )
    to_state = _target_state(plan.decision.action)
    if to_state not in SESSION_TRANSITIONS[SessionState(owner.state)]:
        raise RuntimeStaleError(
            f"Plan action {plan.decision.action} cannot transition session from {owner.state}"
        )
    transition = SessionTransition(
        session_id=owner.id, event_id=event_id,
        from_state=SessionState(owner.state), to_state=to_state,
        from_version=owner.version, to_version=owner.version + 1,
        occurred_at=completed_at or started_at,
        plan_version_id=plan_version_id, execution_id=receipt.identity.execution_id,
    )
    await transition_learning_session(session, learner_id, transition)
    await _link_worker(session, learner_id, owner.id, receipt, worker)
    return receipt


async def _plan_session_id(
    session: AsyncSession, learner_id: UUID, plan_version_id: UUID,
) -> UUID:
    plan = await get_plan_version(session, learner_id, plan_version_id)
    if plan is None:
        raise RuntimeValidationError("Plan is missing before execution authorization")
    return plan.plan.session_id
