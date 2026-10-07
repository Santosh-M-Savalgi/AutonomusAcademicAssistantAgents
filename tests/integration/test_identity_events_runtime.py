"""PostgreSQL identity, learning-event and transaction-boundary coverage."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.domain.enums import JobLane, LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload
from packages.persistence.identities import resolve_student_identity
from packages.persistence.job_creation import (
    JobIdempotencyConflictError,
    create_job_in_transaction,
)
from packages.persistence.learning_events import (
    LearningEventConflictError,
    LegacyLearningEventError,
    event_from_record,
    insert_learning_event,
    list_learning_events,
)
from packages.persistence.models import Course, Job, LearningEventRecord, StudentIdentity

pytestmark = pytest.mark.live_integration


async def identity(database, subject: str):
    async with database.session() as session, session.begin():
        return await resolve_student_identity(session, "jwt:test:api", subject)


def event_for(
    actor_id, *, key: str, occurred_at: datetime, actor_subject: str = "opaque-actor",
    learner_id=None, course_id=None,
):
    return LearningEventInput(
        event_id=uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=actor_id,
        actor_subject=actor_subject,
        learner_id=learner_id or actor_id,
        course_id=course_id or uuid4(),
        occurred_at=occurred_at,
        payload=LearningEventPayload(
            kind="answer_graded",
            data={"correct": 1.0, "question_id": str(uuid4())},
        ),
        correlation_id=uuid4(),
        idempotency_key=key,
    )


async def test_identity_resolution_is_stable_and_concurrency_safe(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    first = await identity(live_database, "opaque-subject")
    second = await identity(live_database, "opaque-subject")
    other = await identity(live_database, "other-subject")
    assert first.id == second.id
    assert first.id != other.id
    assert first.external_subject == "opaque-subject"

    async def resolve_once():
        async with live_database.session() as session, session.begin():
            return await resolve_student_identity(session, "jwt:test:api", "racing-subject")

    results = await asyncio.gather(*(resolve_once() for _ in range(4)))
    assert len({result.id for result in results}) == 1
    async with live_database.session() as session:
        assert await session.scalar(
            select(func.count()).select_from(StudentIdentity).where(
                StudentIdentity.external_subject == "racing-subject",
            )
        ) == 1


async def test_event_insert_is_caller_transactional_and_idempotent(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    actor = await identity(live_database, "event-actor")
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Event course"))
    event = event_for(
        actor.id, actor_subject="event-actor", key="event-idempotency", course_id=course_id,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    async with live_database.session() as session, session.begin():
        first = await insert_learning_event(session, event)
        second = await insert_learning_event(session, event)
        assert first.event_id == second.event_id

    async with live_database.session() as session:
        rows = await list_learning_events(session, learner_id=actor.id)
        assert len(rows) == 1
        decoded = event_from_record(rows[0])
        assert decoded.event_id == event.event_id
        assert decoded.recorded_at >= decoded.occurred_at

    conflict = event.model_copy(update={"event_id": uuid4()})
    async with live_database.session() as session, session.begin():
        with pytest.raises(LearningEventConflictError):
            await insert_learning_event(session, conflict)

    subject_conflict = event.model_copy(update={"actor_subject": "different-subject"})
    async with live_database.session() as session, session.begin():
        with pytest.raises(ValueError, match="authenticated subject"):
            await insert_learning_event(session, subject_conflict)


async def test_concurrent_duplicate_event_insertions_converge(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    actor = await identity(live_database, "concurrent-event-actor")
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Concurrent event course"))
    event = event_for(
        actor.id, actor_subject="concurrent-event-actor", key="concurrent-event",
        course_id=course_id,
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    async def insert_once():
        async with live_database.session() as session, session.begin():
            return await insert_learning_event(session, event)

    rows = await asyncio.gather(insert_once(), insert_once())
    assert {row.event_id for row in rows} == {event.event_id}
    async with live_database.session() as session:
        assert await session.scalar(
            select(func.count()).select_from(LearningEventRecord).where(
                LearningEventRecord.idempotency_key == "concurrent-event",
            )
        ) == 1


async def test_event_and_domain_change_roll_back_together(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    actor = await identity(live_database, "rollback-event-actor")
    course_id = uuid4()
    event = event_for(
        actor.id, actor_subject="rollback-event-actor", key="rollback-event",
        occurred_at=datetime.now(UTC),
    )
    event = event.model_copy(update={"course_id": course_id})
    with pytest.raises(RuntimeError, match="rollback"):
        async with live_database.session() as session, session.begin():
            session.add(Course(id=course_id, title="Rolled back course"))
            await insert_learning_event(session, event)
            raise RuntimeError("rollback")

    async with live_database.session() as session:
        assert await session.get(Course, course_id) is None
        assert await session.get(LearningEventRecord, event.event_id) is None


async def test_legacy_event_rows_are_not_reinterpreted_as_v1(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    event_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(LearningEventRecord(
            event_id=event_id,
            event_type="SYLLABUS_UPLOADED",
            actor_subject="legacy-subject",
            payload={"document_id": str(uuid4())},
            correlation_id=uuid4(),
        ))
    async with live_database.session() as session:
        row = await session.get(LearningEventRecord, event_id)
        assert row is not None
        assert row.event_schema_version is None
        with pytest.raises(LegacyLearningEventError):
            event_from_record(row)


async def test_transactional_job_creation_is_atomic_and_conflict_safe(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    job_id = uuid4()
    payload = {"course_id": str(uuid4()), "kind": "synthetic"}
    async with live_database.session() as session, session.begin():
        first = await create_job_in_transaction(
            session,
            job_id=job_id,
            job_type="synthetic_event_job",
            payload=payload,
            idempotency_key="job-idempotency",
            lane=JobLane.BATCH,
        )
        second = await create_job_in_transaction(
            session,
            job_id=job_id,
            job_type="synthetic_event_job",
            payload=payload,
            idempotency_key="job-idempotency",
            lane=JobLane.BATCH,
        )
        assert first.id == second.id

    async with live_database.session() as session:
        assert await session.get(Job, job_id) is not None

    with pytest.raises(JobIdempotencyConflictError):
        async with live_database.session() as session, session.begin():
            await create_job_in_transaction(
                session,
                job_id=uuid4(),
                job_type="synthetic_event_job",
                payload={"different": True},
                idempotency_key="job-idempotency",
            )

    rollback_job = uuid4()
    with pytest.raises(RuntimeError, match="job rollback"):
        async with live_database.session() as session, session.begin():
            await create_job_in_transaction(
                session,
                job_id=rollback_job,
                job_type="synthetic_event_job",
                payload={},
                idempotency_key="rollback-job",
            )
            raise RuntimeError("job rollback")
    async with live_database.session() as session:
        assert await session.get(Job, rollback_job) is None


async def test_event_order_is_deterministic(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    actor = await identity(live_database, "ordered-event-actor")
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Ordered event course"))
    later = datetime(2026, 1, 3, tzinfo=UTC)
    earlier = later - timedelta(days=1)
    async with live_database.session() as session, session.begin():
        await insert_learning_event(
            session, event_for(
                actor.id, actor_subject="ordered-event-actor", key="ordered-later",
                course_id=course_id, occurred_at=later,
            ),
        )
        await insert_learning_event(
            session, event_for(
                actor.id, actor_subject="ordered-event-actor", key="ordered-earlier",
                course_id=course_id, occurred_at=earlier,
            ),
        )
    async with live_database.session() as session:
        rows = await list_learning_events(session, learner_id=actor.id)
        assert [row.idempotency_key for row in rows] == ["ordered-earlier", "ordered-later"]
