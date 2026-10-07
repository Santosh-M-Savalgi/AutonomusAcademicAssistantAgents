"""Stage 6 planner boundary, immutable publication and session-head ownership."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import PlannerDecision
from packages.domain.runtime import (
    DurablePlanVersion,
    LearningPlan,
    PlanVersionIdentity,
    SourceIdentity,
    TriggerIdentity,
    deterministic_plan_id,
)
from packages.domain.snapshot import AuthoritativePlanningSnapshot
from packages.domain.triggers import TriggerEvaluation, TriggerStatus
from packages.persistence.models import CurriculumGraphVersion
from packages.persistence.planning_snapshot import revalidate_planning_snapshot
from packages.persistence.runtime import (
    RuntimeConflictError,
    RuntimeStaleError,
    RuntimeValidationError,
    locked_session,
    store_plan_version,
)
from packages.persistence.runtime_models import LearningPlanVersionRecord
from packages.persistence.runtime_support_models import (
    RuntimeOperationRecord,
    RuntimeTriggerPlanLinkRecord,
    RuntimeTriggerRecord,
)
from packages.planner import PlannerPolicy


def _plan_immutable_material(value: DurablePlanVersion) -> bytes:
    """Exclude only transaction-time creation stamps from retry comparison."""

    data = value.model_dump(mode="json")
    data["created_at"] = None
    data["plan"]["created_at"] = None
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


async def _stored_plan(
    session: AsyncSession, learner_id: UUID, version_id: UUID,
) -> DurablePlanVersion | None:
    receipt = await session.scalar(select(RuntimeOperationRecord.result_bytes).where(
        RuntimeOperationRecord.kind == "plan-version",
        RuntimeOperationRecord.source_id == version_id,
        RuntimeOperationRecord.learner_id == learner_id,
    ).execution_options(populate_existing=True))
    return None if receipt is None else DurablePlanVersion.model_validate_json(receipt)


async def _graph_revision(
    session: AsyncSession, graph_version_id: UUID | None,
) -> UUID | None:
    if graph_version_id is None:
        return None
    graph = await session.get(CurriculumGraphVersion, graph_version_id, populate_existing=True)
    if graph is None:
        raise RuntimeValidationError("Plan graph version is missing")
    return graph.curriculum_revision_id


async def _validate_trigger_link(
    session: AsyncSession,
    value: DurablePlanVersion,
    trigger_identity: TriggerIdentity | None,
) -> bool:
    if trigger_identity is None:
        return False
    if trigger_identity.trigger_id != value.identity.trigger_id:
        raise RuntimeConflictError("Plan trigger identity conflicts with its source")
    trigger = await session.get(RuntimeTriggerRecord, trigger_identity.trigger_id,
                                populate_existing=True)
    if trigger is None or trigger.status != TriggerStatus.ADMITTED:
        raise RuntimeStaleError("Only an admitted durable trigger can publish a plan")
    if trigger.learner_id != value.plan.learner_id or trigger.session_id != value.plan.session_id:
        raise RuntimeValidationError("Trigger and plan scopes conflict")
    if trigger.source_event_id != value.source_event_id:
        raise RuntimeConflictError("Plan source event conflicts with its trigger")
    existing = await session.get(RuntimeTriggerPlanLinkRecord, trigger_identity.trigger_id,
                                 populate_existing=True)
    if existing is not None and existing.plan_version_id != value.identity.plan_version_id:
        raise RuntimeConflictError("Trigger has already consumed another plan")
    return existing is not None


async def _create_trigger_link(
    session: AsyncSession, value: DurablePlanVersion, trigger_identity: TriggerIdentity | None,
) -> None:
    if trigger_identity is None:
        return
    session.add(RuntimeTriggerPlanLinkRecord(
        trigger_id=trigger_identity.trigger_id,
        plan_version_id=value.identity.plan_version_id,
    ))
    await session.flush()


async def publish_plan_version(
    session: AsyncSession,
    value: DurablePlanVersion,
    *,
    expected_head_id: UUID | None,
    trigger_identity: TriggerIdentity | None = None,
) -> DurablePlanVersion:
    """Publish one immutable plan and move the session head in the same transaction."""

    owner = await locked_session(session, value.plan.learner_id, value.plan.session_id)
    existing_row = await session.get(LearningPlanVersionRecord, value.identity.plan_version_id,
                                     populate_existing=True)
    if existing_row is not None:
        stored = await _stored_plan(session, owner.learner_identity_id,
                                    value.identity.plan_version_id)
        if stored is None:
            raise RuntimeValidationError("Published plan is missing its immutable receipt")
        if _plan_immutable_material(stored) != _plan_immutable_material(value):
            raise RuntimeConflictError("Plan identity was reused with changed immutable content")
        if not await _validate_trigger_link(session, stored, trigger_identity):
            await _create_trigger_link(session, stored, trigger_identity)
        return stored

    _version = owner.version
    if _version != value.session_version:
        raise RuntimeStaleError(
            f"Expected session version {value.session_version}; current version is {_version}"
        )
    if owner.current_plan_version_id != expected_head_id:
        raise RuntimeStaleError("Session plan head changed before publication")
    if value.supersedes_version_id != expected_head_id:
        raise RuntimeStaleError("Plan predecessor does not match the session head")
    trigger_link_exists = await _validate_trigger_link(session, value, trigger_identity)
    await store_plan_version(session, value)
    if not trigger_link_exists:
        await _create_trigger_link(session, value, trigger_identity)
    owner.current_plan_version_id = value.identity.plan_version_id
    await session.flush()
    return value


async def invoke_and_publish_plan(
    session: AsyncSession,
    snapshot: AuthoritativePlanningSnapshot,
    *,
    source: SourceIdentity,
    source_event_id: UUID,
    created_at: datetime,
    mastery_policy_version: str = "mastery_v1",
    trigger_identity: TriggerIdentity | None = None,
    trigger: TriggerEvaluation | None = None,
) -> DurablePlanVersion:
    """Run the existing pure planner and publish its detached decision."""

    identity = trigger_identity or TriggerIdentity(
        learner_id=snapshot.learner_id, source=source, trigger_kind="PLANNER_INVOCATION",
    )
    owner = await locked_session(session, snapshot.learner_id, snapshot.session.session_id)
    operation_version_id = PlanVersionIdentity(
        session_id=snapshot.session.session_id,
        trigger_id=identity.trigger_id,
        version=snapshot.plan_version,
    ).plan_version_id
    existing = await _stored_plan(
        session, owner.learner_identity_id, operation_version_id,
    )
    if existing is not None:
        # A lost response is recovered from the immutable operation identity before
        # current dependency freshness is checked.  The detached snapshot still
        # participates in exact request comparison, so changed requests conflict.
        replay_decision = PlannerPolicy.decide(snapshot.planning_state)
        if replay_decision.plan_version != snapshot.plan_version:
            raise RuntimeConflictError("Planner decision version does not match the snapshot")
        candidate = existing.model_copy(update={
            "source": source,
            "source_event_id": source_event_id,
            "session_version": snapshot.session.version,
            "frame_id": (
                None if snapshot.active_remediation is None
                else snapshot.active_remediation.frame_id
            ),
            "frame_version": snapshot.frame_version,
            "graph_version_id": (
                None if snapshot.graph_context is None
                else snapshot.graph_context.graph_version_id
            ),
            "snapshot": snapshot.planning_state,
            "decision": replay_decision,
            "source_snapshot_fingerprint": snapshot.session_fingerprint,
        })
        if _plan_immutable_material(existing) != _plan_immutable_material(candidate):
            raise RuntimeConflictError("Plan retry changed immutable snapshot material")
        return await publish_plan_version(
            session, existing, expected_head_id=existing.supersedes_version_id,
            trigger_identity=trigger_identity,
        )

    await revalidate_planning_snapshot(session, snapshot)
    if trigger is not None and trigger.status != TriggerStatus.ADMITTED:
        raise RuntimeStaleError("Only an admitted trigger can invoke planning")
    if snapshot.trigger is not None:
        if trigger_identity is None or snapshot.trigger.trigger_id != trigger_identity.trigger_id:
            raise RuntimeConflictError("Snapshot trigger provenance is incomplete")
        if trigger is not None and trigger.trigger_id != snapshot.trigger.trigger_id:
            raise RuntimeConflictError("Snapshot and trigger evaluation identities conflict")
    elif trigger_identity is not None:
        raise RuntimeConflictError(
            "A trigger identity cannot be attached to a triggerless snapshot",
        )

    decision: PlannerDecision = PlannerPolicy.decide(snapshot.planning_state)
    if decision.plan_version != snapshot.plan_version:
        raise RuntimeConflictError("Planner decision version does not match the snapshot")
    owner = await locked_session(session, snapshot.learner_id, snapshot.session.session_id)
    existing = await _stored_plan(
        session, owner.learner_identity_id, operation_version_id,
    )
    previous = None
    if existing is not None:
        previous = (None if existing.supersedes_version_id is None else await _stored_plan(
            session, owner.learner_identity_id, existing.supersedes_version_id,
        ))
        if existing.supersedes_version_id is not None and previous is None:
            raise RuntimeValidationError("Existing plan predecessor has no immutable payload")
    elif owner.current_plan_version_id is not None:
        previous = await _stored_plan(
            session, owner.learner_identity_id, owner.current_plan_version_id,
        )
        if previous is None:
            raise RuntimeValidationError("Current session plan head has no immutable plan")
    if (
        existing is None and previous is not None
        and previous.identity.version + 1 != snapshot.plan_version
    ):
        raise RuntimeStaleError("Snapshot plan successor version is stale")
    if existing is None and previous is None and snapshot.plan_version != 1:
        raise RuntimeStaleError("Initial plan version must be one")
    plan = LearningPlan(
        plan_id=deterministic_plan_id(snapshot.session.session_id),
        session_id=snapshot.session.session_id,
        learner_id=snapshot.learner_id,
        course_id=snapshot.course_id,
        created_at=created_at,
    )
    value = DurablePlanVersion(
        plan=plan,
        identity=PlanVersionIdentity(
            session_id=plan.session_id, trigger_id=identity.trigger_id,
            version=snapshot.plan_version,
        ),
        source=source,
        source_event_id=source_event_id,
        session_version=snapshot.session.version,
        frame_id=(None if snapshot.active_remediation is None
                  else snapshot.active_remediation.frame_id),
        frame_version=snapshot.frame_version,
        curriculum_revision_id=await _graph_revision(
            session, None if snapshot.graph_context is None
            else snapshot.graph_context.graph_version_id,
        ),
        graph_version_id=(None if snapshot.graph_context is None
                          else snapshot.graph_context.graph_version_id),
        mastery_policy_version=mastery_policy_version,
        snapshot=snapshot.planning_state,
        decision=decision,
        supersedes_version_id=(existing.supersedes_version_id if existing is not None else
                               (None if previous is None else previous.identity.plan_version_id)),
        source_snapshot_fingerprint=snapshot.session_fingerprint,
        created_at=created_at,
    )
    return await publish_plan_version(
        session, value, expected_head_id=(None if previous is None
                                          else previous.identity.plan_version_id),
        trigger_identity=trigger_identity,
    )
