"""Durable job events, replay, SSE authorization and recovery integration tests."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.auth.jwt import JWTService
from apps.api.jobs import stream_job_events
from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import (
    JobCreatedPayload,
    JobEventType,
    JobStagePayload,
)
from packages.persistence import Course, CourseMember, Job
from packages.persistence.job_events import (
    append_event,
    events_after,
    job_snapshot,
)
from packages.persistence.job_wakeups import wait_for_job_events
from packages.persistence.jobs import JobRepository

pytestmark = pytest.mark.live_integration
LANES = (JobLane.INTERACTIVE, JobLane.PREFETCH, JobLane.BATCH)


@pytest.fixture
async def event_repository(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)
    return JobRepository(live_database, retry_base=0.01, retry_max=0.04)


@pytest.fixture
def insert_event_job(event_repository):
    async def insert(*, course_id: UUID | None = None):
        course_id = course_id or uuid4()
        job = Job(
            id=uuid4(), job_type="fake", payload={"course_id": str(course_id)},
            idempotency_key=str(uuid4()), lane="batch", max_attempts=3,
        )
        async with event_repository.database.session() as session, session.begin():
            session.add(Course(id=course_id, title="Event course"))
            session.add(CourseMember(course_id=course_id, subject="fixture-student"))
            session.add(job)
            append_event(
                session, job, JobEventType.CREATED,
                JobCreatedPayload(job_type=job.job_type), attempt=0, idempotency_key="created",
            )
        return job.id, course_id

    return insert


async def test_progress_events_are_ordered_atomic_and_replayable(
    event_repository, insert_event_job,
):
    job_id, _ = await insert_event_job()
    claim = await event_repository.claim("worker-one", LANES, 60)
    assert claim is not None
    assert await event_repository.report_progress(
        claim, JobEventType.STAGE_STARTED,
        JobStagePayload(stage="extracting", progress_percent=10),
        "attempt:1:stage:extracting:started",
    )
    assert await event_repository.report_progress(
        claim, JobEventType.STAGE_STARTED,
        JobStagePayload(stage="extracting", progress_percent=10),
        "attempt:1:stage:extracting:started",
    )
    assert await event_repository.finish(claim, JobStatus.SUCCEEDED, result_ref="safe-ref")

    events = await events_after(event_repository.database, job_id, 0)
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert [event.type for event in events] == [
        JobEventType.CREATED, JobEventType.STARTED,
        JobEventType.STAGE_STARTED, JobEventType.COMPLETED,
    ]
    snapshot = await job_snapshot(event_repository.database, job_id)
    assert snapshot is not None
    assert snapshot.status == JobStatus.SUCCEEDED
    assert snapshot.progress.stage == "extracting"
    assert snapshot.progress.progress_percent == 10
    assert snapshot.result_available is True
    assert snapshot.latest_event_sequence == 4
    assert (await events_after(event_repository.database, job_id, 2))[0].sequence == 3


async def test_progress_write_is_atomic_with_job_snapshot(event_repository, insert_event_job):
    job_id, _ = await insert_event_job()
    claim = await event_repository.claim("worker-one", LANES, 60)

    def fail_before_commit(session):
        session.connection().execute(text("SELECT 1 / 0"))

    event.listen(Session, "before_commit", fail_before_commit)
    try:
        with pytest.raises(DBAPIError):
            await event_repository.report_progress(
                claim, JobEventType.PROGRESS_UPDATED,
                JobStagePayload(stage="extracting", progress_percent=50),
                "attempt:1:stage:extracting:progress:50",
            )
    finally:
        event.remove(Session, "before_commit", fail_before_commit)
    snapshot = await job_snapshot(event_repository.database, job_id)
    assert snapshot is not None
    assert snapshot.latest_event_sequence == 2
    assert snapshot.progress.stage is None
    assert [event.type for event in await events_after(event_repository.database, job_id, 0)] == [
        JobEventType.CREATED, JobEventType.STARTED,
    ]


async def test_recovery_and_stale_attempts_are_fenced(event_repository, insert_event_job):
    job_id, _ = await insert_event_job()
    stale = await event_repository.claim("worker-one", LANES, 60)
    assert stale is not None
    async with event_repository.database.session() as session, session.begin():
        await session.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        )
    async with event_repository.database.session() as session, session.begin():
        job = await session.get(Job, job_id)
        assert job is not None
        job.lease_expires_at = job.updated_at
    assert await event_repository.reap() == 1
    async with event_repository.database.session() as session, session.begin():
        job = await session.get(Job, job_id)
        assert job is not None
        job.run_after = job.updated_at
    replacement = await event_repository.claim("worker-two", LANES, 60)
    assert replacement is not None and replacement.attempts == 2
    assert not await event_repository.report_progress(
        stale, JobEventType.PROGRESS_UPDATED,
        JobStagePayload(stage="stale", progress_percent=99),
        "attempt:1:stage:stale:progress:99",
    )
    assert await event_repository.report_progress(
        replacement, JobEventType.PROGRESS_UPDATED,
        JobStagePayload(stage="replacement", progress_percent=25),
        "attempt:2:stage:replacement:progress:25",
    )
    events = await events_after(event_repository.database, job_id, 0)
    assert [event.type for event in events] == [
        JobEventType.CREATED, JobEventType.STARTED, JobEventType.RECOVERED,
        JobEventType.RETRY_SCHEDULED, JobEventType.STARTED, JobEventType.PROGRESS_UPDATED,
    ]
    assert all(event.payload.get("stage") != "stale" for event in events)


async def test_snapshot_and_sse_replay_are_authenticated(
    event_repository, insert_event_job, async_http_client, auth_headers, test_settings,
):
    job_id, course_id = await insert_event_job()
    claim = await event_repository.claim("worker-one", LANES, 60)
    assert claim is not None
    await event_repository.report_progress(
        claim, JobEventType.PROGRESS_UPDATED,
        JobStagePayload(stage="complete", progress_percent=100),
        "attempt:1:stage:complete:progress:100",
    )
    await event_repository.finish(claim, JobStatus.SUCCEEDED, result_ref="safe-ref")

    snapshot = await async_http_client.get(f"/api/v3/jobs/{job_id}", headers=auth_headers)
    assert snapshot.status_code == 200
    assert snapshot.json()["result_available"] is True
    assert "result_ref" not in snapshot.json()
    assert (await async_http_client.get(
        f"/api/v3/jobs/{job_id}/events", headers=auth_headers,
    )).headers["content-type"].startswith("text/event-stream")
    async with async_http_client.stream(
        "GET", f"/api/v3/jobs/{job_id}/events", headers=auth_headers,
    ) as response:
        body = (await response.aread()).decode()
    assert response.status_code == 200
    assert "event: job.created" in body
    assert "event: job.completed" in body
    assert "safe-ref" not in body
    async with async_http_client.stream(
        "GET", f"/api/v3/jobs/{job_id}/events",
        headers={**auth_headers, "Last-Event-ID": "2"},
    ) as response:
        replay = (await response.aread()).decode()
    assert "id: 1\n" not in replay and "id: 2\n" not in replay
    assert "event: job.progress_updated" in replay
    assert "event: job.completed" in replay
    invalid = await async_http_client.get(
        f"/api/v3/jobs/{job_id}/events",
        headers={**auth_headers, "Last-Event-ID": "not-a-number"},
    )
    assert invalid.status_code == 400
    other = JWTService(test_settings).create_access_token("not-a-member")
    forbidden = await async_http_client.get(
        f"/api/v3/jobs/{job_id}", headers={"Authorization": f"Bearer {other}"},
    )
    assert forbidden.status_code == 403
    assert course_id


async def test_sse_replay_to_live_handoff_polls_postgres_when_redis_hint_is_lost(
    event_repository, insert_event_job, test_app, auth_identity, async_http_client, monkeypatch,
):
    job_id, _ = await insert_event_job()
    claim = await event_repository.claim("worker-one", LANES, 60)
    assert claim is not None
    import apps.api.jobs as jobs_api

    waiting = asyncio.Event()
    release = asyncio.Event()

    async def lost_hint(*args, **kwargs):
        waiting.set()
        await release.wait()
        return False

    monkeypatch.setattr(jobs_api, "wait_for_job_events", lost_hint)

    class RequestStub:
        app = test_app

        async def is_disconnected(self):
            return False

    response = await stream_job_events(job_id, RequestStub(), auth_identity)
    iterator = response.body_iterator
    assert "id: 1\n" in await anext(iterator)
    assert "id: 2\n" in await anext(iterator)
    assert await anext(iterator) == ": keepalive\n\n"
    pending = asyncio.create_task(anext(iterator))
    await waiting.wait()
    assert await event_repository.report_progress(
        claim, JobEventType.PROGRESS_UPDATED,
        JobStagePayload(stage="live", progress_percent=50),
        "attempt:1:stage:live:progress:50",
    )
    release.set()
    frame = await asyncio.wait_for(pending, 2)
    assert "event: job.progress_updated" in frame
    await iterator.aclose()


async def test_redis_unavailable_does_not_block_postgres_event_replay(live_database):
    from packages.persistence.redis import RedisClient

    redis = RedisClient("redis://127.0.0.1:1/0")
    try:
        assert await wait_for_job_events(redis, uuid4(), timeout=0.05) is False
    finally:
        await redis.close()
