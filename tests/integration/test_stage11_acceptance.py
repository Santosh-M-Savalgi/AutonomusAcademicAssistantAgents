"""Stage 11 deterministic end-to-end Sprint 3.7 acceptance slice."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from packages.domain.runtime import SourceIdentity, SourceKind, WorkerAttemptIdentity
from packages.domain.triggers import TriggerFacts, TriggerKind, TriggerSubmission
from packages.persistence import (
    ExecutionReceiptRecord,
    RuntimeTriggerPlanLinkRecord,
    RuntimeTriggerRecord,
    assemble_planning_snapshot,
    evaluate_and_record_trigger,
    execute_published_plan,
    get_learning_session,
)
from packages.persistence.runtime_models import SessionTransitionRecord
from packages.persistence.runtime_support_models import WorkerExecutionLinkRecord
from tests.integration.test_block_b_planning_execution import (
    _publish,
    _snapshot,
)
from tests.unit.test_runtime_contracts import AT

pytest_plugins = ("tests.integration.test_block_b_planning_execution",)
pytestmark = pytest.mark.live_integration


async def test_stage11_deterministic_adaptive_vertical_slice(live_database, block_b_source):
    """Prove outcome/mastery/trigger/snapshot/plan/execution/session continuity."""

    source, session_value = block_b_source
    initial = await _snapshot(live_database, source, session_value)
    assert initial.evidence_count == 1
    assert initial.evidence_set_digest is not None

    submission = TriggerSubmission(
        learner_id=session_value.learner_id,
        session_id=session_value.session_id,
        source=SourceIdentity(
            kind=SourceKind.EVENT, source_id=source["planning_event_id"],
        ),
        source_event_id=source["planning_event_id"],
        kind=TriggerKind.STRONG_PERFORMANCE,
        expected_session_version=initial.session.version,
        window_id=uuid4(), batch_id=uuid4(),
    )
    facts = TriggerFacts(
        submission=submission,
        session_version=initial.session.version,
        batch_completed=True,
        batch_is_quiz=True,
        batch_score=1.0,
        batch_item_count=3,
        gate_satisfied=True,
    )
    async with live_database.session() as session, session.begin():
        trigger = await evaluate_and_record_trigger(
            session, facts, as_of=AT + timedelta(seconds=2),
        )
    assert trigger.status.value == "ADMITTED"

    async with live_database.session() as session, session.begin():
        trigger_row = await session.get(RuntimeTriggerRecord, trigger.trigger_id)
        assert trigger_row is not None and trigger_row.status == "ADMITTED"
        snapshot = await assemble_planning_snapshot(
            session, session_value.learner_id, session_value.session_id,
            as_of=AT + timedelta(seconds=2), trigger=trigger,
        )
    assert snapshot.evidence_count == 1
    assert snapshot.session_fingerprint

    plan = await _publish(
        live_database, source, session_value, snapshot,
        source_event_id=source["planning_event_id"], trigger=trigger,
        trigger_identity=submission.identity,
    )
    assert plan.identity.trigger_id == submission.identity.trigger_id
    assert plan.source_event_id == source["planning_event_id"]

    worker = WorkerAttemptIdentity(job_id=source["job_id"], attempt=2)
    async with live_database.session() as session, session.begin():
        receipt = await execute_published_plan(
            session, session_value.learner_id, plan.identity.plan_version_id,
            event_id=source["execution_event_id"],
            started_at=AT + timedelta(seconds=4),
            completed_at=AT + timedelta(seconds=5), worker=worker,
        )
    assert receipt.state.value == "COMPLETED"
    assert receipt.identity.execution_id != worker.worker_attempt_id
    assert receipt.identity.execution_id != submission.identity.trigger_id
    assert plan.identity.plan_version_id != submission.identity.trigger_id

    async with live_database.session() as session:
        final = await get_learning_session(
            session, session_value.learner_id, session_value.session_id,
        )
        trigger_plan_link = await session.get(
            RuntimeTriggerPlanLinkRecord, trigger.trigger_id,
        )
        execution_row = await session.get(
            ExecutionReceiptRecord, receipt.identity.execution_id,
        )
        worker_link = await session.scalar(
            select(WorkerExecutionLinkRecord).where(
                WorkerExecutionLinkRecord.execution_id == receipt.identity.execution_id,
            ),
        )
        transition = await session.scalar(
            select(SessionTransitionRecord).where(
                SessionTransitionRecord.execution_id == receipt.identity.execution_id,
            ),
        )
    assert final is not None
    assert final.state.value == "TEACHING"
    assert final.current_plan_version_id == plan.identity.plan_version_id
    assert final.version == snapshot.session.version + 1
    assert trigger_plan_link is not None
    assert trigger_plan_link.plan_version_id == plan.identity.plan_version_id
    assert execution_row is not None
    assert worker_link is not None
    assert transition is not None
    assert transition.plan_version_id == plan.identity.plan_version_id
    assert transition.execution_id == receipt.identity.execution_id
