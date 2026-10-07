"""Block B plan publication and deterministic educational execution tests."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from packages.domain.runtime import (
    ExecutionIdentity,
    ExecutionReceipt,
    ExecutionState,
    LearningSessionSnapshot,
    SessionState,
    SessionTransition,
    SourceIdentity,
    SourceKind,
    WorkerAttemptIdentity,
)
from packages.domain.runtime_state import TopicWindow
from packages.domain.triggers import TriggerFacts, TriggerKind, TriggerSubmission
from packages.persistence import (
    ExecutionReceiptRecord,
    LearningEventRecord,
    LearningSessionRecord,
    RuntimeConflictError,
    RuntimeStaleError,
    RuntimeTriggerPlanLinkRecord,
    RuntimeTriggerRecord,
    RuntimeValidationError,
    assemble_planning_snapshot,
    create_learning_session,
    evaluate_and_record_trigger,
    execute_published_plan,
    get_learning_session,
    invoke_and_publish_plan,
    record_execution_receipt,
    record_topic_window,
    transition_learning_session,
)
from packages.persistence.mastery import apply_evidence
from packages.persistence.models import CurriculumGraphMapping, CurriculumGraphNode, Job
from packages.persistence.runtime_models import SessionTransitionRecord
from packages.persistence.runtime_support_models import WorkerExecutionLinkRecord
from tests.integration.test_mastery_runtime import _evidence, _source_context
from tests.unit.test_runtime_contracts import AT

pytestmark = pytest.mark.live_integration


class FailingExecutor:
    def execute(self, _plan):
        raise RuntimeError("synthetic executor failure")


async def _event(session, source, event_id, event_type="PLAN_REPLANNED"):
    session.add(LearningEventRecord(
        event_id=event_id, event_type=event_type, actor_subject="mastery-actor",
        actor_identity_id=source["actor_id"], learner_identity_id=source["actor_id"],
        course_id=source["course_id"], payload={}, correlation_id=uuid4(), occurred_at=AT,
    ))
    await session.flush()


@pytest.fixture
async def block_b_source(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    source.update(
        session_id=uuid4(), event_id=uuid4(), topic_id=uuid4(),
        planning_event_id=uuid4(), execution_event_id=uuid4(), alternate_event_id=uuid4(),
    )
    async with live_database.session() as session, session.begin():
        source["job_id"] = await session.scalar(select(Job.id))
        await _event(session, source, source["event_id"], "SESSION_STARTED")
        await _event(session, source, source["planning_event_id"])
        await _event(session, source, source["execution_event_id"])
        await _event(session, source, source["alternate_event_id"])
        session.add(CurriculumGraphNode(
            id=uuid4(), graph_id=source["graph_id"], stable_node_id=source["topic_id"],
            node_type="TOPIC", label="Topic", source="TEST", confidence=1.0,
        ))
        session.add(CurriculumGraphMapping(
            id=uuid4(), graph_id=source["graph_id"], mapping_id=uuid4(),
            topic_id=source["topic_id"], concept_id=source["concept_id"],
            mapping_kind="EXPLICIT", source="TEST", confidence=1.0, verified=True,
        ))
        await session.flush()
        value = LearningSessionSnapshot(
            session_id=source["session_id"], learner_id=source["actor_id"],
            course_id=source["course_id"], state=SessionState.CREATED, version=1,
            graph_version_id=source["graph_id"], current_topic_id=source["topic_id"],
            last_event_id=source["event_id"], created_at=AT, updated_at=AT,
        )
        await create_learning_session(session, value)
        await session.execute(update(Job).where(Job.id == source["job_id"]).values(attempts=2))
        await session.flush()
        await apply_evidence(session, _evidence(source), actor_subject="mastery-actor")
        await transition_learning_session(session, value.learner_id, SessionTransition(
            session_id=value.session_id, event_id=source["planning_event_id"],
            from_state=SessionState.CREATED, to_state=SessionState.PLANNING,
            from_version=1, to_version=2, occurred_at=AT + timedelta(seconds=1),
        ))
        await record_topic_window(session, value.learner_id, TopicWindow(
            window_id=uuid4(), session_id=value.session_id, topic_id=value.current_topic_id,
            graph_version_id=source["graph_id"], version=1,
            event_id=source["planning_event_id"], opened_at=AT + timedelta(seconds=1),
            authorized=True, taught=False, prerequisites_evaluated=True,
            core_concept_ids=(source["concept_id"],),
        ), expected_session_version=2)
    return source, value


async def _snapshot(database, source, value, *, trigger=None):
    async with database.session() as session, session.begin():
        return await assemble_planning_snapshot(
            session, value.learner_id, value.session_id, as_of=AT, trigger=trigger,
        )


async def _publish(database, source, value, snapshot, *, source_event_id=None, trigger=None,
                   trigger_identity=None):
    async with database.session() as session, session.begin():
        return await invoke_and_publish_plan(
            session, snapshot,
            source=SourceIdentity(
                kind=SourceKind.EVENT,
                source_id=source_event_id or source["planning_event_id"],
            ),
            source_event_id=source_event_id or source["planning_event_id"],
            created_at=AT + timedelta(seconds=2),
            trigger=trigger, trigger_identity=trigger_identity,
        )


async def test_stage6_invokes_pure_planner_publishes_head_and_retries_original(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)
    assert snapshot.plan_version == 1
    assert snapshot.planning_state.topic is not None
    plan = await _publish(live_database, source, value, snapshot)
    assert plan.decision.action.value == "TEACH_CURRENT_TOPIC"
    assert plan.source_snapshot_fingerprint == snapshot.session_fingerprint
    async with live_database.session() as session, session.begin():
        current = await get_learning_session(session, value.learner_id, value.session_id)
        assert current is not None
        assert current.current_plan_version_id == plan.identity.plan_version_id
        retried = await invoke_and_publish_plan(
            session, snapshot,
            source=SourceIdentity(kind=SourceKind.EVENT, source_id=source["planning_event_id"]),
            source_event_id=source["planning_event_id"], created_at=AT + timedelta(seconds=9),
        )
        assert retried == plan
        assert await session.scalar(select(func.count()).select_from(LearningSessionRecord)) == 1


async def test_stage6_concurrent_identical_publication_converges_and_different_is_stale(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)

    async def publish_same():
        return await _publish(live_database, source, value, snapshot)

    left, right = await asyncio.gather(publish_same(), publish_same())
    assert left == right
    async with live_database.session() as session, session.begin():
        with pytest.raises(RuntimeStaleError):
            await invoke_and_publish_plan(
                session, snapshot,
                source=SourceIdentity(
                    kind=SourceKind.EVENT, source_id=source["alternate_event_id"],
                ),
                source_event_id=source["alternate_event_id"], created_at=AT,
            )


async def test_trigger_to_plan_route_consumes_trigger_once(
    live_database, block_b_source,
):
    source, value = block_b_source
    submission = TriggerSubmission(
        learner_id=value.learner_id, session_id=value.session_id,
        source=SourceIdentity(kind=SourceKind.EVENT, source_id=source["planning_event_id"]),
        source_event_id=source["planning_event_id"], kind=TriggerKind.BATCH_COMPLETED,
        expected_session_version=2, window_id=uuid4(), batch_id=uuid4(),
    )
    facts = TriggerFacts(
        submission=submission, session_version=2, batch_completed=True, batch_is_quiz=True,
        batch_score=1, batch_item_count=3, gate_satisfied=True,
    )
    async with live_database.session() as session, session.begin():
        trigger = await evaluate_and_record_trigger(session, facts, as_of=AT)
    snapshot = await _snapshot(live_database, source, value, trigger=trigger)
    plan = await _publish(
        live_database, source, value, snapshot, source_event_id=source["planning_event_id"],
        trigger=trigger, trigger_identity=submission.identity,
    )
    async with live_database.session() as session, session.begin():
        link = await session.get(RuntimeTriggerPlanLinkRecord, trigger.trigger_id)
        assert link is not None and link.plan_version_id == plan.identity.plan_version_id
        row = await session.get(RuntimeTriggerRecord, trigger.trigger_id)
        assert row is not None and row.status == "ADMITTED"


async def test_stage6_successor_links_previous_plan_after_execution_fence(
    live_database, block_b_source,
):
    source, value = block_b_source
    first_snapshot = await _snapshot(live_database, source, value)
    first = await _publish(live_database, source, value, first_snapshot)
    async with live_database.session() as session, session.begin():
        await execute_published_plan(
            session, value.learner_id, first.identity.plan_version_id,
            event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
        )
    second_snapshot = await _snapshot(live_database, source, value)
    assert second_snapshot.plan_version == 2
    second = await _publish(
        live_database, source, value, second_snapshot,
        source_event_id=source["alternate_event_id"],
    )
    assert second.identity.version == 2
    assert second.supersedes_version_id == first.identity.plan_version_id


async def test_stage7_executes_once_transitions_session_and_links_worker_retries(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)
    plan = await _publish(live_database, source, value, snapshot)
    worker = WorkerAttemptIdentity(job_id=source["job_id"], attempt=1)

    async def execute_once():
        async with live_database.session() as session, session.begin():
            return await execute_published_plan(
                session, value.learner_id, plan.identity.plan_version_id,
                event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
                completed_at=AT + timedelta(seconds=4), worker=worker,
            )

    receipt, concurrent_retry = await asyncio.gather(execute_once(), execute_once())
    assert receipt == concurrent_retry
    assert receipt.state.value == "COMPLETED"
    assert receipt.request_digest is not None and receipt.result_digest is not None
    assert receipt.receipt_fingerprint
    async with live_database.session() as session:
        current = await get_learning_session(session, value.learner_id, value.session_id)
        assert current is not None and current.state == SessionState.TEACHING
        assert current.version == 3
    async with live_database.session() as session, session.begin():
        retried = await execute_published_plan(
            session, value.learner_id, plan.identity.plan_version_id,
            event_id=source["alternate_event_id"], started_at=AT + timedelta(seconds=5),
            worker=WorkerAttemptIdentity(job_id=source["job_id"], attempt=2),
        )
        assert retried == receipt
        assert await session.scalar(select(func.count()).select_from(ExecutionReceiptRecord)) == 1
        assert await session.scalar(
            select(func.count()).select_from(WorkerExecutionLinkRecord),
        ) == 2
        assert await session.scalar(
            select(func.count()).select_from(SessionTransitionRecord),
        ) == 2


async def test_stage7_stale_plan_and_changed_execution_request_are_rejected(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)
    plan = await _publish(live_database, source, value, snapshot)
    async with live_database.session() as session, session.begin():
        original = ExecutionReceipt(
            identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id),
            plan=plan, state=ExecutionState.PENDING, version=1, created_at=AT,
            request_bytes=b"original-request",
        )
        await record_execution_receipt(
            session, original, event_id=source["execution_event_id"],
            expected_session_version=2,
        )
        changed = ExecutionReceipt.model_validate({
            **original.model_dump(), "version": 2, "request_bytes": b"changed-request",
            "request_digest": None,
        })
        with pytest.raises(RuntimeConflictError):
            await record_execution_receipt(
                session, changed, event_id=source["alternate_event_id"], expected_version=1,
                expected_session_version=2,
            )
    async with live_database.session() as session, session.begin():
        with pytest.raises(RuntimeValidationError):
            await execute_published_plan(
                session, value.learner_id, uuid4(), event_id=source["execution_event_id"],
                started_at=AT,
            )
    async with live_database.session() as session, session.begin():
        event_id = source["alternate_event_id"]
        await transition_learning_session(session, value.learner_id, SessionTransition(
            session_id=value.session_id, event_id=event_id,
            from_state=SessionState.PLANNING, to_state=SessionState.TEACHING,
            from_version=2, to_version=3, occurred_at=AT + timedelta(seconds=3),
        ))
    async with live_database.session() as session, session.begin():
        with pytest.raises(RuntimeStaleError):
            await execute_published_plan(
                session, value.learner_id, plan.identity.plan_version_id,
                event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=4),
            )


async def test_stage7_executor_failure_is_durable_and_retry_does_not_reexecute(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)
    plan = await _publish(live_database, source, value, snapshot)
    async with live_database.session() as session, session.begin():
        failed = await execute_published_plan(
            session, value.learner_id, plan.identity.plan_version_id,
            event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
            executor=FailingExecutor(),
        )
        assert failed.state == ExecutionState.FAILED
        current = await get_learning_session(session, value.learner_id, value.session_id)
        assert current is not None and current.state == SessionState.PLANNING
    async with live_database.session() as session, session.begin():
        retried = await execute_published_plan(
            session, value.learner_id, plan.identity.plan_version_id,
            event_id=source["alternate_event_id"], started_at=AT + timedelta(seconds=4),
        )
        assert retried == failed


async def test_stage7_crash_before_commit_rolls_back_then_retry_commits_once(
    live_database, block_b_source,
):
    source, value = block_b_source
    snapshot = await _snapshot(live_database, source, value)
    plan = await _publish(live_database, source, value, snapshot)
    with pytest.raises(RuntimeError, match="lost response"):
        async with live_database.session() as session, session.begin():
            await execute_published_plan(
                session, value.learner_id, plan.identity.plan_version_id,
                event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
            )
            raise RuntimeError("lost response before commit")
    async with live_database.session() as session, session.begin():
        assert await session.scalar(select(func.count()).select_from(ExecutionReceiptRecord)) == 0
        receipt = await execute_published_plan(
            session, value.learner_id, plan.identity.plan_version_id,
            event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=4),
        )
        assert receipt.state == ExecutionState.COMPLETED
