"""Stage 4 trigger journal and Stage 5 coherent snapshot boundaries."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.domain.runtime import (
    LearningSessionSnapshot,
    SessionState,
    SessionTransition,
    SourceIdentity,
    SourceKind,
)
from packages.domain.runtime_state import TopicWindow
from packages.domain.triggers import (
    TriggerFacts,
    TriggerKind,
    TriggerSubmission,
)
from packages.persistence import (
    RuntimeStaleError,
    RuntimeTriggerRecord,
    apply_evidence,
    assemble_planning_snapshot,
    create_learning_session,
    evaluate_and_record_trigger,
    record_topic_window,
    recover_deferred_trigger,
    revalidate_planning_snapshot,
)
from packages.persistence.models import (
    CurriculumGraphMapping,
    CurriculumGraphNode,
    LearningEventRecord,
)
from packages.persistence.runtime import transition_learning_session
from tests.integration.test_mastery_runtime import _evidence, _source_context
from tests.unit.test_runtime_contracts import AT

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
            node_type="TOPIC", label="Topic", source="TEST", confidence=1.0,
        ))
        session.add(CurriculumGraphMapping(
            id=uuid4(), graph_id=source["graph_id"], mapping_id=uuid4(),
            topic_id=source["topic_id"], concept_id=source["concept_id"],
            mapping_kind="EXPLICIT", source="TEST", confidence=1.0, verified=True,
        ))
    return source, LearningSessionSnapshot(
        session_id=source["session_id"], learner_id=source["actor_id"],
        course_id=source["course_id"], state=SessionState.CREATED, version=1,
        graph_version_id=source["graph_id"], current_topic_id=source["topic_id"],
        last_event_id=source["event_id"], created_at=AT, updated_at=AT,
    )


def trigger_facts(source, session_id, session_version, *, kind=TriggerKind.BATCH_COMPLETED):
    source_id = source["event_id"]
    submission = TriggerSubmission(
        learner_id=source["actor_id"], session_id=session_id,
        source=SourceIdentity(kind=SourceKind.EVENT, source_id=source_id),
        source_event_id=source_id, kind=kind, expected_session_version=session_version,
        window_id=uuid4(), evidence_id=uuid4(),
    )
    return TriggerFacts(
        submission=submission, session_version=session_version,
        batch_completed=kind == TriggerKind.BATCH_COMPLETED,
        batch_is_quiz=True, batch_score=1, batch_item_count=3, gate_satisfied=True,
    )


async def test_trigger_journal_converges_concurrent_first_evaluations_and_retries(
    live_database, repository_source,
):
    source, value = repository_source
    async with live_database.session() as session, session.begin():
        await create_learning_session(session, value)
    facts = trigger_facts(source, value.session_id, 1)

    async def evaluate():
        async with live_database.session() as session, session.begin():
            return await evaluate_and_record_trigger(session, facts, as_of=AT)

    left, right = await asyncio.gather(evaluate(), evaluate())
    assert left == right and left.status.value == "ADMITTED"
    async with live_database.session() as session, session.begin():
        again = await evaluate_and_record_trigger(session, facts, as_of=AT + timedelta(seconds=10))
        assert again == left
        assert await session.scalar(select(func.count()).select_from(RuntimeTriggerRecord)) == 1


async def test_trigger_cooldown_is_durable_and_deferred_recovery_is_explicit(
    live_database, repository_source,
):
    source, value = repository_source
    async with live_database.session() as session, session.begin():
        await create_learning_session(session, value)
    first = trigger_facts(source, value.session_id, 1)
    async with live_database.session() as session, session.begin():
        await evaluate_and_record_trigger(session, first, as_of=AT)
    second = trigger_facts(source, value.session_id, 1)
    second = second.model_copy(update={"submission": second.submission.model_copy(update={
        "source": SourceIdentity(kind=SourceKind.EVENT, source_id=uuid4()),
        "source_event_id": source["event_id"],
    })})
    async with live_database.session() as session, session.begin():
        deferred = await evaluate_and_record_trigger(
            session, second, as_of=AT + timedelta(seconds=1),
        )
        assert deferred.status.value == "DEFERRED"
    async with live_database.session() as session, session.begin():
        recovered = await recover_deferred_trigger(
            session, second.submission.learner_id, second.submission.identity.trigger_id,
            second, as_of=AT + timedelta(seconds=60),
        )
        assert recovered.status.value == "ADMITTED"


async def test_snapshot_preserves_missing_projection_and_complete_freshness_boundary(
    live_database, repository_source,
):
    source, value = repository_source
    async with live_database.session() as session, session.begin():
        await create_learning_session(session, value)
        missing = await assemble_planning_snapshot(
            session, value.learner_id, value.session_id, as_of=AT,
        )
        assert "MISSING_PROJECTION" in {item.value for item in missing.guards}
    evidence = _evidence(source)
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor")
    async with live_database.session() as session, session.begin():
        event = TopicWindow(
            window_id=uuid4(), session_id=value.session_id, topic_id=value.current_topic_id,
            graph_version_id=source["graph_id"], version=1, event_id=source["event_id"],
            opened_at=AT, authorized=True, taught=False, prerequisites_evaluated=True,
            core_concept_ids=(source["concept_id"],),
        )
        await record_topic_window(session, value.learner_id, event, expected_session_version=1)
        complete = await assemble_planning_snapshot(
            session, value.learner_id, value.session_id, as_of=AT,
        )
        assert complete.evidence_count == 1
        assert complete.evidence_set_digest is not None
        assert complete.topic.topic_id == value.current_topic_id
        assert complete.canonical_bytes() == complete.canonical_bytes()
        assert len(complete.session_fingerprint) == 64


async def test_snapshot_fingerprint_is_stable_and_revalidation_rejects_newer_session(
    live_database, repository_source,
):
    source, value = repository_source
    async with live_database.session() as session, session.begin():
        await create_learning_session(session, value)
        first = await assemble_planning_snapshot(
            session, value.learner_id, value.session_id, as_of=AT,
        )
    event_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(LearningEventRecord(
            event_id=event_id, event_type="PLAN_REPLANNED", actor_subject="mastery-actor",
            learner_identity_id=value.learner_id, course_id=value.course_id,
            payload={}, correlation_id=uuid4(),
        ))
        await session.flush()
        await transition_learning_session(session, value.learner_id, SessionTransition(
            session_id=value.session_id, event_id=event_id, from_state=SessionState.CREATED,
            to_state=SessionState.PLANNING, from_version=1, to_version=2,
            occurred_at=AT + timedelta(seconds=1),
        ))
    async with live_database.session() as session, session.begin():
        with pytest.raises(RuntimeStaleError):
            await revalidate_planning_snapshot(session, first)
        second = await assemble_planning_snapshot(
            session, value.learner_id, value.session_id, as_of=AT,
        )
        assert second.session.version == 2
        assert second.session_fingerprint != first.session_fingerprint
