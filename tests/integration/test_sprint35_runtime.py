"""Live PostgreSQL coverage for Sprint 3.5 schedule and event boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.domain.adaptation import SelfReportAssertion
from packages.domain.enums import LearningEventType
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.persistence import (
    LearningEventConceptAssociation,
    LearningEventRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    SelfReportAssertionRecord,
    apply_evidence,
    apply_self_report,
    emit_review_due,
    get_review_schedule,
    process_due_reviews,
    select_persisted_review_candidates,
)
from tests.integration.test_mastery_runtime import _evidence, _source_context

pytestmark = pytest.mark.live_integration


async def test_self_report_prior_replays_with_confidence_and_is_idempotent(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    assertion = SelfReportAssertion(
        assertion_id=uuid4(),
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        actor_id=source["actor_id"],  # type: ignore[arg-type]
        course_id=source["course_id"],  # type: ignore[arg-type]
        stable_concept_id=source["concept_id"],  # type: ignore[arg-type]
        graph_version_id=source["graph_id"],  # type: ignore[arg-type]
        occurred_at=source["occurred_at"],  # type: ignore[arg-type]
        idempotency_key="self-report:one",
        policy_version="review_diagnostic_v1",
    )
    async with live_database.session() as session, session.begin():
        first = await apply_self_report(session, assertion, actor_subject="mastery-actor")
        duplicate = await apply_self_report(session, assertion, actor_subject="mastery-actor")
    assert first.duplicate is False
    assert duplicate.projection_ids == first.projection_ids
    async with live_database.session() as session:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == source["actor_id"],
            MasteryProjectionHead.course_id == source["course_id"],
        ))
        assert head is not None
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
        count = await session.scalar(select(func.count()).select_from(SelfReportAssertionRecord))
    assert revision is not None
    assert revision.alpha == pytest.approx(2.0)
    assert revision.beta == pytest.approx(1.0)
    assert revision.confidence == pytest.approx(0.2)
    assert count == 1


async def test_grading_event_seeds_schedule_and_due_event_is_non_impact(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    event = ConceptLearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=source["actor_id"],  # type: ignore[arg-type]
        actor_subject="mastery-actor",
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        course_id=source["course_id"],  # type: ignore[arg-type]
        occurred_at=evidence.occurred_at,
        payload=LearningEventPayload(
            kind="answer_graded",
            data={"graph_version_id": str(source["graph_id"])},
        ),
        correlation_id=uuid4(),
        idempotency_key="grading-event:one",
        stable_concept_ids=(source["concept_id"],),  # type: ignore[arg-type]
        source_evidence_id=evidence.evidence_id,
        source_attempt_id=evidence.attempt_id,
    )
    async with live_database.session() as session, session.begin():
        await apply_evidence(
            session,
            evidence,
            actor_subject="mastery-actor",
            concept_event=event,
        )
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            source["concept_id"],  # type: ignore[arg-type]
        )
        assert schedule is not None
        assert schedule.due_at == evidence.occurred_at + timedelta(days=1)
        candidates = await select_persisted_review_candidates(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            as_of=evidence.occurred_at + timedelta(days=1, seconds=1),
        )
    assert candidates.candidates
    async with live_database.session() as session, session.begin():
        await emit_review_due(
            session,
            schedule,
            candidates.candidates[0],
            actor_id=source["actor_id"],  # type: ignore[arg-type]
            actor_subject="mastery-actor",
            occurred_at=datetime.now(UTC),
        )
    async with live_database.session() as session:
        due_event = await session.scalar(select(LearningEventRecord).where(
            LearningEventRecord.event_type == LearningEventType.REVIEW_DUE.value,
        ))
        assert due_event is not None
        association_count = await session.scalar(select(func.count()).where(
            LearningEventConceptAssociation.event_id == due_event.event_id,
        ))
    assert association_count == 0


async def test_due_retry_preserves_original_envelope_across_time(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    event = ConceptLearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=source["actor_id"],  # type: ignore[arg-type]
        actor_subject="mastery-actor",
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        course_id=source["course_id"],  # type: ignore[arg-type]
        occurred_at=evidence.occurred_at,
        payload=LearningEventPayload(
            kind="answer_graded", data={"graph_version_id": str(source["graph_id"])},
        ),
        correlation_id=uuid4(),
        idempotency_key="grading-event:due-retry",
        stable_concept_ids=(source["concept_id"],),  # type: ignore[arg-type]
        source_evidence_id=evidence.evidence_id,
        source_attempt_id=evidence.attempt_id,
    )
    async with live_database.session() as session, session.begin():
        await apply_evidence(
            session, evidence, actor_subject="mastery-actor", concept_event=event,
        )
    as_of = evidence.occurred_at + timedelta(days=1, seconds=1)
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session, source["actor_id"], source["course_id"], source["concept_id"],  # type: ignore[arg-type]
        )
    assert schedule is not None
    async with live_database.session() as session, session.begin():
        first = await process_due_reviews(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            as_of=as_of,
            actor_id=source["actor_id"],  # type: ignore[arg-type]
            actor_subject="mastery-actor",
        )
    later = as_of + timedelta(days=2)
    async with live_database.session() as session, session.begin():
        second = await process_due_reviews(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            as_of=later,
            actor_id=source["actor_id"],  # type: ignore[arg-type]
            actor_subject="mastery-actor",
        )
    assert len(first) == len(second) == 1
    assert second[0].event_id == first[0].event_id
    assert second[0].correlation_id == first[0].correlation_id
    assert second[0].occurred_at == first[0].occurred_at
    assert second[0].payload == first[0].payload


async def test_concurrent_due_emission_converges_to_one_event(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    event = ConceptLearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=source["actor_id"],  # type: ignore[arg-type]
        actor_subject="mastery-actor",
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        course_id=source["course_id"],  # type: ignore[arg-type]
        occurred_at=evidence.occurred_at,
        payload=LearningEventPayload(kind="answer_graded", data={}),
        correlation_id=uuid4(),
        idempotency_key="grading-event:concurrent-due",
        stable_concept_ids=(source["concept_id"],),  # type: ignore[arg-type]
        source_evidence_id=evidence.evidence_id,
        source_attempt_id=evidence.attempt_id,
    )
    async with live_database.session() as session, session.begin():
        await apply_evidence(
            session, evidence, actor_subject="mastery-actor", concept_event=event,
        )
    as_of = evidence.occurred_at + timedelta(days=1, seconds=1)

    async def emit_once():
        async with live_database.session() as session, session.begin():
            return await process_due_reviews(
                session,
                source["actor_id"],  # type: ignore[arg-type]
                source["course_id"],  # type: ignore[arg-type]
                as_of=as_of,
                actor_id=source["actor_id"],  # type: ignore[arg-type]
                actor_subject="mastery-actor",
            )

    first, second = await asyncio.gather(emit_once(), emit_once())
    assert len(first) == len(second) == 1
    assert first[0].event_id == second[0].event_id
    async with live_database.session() as session:
        count = await session.scalar(select(func.count()).where(
            LearningEventRecord.event_id == first[0].event_id,
        ))
    assert count == 1
