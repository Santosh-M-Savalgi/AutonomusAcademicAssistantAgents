"""Stage 3 repository boundaries on fixture-owned PostgreSQL."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.domain.adaptation import DiagnosticState
from packages.domain.runtime import (
    DiagnosticRunSnapshot,
    DiagnosticRunState,
    ExecutionIdentity,
    ExecutionReceipt,
    ExecutionState,
    LearningSessionSnapshot,
    SessionState,
    SessionTransition,
    SourceIdentity,
    SourceKind,
)
from packages.persistence import (
    CurriculumGraphMapping,
    CurriculumGraphNode,
    LearningEventRecord,
    LearningSessionRecord,
)
from packages.persistence.runtime import (
    RuntimeConflictError,
    RuntimeStaleError,
    RuntimeValidationError,
    create_diagnostic_run,
    create_learning_session,
    get_learning_session,
    get_plan_version,
    record_execution_receipt,
    reserve_diagnostic_question,
    store_plan_version,
    transition_learning_session,
)
from packages.persistence.runtime_support_models import RuntimeOperationRecord
from tests.integration.test_mastery_runtime import _source_context
from tests.unit.test_runtime_contracts import AT, plan_contract

pytestmark = pytest.mark.live_integration


@pytest.fixture
async def repository_source(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    source.update(session_id=uuid4(), event_id=uuid4(), topic_id=uuid4())
    async with live_database.session() as session, session.begin():
        session.add(LearningEventRecord(
            event_id=source["event_id"], event_type="SESSION_STARTED",
            actor_subject="mastery-actor", actor_identity_id=source["actor_id"],
            learner_identity_id=source["actor_id"], course_id=source["course_id"],
            payload={}, correlation_id=uuid4(), occurred_at=AT,
        ))
        session.add(CurriculumGraphNode(
            id=uuid4(), graph_id=source["graph_id"], stable_node_id=source["topic_id"],
            node_type="TOPIC", label="Topic", source="USER_DEFINED", confidence=1.0,
        ))
        session.add(CurriculumGraphMapping(
            id=uuid4(), graph_id=source["graph_id"], mapping_id=uuid4(),
            topic_id=source["topic_id"], concept_id=source["concept_id"],
            mapping_kind="EXPLICIT", source="USER_DEFINED", confidence=1.0, verified=True,
        ))
    value = LearningSessionSnapshot(
        session_id=source["session_id"], learner_id=source["actor_id"],
        course_id=source["course_id"], state=SessionState.CREATED, version=1,
        graph_version_id=source["graph_id"], current_topic_id=source["topic_id"],
        last_event_id=source["event_id"], created_at=AT, updated_at=AT,
    )
    return source, value


async def create_source(database, value):
    async with database.session() as session, session.begin():
        return await create_learning_session(session, value)


async def test_session_create_is_concurrent_retry_safe_and_requires_caller_transaction(
    live_database, repository_source,
):
    _, value = repository_source
    async with live_database.session() as session:
        with pytest.raises(RuntimeValidationError, match="explicit caller"):
            await create_learning_session(session, value)
    first, second = await asyncio.gather(
        create_source(live_database, value), create_source(live_database, value),
    )
    assert first == second == value
    async with live_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(LearningSessionRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(RuntimeOperationRecord)) == 1


async def test_session_exact_retry_preserves_old_result_after_head_advances(
    live_database, repository_source,
):
    source, value = repository_source
    await create_source(live_database, value)
    event_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(LearningEventRecord(
            event_id=event_id, event_type="PLAN_REPLANNED", actor_subject="mastery-actor",
            learner_identity_id=source["actor_id"], course_id=source["course_id"],
            payload={}, correlation_id=uuid4(),
        ))
        await session.flush()
        transition = SessionTransition(
            session_id=value.session_id, event_id=event_id, from_state=SessionState.CREATED,
            to_state=SessionState.PLANNING, from_version=1, to_version=2,
            occurred_at=AT + timedelta(seconds=1),
        )
        changed = await transition_learning_session(session, value.learner_id, transition)
    async with live_database.session() as session, session.begin():
        assert await create_learning_session(session, value) == value
        assert await transition_learning_session(session, value.learner_id, transition) == changed
        current = await get_learning_session(session, value.learner_id, value.session_id)
        assert current.version == 2
        with pytest.raises(RuntimeConflictError):
            await create_learning_session(session, value.model_copy(update={
                "updated_at": changed.updated_at,
            }))
        stale = transition.model_copy(update={"event_id": uuid4()})
        with pytest.raises(RuntimeStaleError):
            await transition_learning_session(session, value.learner_id, stale)


async def test_failed_caller_transaction_rolls_back_session_and_retry_receipt(
    live_database, repository_source,
):
    _, value = repository_source
    with pytest.raises(RuntimeError, match="crash"):
        async with live_database.session() as session, session.begin():
            await create_learning_session(session, value)
            raise RuntimeError("crash before commit")
    async with live_database.session() as session:
        assert await get_learning_session(session, value.learner_id, value.session_id) is None
        assert await session.scalar(select(func.count()).select_from(RuntimeOperationRecord)) == 0
    assert await create_source(live_database, value) == value


async def test_supplied_plan_storage_does_not_publish_and_is_immutable_on_retry(
    live_database, repository_source,
):
    source, value = repository_source
    await create_source(live_database, value)
    plan = plan_contract(
        session_id=value.session_id, learner_id=value.learner_id, course_id=value.course_id,
        source_event_id=source["event_id"],
    )
    async with live_database.session() as session, session.begin():
        assert await store_plan_version(session, plan) == plan
    async with live_database.session() as session, session.begin():
        assert await store_plan_version(session, plan) == plan
        stored = await get_plan_version(session, value.learner_id, plan.identity.plan_version_id)
        assert stored == plan
        current = await get_learning_session(session, value.learner_id, value.session_id)
        assert current.current_plan_version_id is None
        with pytest.raises(RuntimeConflictError):
            await store_plan_version(session, plan.model_copy(update={
                "mastery_policy_version": "different",
            }))


async def test_execution_terminal_result_and_stale_new_update_are_protected(
    live_database, repository_source,
):
    source, value = repository_source
    await create_source(live_database, value)
    plan = plan_contract(
        session_id=value.session_id, learner_id=value.learner_id,
        course_id=value.course_id, source_event_id=source["event_id"],
    )
    pending = ExecutionReceipt(
        identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id), plan=plan,
        state=ExecutionState.PENDING, version=1, created_at=AT,
    )
    async with live_database.session() as session, session.begin():
        await store_plan_version(session, plan)
        await record_execution_receipt(session, pending, event_id=source["event_id"])
    completed = pending.model_copy(update={
        "state": ExecutionState.COMPLETED, "version": 2, "completed_at": AT,
        "result_bytes": b'{"original":true}',
    })
    completion_event = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(LearningEventRecord(
            event_id=completion_event, event_type="SESSION_STARTED", actor_subject="mastery-actor",
            learner_identity_id=value.learner_id, course_id=value.course_id,
            payload={}, correlation_id=uuid4(),
        ))
        await session.flush()
        await record_execution_receipt(
            session, completed, event_id=completion_event, expected_version=1,
        )
    async with live_database.session() as session, session.begin():
        original = await record_execution_receipt(session, pending, event_id=source["event_id"])
        assert original == pending
        assert await record_execution_receipt(
            session, completed, event_id=completion_event, expected_version=1,
        ) == completed
        rejection_event = uuid4()
        session.add(LearningEventRecord(
            event_id=rejection_event, event_type="SESSION_STARTED", actor_subject="mastery-actor",
            learner_identity_id=value.learner_id, course_id=value.course_id,
            payload={}, correlation_id=uuid4(),
        ))
        await session.flush()
        with pytest.raises(RuntimeStaleError):
            await record_execution_receipt(
                session, completed.model_copy(update={"version": 3}),
                event_id=rejection_event, expected_version=2,
            )


async def test_diagnostic_first_reservation_race_reuses_original_budget_slot(
    live_database, repository_source,
):
    source, value = repository_source
    await create_source(live_database, value)
    plan = plan_contract(session_id=value.session_id, learner_id=value.learner_id,
                         course_id=value.course_id, source_event_id=source["event_id"])
    execution = ExecutionReceipt(
        identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id), plan=plan,
        state=ExecutionState.PENDING, version=1, created_at=AT,
    )
    run = DiagnosticRunSnapshot(
        diagnostic=DiagnosticState(
            diagnostic_run_id=uuid4(), learner_id=value.learner_id, course_id=value.course_id,
            graph_version_id=source["graph_id"], diagnostic_policy_version="review_diagnostic_v1",
            item_budget=1, remaining_item_budget=1,
        ), session_id=value.session_id,
        source=SourceIdentity(kind=SourceKind.EVENT, source_id=source["event_id"]),
        source_event_id=source["event_id"], state=DiagnosticRunState.OPEN, version=1, created_at=AT,
    )
    async with live_database.session() as session, session.begin():
        await store_plan_version(session, plan)
        await record_execution_receipt(session, execution, event_id=source["event_id"])
        await create_diagnostic_run(session, run)
    arguments = dict(
        run_id=run.diagnostic.diagnostic_run_id, reservation_id=uuid4(),
        execution_id=execution.identity.execution_id,
        question_version_id=source["question_version_id"],
        target_concept_id=source["concept_id"], expected_run_version=1, reserved_at=AT,
    )

    async def reserve():
        async with live_database.session() as session, session.begin():
            return await reserve_diagnostic_question(
                session, value.learner_id, value.session_id, **arguments,
            )

    left, right = await asyncio.gather(reserve(), reserve())
    assert left == right and left.slot == 1
    async with live_database.session() as session, session.begin():
        with pytest.raises(RuntimeConflictError):
            await reserve_diagnostic_question(
                session, value.learner_id, value.session_id,
                **{**arguments, "reservation_id": uuid4()},
            )
