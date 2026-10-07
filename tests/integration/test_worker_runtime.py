"""Real PostgreSQL ownership, concurrency, recovery and fault-injection tests."""

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from apps.worker.handlers import HandlerFailure
from apps.worker.runner import Worker
from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import JobErrorCode, JobEventType
from packages.persistence import Job, JobProgressEvent, RedisClient
from packages.persistence.job_wakeups import JOB_WAKEUP_CHANNEL, RedisWakeups, notify_jobs
from packages.persistence.jobs import JobRepository

pytestmark = pytest.mark.live_integration
LANES = (JobLane.INTERACTIVE, JobLane.PREFETCH, JobLane.BATCH)


@pytest.fixture
async def repository(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)
    return JobRepository(live_database, retry_base=0.01, retry_max=0.04)


@pytest.fixture
def insert_job(repository):
    async def insert(**overrides):
        values = dict(
            id=uuid4(), job_type="fake", payload={"document_id": "synthetic"},
            idempotency_key=str(uuid4()),
        )
        values.update(overrides)
        job = Job(**values)
        async with repository.database.session() as session, session.begin():
            session.add(job)
        return job.id
    return insert


async def read_job(repository, job_id):
    async with repository.database.session() as session:
        return await session.get(Job, job_id)


async def expire(repository, job_id):
    async with repository.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == job_id).values(
            lease_expires_at=func.clock_timestamp() - timedelta(seconds=1)
        ))


async def due_now(repository, job_id):
    async with repository.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == job_id).values(
            run_after=func.clock_timestamp() - timedelta(seconds=1)
        ))


async def test_claim_is_committed_and_attempts_increment(repository, insert_job):
    job_id = await insert_job()
    claim = await repository.claim("one", LANES, 60)
    row = await read_job(repository, job_id)
    assert claim.id == job_id
    assert row.status == "RUNNING"
    assert row.attempts == 1
    assert row.locked_by == "one"
    assert row.lease_expires_at > row.heartbeat_at
    assert await repository.claim("two", LANES, 60) is None


async def test_concurrent_claims_have_distinct_ownership(repository, insert_job):
    ids = {await insert_job() for _ in range(8)}
    start = asyncio.Event()

    async def claim(name):
        await start.wait()
        return await repository.claim(name, LANES, 60)

    tasks = [asyncio.create_task(claim(f"worker-{i}")) for i in range(8)]
    start.set()
    claims = await asyncio.gather(*tasks)
    assert {job.id for job in claims} == ids
    assert len({job.worker_id for job in claims}) == 8


async def test_locked_candidate_is_skipped_without_waiting(repository, insert_job):
    first = await insert_job(priority=100)
    second = await insert_job(priority=0)
    async with repository.database.session() as session, session.begin():
        await session.execute(select(Job).where(Job.id == first).with_for_update())
        claim = await asyncio.wait_for(repository.claim("other", LANES, 60), 2)
        assert claim.id == second


async def test_eligibility_priority_creation_ties_and_lanes(repository, insert_job):
    now = datetime.now(UTC)
    await insert_job(priority=999, run_after=now + timedelta(days=1))
    await insert_job(priority=999, attempts=3, max_attempts=3)
    await insert_job(priority=999, status="PARTIAL")
    await insert_job(priority=999, status="CANCELLED")
    await insert_job(priority=999, lane="interactive")
    newer = await insert_job(priority=10, created_at=now, status="RETRYING")
    older = await insert_job(priority=10, created_at=now - timedelta(seconds=5))
    lower = await insert_job(priority=1, created_at=now - timedelta(days=1))
    claims = [await repository.claim("one", (JobLane.BATCH,), 60) for _ in range(3)]
    assert [job.id for job in claims] == [older, newer, lower]
    assert await repository.claim("one", (JobLane.BATCH,), 60) is None


@pytest.mark.parametrize(("error", "attempts", "expected", "code"), [
    (None, 0, "SUCCEEDED", None),
    (HandlerFailure(JobErrorCode.RETRYABLE_FAILURE, retryable=True), 0,
     "RETRYING", "RETRYABLE_FAILURE"),
    (HandlerFailure(JobErrorCode.PERMANENT_FAILURE), 0, "FAILED", "PERMANENT_FAILURE"),
    (HandlerFailure(JobErrorCode.RETRYABLE_FAILURE, retryable=True), 2,
     "FAILED", "RETRYABLE_FAILURE"),
    (RuntimeError("Bearer private-token document contents"), 0, "RETRYING", "HANDLER_EXCEPTION"),
])
async def test_handler_outcomes(
    repository, insert_job, controlled_handler, worker_settings, error, attempts, expected, code,
):
    job_id = await insert_job(attempts=attempts)
    controlled_handler.failure = error
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)
    claim = await repository.claim(worker.worker_id, LANES, 60)
    await worker.execute(claim)
    row = await read_job(repository, job_id)
    assert row.status == expected
    assert row.error_code == code
    assert row.attempts == attempts + 1
    assert row.locked_by is row.lease_expires_at is row.heartbeat_at is None
    assert row.result_ref == ("synthetic-artifact" if expected == "SUCCEEDED" else None)
    if expected == "FAILED":
        async with repository.database.session() as session:
            events = (await session.scalars(select(JobProgressEvent).where(
                JobProgressEvent.job_id == job_id,
                JobProgressEvent.event_type == JobEventType.FAILED.value,
            ))).all()
        assert len(events) == 1
        assert events[0].payload["error_code"] == code
    if expected == "RETRYING":
        assert row.run_after > row.updated_at


async def test_unknown_job_type_fails_without_executing(repository, insert_job, worker_settings):
    job_id = await insert_job(job_type="unknown")
    worker = Worker(repository, {}, worker_settings)
    await worker.execute(await repository.claim(worker.worker_id, LANES, 60))
    row = await read_job(repository, job_id)
    assert row.status == "FAILED"
    assert row.error_code == "UNKNOWN_JOB_TYPE"


async def test_heartbeat_fences_worker_attempt_status_and_expiry(repository, insert_job):
    job_id = await insert_job()
    claim = await repository.claim("one", LANES, 3)
    assert not await repository.heartbeat(replace(claim, worker_id="two"), 60)
    assert await repository.heartbeat(claim, 60)
    row = await read_job(repository, job_id)
    assert row.lease_expires_at > claim.lease_expires_at
    assert await repository.reap() == 0
    assert not await repository.finish(replace(claim, worker_id="two"), JobStatus.SUCCEEDED)
    await expire(repository, job_id)
    assert not await repository.heartbeat(claim, 60)
    assert not await repository.finish(claim, JobStatus.SUCCEEDED)
    assert await repository.reap() == 1
    await due_now(repository, job_id)
    newer = await repository.claim("one", LANES, 60)
    assert newer.attempts == 2
    assert not await repository.heartbeat(claim, 60)  # Same worker, stale attempt.
    assert not await repository.finish(claim, JobStatus.SUCCEEDED)
    assert await repository.finish(newer, JobStatus.SUCCEEDED)
    assert not await repository.heartbeat(newer, 60)
    assert not await repository.finish(newer, JobStatus.FAILED)


async def test_reaper_is_concurrent_idempotent_and_exhaustion_aware(repository, insert_job):
    retry = await insert_job()
    exhausted = await insert_job(attempts=2)
    claims = [await repository.claim("dead", LANES, 60) for _ in range(2)]
    for job in claims:
        await expire(repository, job.id)
    counts = await asyncio.gather(repository.reap(), repository.reap())
    assert sum(counts) == 2
    assert await repository.reap() == 0
    for job_id, status in ((retry, "RETRYING"), (exhausted, "FAILED")):
        row = await read_job(repository, job_id)
        assert row.status == status
        assert row.error_code == "LEASE_EXPIRED"
        assert row.locked_by is row.heartbeat_at is row.lease_expires_at is None


async def test_reaper_skips_row_during_renewal_transaction(repository, insert_job):
    job_id = await insert_job()
    await repository.claim("one", LANES, 60)
    await expire(repository, job_id)
    async with repository.database.session() as session, session.begin():
        # Simulate a heartbeat holding the row lock while renewing its lease.
        await session.execute(update(Job).where(Job.id == job_id).values(
            lease_expires_at=func.clock_timestamp() + timedelta(seconds=60)
        ))
        assert await asyncio.wait_for(repository.reap(), 2) == 0
    assert await repository.reap() == 0


async def test_explicit_cancel_stops_running_handler(
    repository, insert_job, controlled_handler, worker_settings,
):
    job_id = await insert_job()
    controlled_handler.release.clear()
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)
    execution = asyncio.create_task(worker.execute(
        await repository.claim(worker.worker_id, LANES, 60)
    ))
    await controlled_handler.started.wait()
    assert await repository.cancel(job_id)
    await asyncio.wait_for(execution, 3)
    await asyncio.wait_for(controlled_handler.cancelled.wait(), 1)
    assert (await read_job(repository, job_id)).status == "CANCELLED"
    assert not await repository.cancel(job_id)


async def test_slow_handler_receives_periodic_heartbeat(
    repository, insert_job, controlled_handler, worker_settings, monkeypatch,
):
    job_id = await insert_job()
    renewed = asyncio.Event()
    heartbeat = repository.heartbeat

    async def observed(job, seconds):
        result = await heartbeat(job, seconds)
        renewed.set()
        return result

    monkeypatch.setattr(repository, "heartbeat", observed)
    controlled_handler.release.clear()
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)
    claim = await repository.claim(worker.worker_id, LANES, 1)
    execution = asyncio.create_task(worker.execute(claim))
    await asyncio.wait_for(renewed.wait(), 3)
    assert (await read_job(repository, job_id)).lease_expires_at > claim.lease_expires_at
    controlled_handler.release.set()
    await execution
    assert (await read_job(repository, job_id)).status == "SUCCEEDED"


async def test_completion_database_failure_leaves_recoverable_running_job(
    repository, insert_job, controlled_handler, worker_settings,
):
    job_id = await insert_job()
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)
    claim = await repository.claim(worker.worker_id, LANES, 60)

    def fail_before_commit(session):
        # Abort in real PostgreSQL AFTER the fenced SUCCEEDED update but BEFORE COMMIT.
        session.connection().execute(text("SELECT 1 / 0"))

    event.listen(Session, "before_commit", fail_before_commit)
    try:
        await worker.execute(claim)
    finally:
        event.remove(Session, "before_commit", fail_before_commit)
    assert (await read_job(repository, job_id)).status == "RUNNING"
    await expire(repository, job_id)
    assert await repository.reap() == 1
    assert (await read_job(repository, job_id)).status == "RETRYING"


async def test_heartbeat_database_failure_cancels_execution(
    repository, insert_job, controlled_handler, worker_settings, monkeypatch,
):
    job_id = await insert_job()
    controlled_handler.release.clear()
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)

    async def broken(*args):
        raise ConnectionError("private DB credentials")

    monkeypatch.setattr(repository, "heartbeat", broken)
    await asyncio.wait_for(worker.execute(
        await repository.claim(worker.worker_id, LANES, 60)
    ), 3)
    await asyncio.wait_for(controlled_handler.cancelled.wait(), 1)
    assert (await read_job(repository, job_id)).status == "RUNNING"
    await expire(repository, job_id)
    assert await repository.reap() == 1


@pytest.mark.parametrize("redis_unavailable", [True, False])
async def test_worker_polls_without_notifications(
    repository, insert_job, worker_settings, controlled_handler, monkeypatch, redis_unavailable,
):
    dead_redis = RedisClient("redis://127.0.0.1:1/0")
    worker = Worker(
        repository, {"fake": controlled_handler}, worker_settings,
        wakeups=RedisWakeups(dead_redis, timeout=0.1, reconnect=0.1) if redis_unavailable else None,
    )
    idle = asyncio.Event()
    claim = repository.claim
    finish = repository.finish

    async def observed_claim(*args):
        result = await claim(*args)
        if result is None:
            idle.set()
        return result

    async def observed_finish(*args, **kwargs):
        result = await finish(*args, **kwargs)
        worker.stop()
        return result

    monkeypatch.setattr(repository, "claim", observed_claim)
    monkeypatch.setattr(repository, "finish", observed_finish)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(idle.wait(), 3)
        job_id = await insert_job()
        if redis_unavailable:
            assert not await notify_jobs(dead_redis, timeout=0.1)
        # No usable wake notification: only polling can discover this insertion.
        await asyncio.wait_for(task, 5)
        assert (await read_job(repository, job_id)).status == "SUCCEEDED"
        assert len(controlled_handler.calls) == 1
    finally:
        worker.stop()
        await asyncio.wait_for(task, 3)
        await dead_redis.close()


async def test_duplicate_redis_wakeups_cannot_duplicate_execution(
    repository, insert_job, worker_settings, controlled_handler, live_redis, monkeypatch,
):
    worker_settings.poll_seconds = 20  # A real pub/sub wake is required after the first poll.
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings,
                    wakeups=RedisWakeups(live_redis, timeout=0.1))
    idle = asyncio.Event()
    original_claim, original_finish = repository.claim, repository.finish

    async def claim(*args):
        result = await original_claim(*args)
        if result is None:
            idle.set()
        return result

    async def finish(*args, **kwargs):
        result = await original_finish(*args, **kwargs)
        worker.stop()
        return result

    monkeypatch.setattr(repository, "claim", claim)
    monkeypatch.setattr(repository, "finish", finish)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(idle.wait(), 3)
        async with asyncio.timeout(3):
            # Wait for actual Redis subscription state, not an arbitrary sleep.
            while not (await live_redis.client.pubsub_numsub(JOB_WAKEUP_CHANNEL))[0][1]:
                await asyncio.sleep(0.01)
        job_id = await insert_job()
        assert await notify_jobs(live_redis)
        assert await notify_jobs(live_redis)
        await asyncio.wait_for(task, 3)
        assert (await read_job(repository, job_id)).attempts == 1
        assert len(controlled_handler.calls) == 1
    finally:
        worker.stop()
        await asyncio.wait_for(task, 3)


@pytest.mark.parametrize("cooperative", [False, True])
async def test_shutdown_stops_new_claims_and_retries_interrupted_work(
    repository, insert_job, controlled_handler, worker_settings, cooperative,
):
    first, second = await insert_job(priority=10), await insert_job(priority=0)
    controlled_handler.release.clear()
    async def handler(job, context):
        if cooperative:
            controlled_handler.calls.append(job)
            controlled_handler.started.set()
            await context.shutdown.wait()
            raise asyncio.CancelledError
        return await controlled_handler(job, context)

    worker = Worker(repository, {"fake": handler}, worker_settings)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(controlled_handler.started.wait(), 3)
    worker.stop()
    await asyncio.wait_for(task, 3)
    assert (await read_job(repository, first)).status == "RETRYING"
    assert (await read_job(repository, first)).error_code == "WORKER_SHUTDOWN"
    assert (await read_job(repository, second)).status == "PENDING"
    assert len(controlled_handler.calls) == 1


async def test_shutdown_allows_completion_within_grace(
    repository, insert_job, controlled_handler, worker_settings,
):
    job_id = await insert_job()
    controlled_handler.release.clear()
    worker = Worker(repository, {"fake": controlled_handler}, worker_settings)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(controlled_handler.started.wait(), 3)
    worker.stop()
    controlled_handler.release.set()
    await asyncio.wait_for(task, 3)
    assert (await read_job(repository, job_id)).status == "SUCCEEDED"


async def test_worker_concurrency_executes_distinct_handlers_in_parallel(
    repository, insert_job, worker_settings, controlled_handler,
):
    worker_settings.concurrency = 2
    ids = {await insert_job() for _ in range(2)}
    both_started = asyncio.Event()
    controlled_handler.release.clear()

    async def handler(job, context):
        # Calls are recorded synchronously before the first await in ControlledHandler.
        if len(controlled_handler.calls) == 1:
            both_started.set()
        return await controlled_handler(job, context)

    worker = Worker(repository, {"fake": handler}, worker_settings)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(both_started.wait(), 3)
        assert {job.id for job in controlled_handler.calls} == ids
        worker.stop()
        controlled_handler.release.set()
        await asyncio.wait_for(task, 3)
        for job_id in ids:
            assert (await read_job(repository, job_id)).status == "SUCCEEDED"
    finally:
        worker.stop()
        controlled_handler.release.set()
        await asyncio.wait_for(task, 3)


async def test_process_crash_leaves_job_for_reaper(
    repository, insert_job, service_settings,
):
    job_id = await insert_job()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.worker_process",
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DATABASE_URL": service_settings.database_url},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await asyncio.wait_for(process.stdout.readline(), 10) == b"HANDLER_STARTED\n"
        assert (await read_job(repository, job_id)).status == "RUNNING"
        process.kill()
        await process.wait()
        await expire(repository, job_id)
        assert await repository.reap() == 1
        await due_now(repository, job_id)
        reclaimed = await repository.claim("replacement", LANES, 60)
        assert reclaimed.id == job_id
        assert reclaimed.attempts == 2
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()


async def test_worker_cli_starts_and_stops_cleanly(repository, service_settings):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "apps.worker",
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DATABASE_URL": service_settings.database_url,
             "REDIS_URL": service_settings.redis_url, "WORKER_ENABLED": "true"},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        started = await asyncio.wait_for(process.stdout.readline(), 10)
        assert b'"event": "worker_started"' in started
        assert b'"service": "aaa-worker"' in started
        process.terminate()
        output, errors = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, errors
        assert b'"event": "worker_stopped"' in output
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
