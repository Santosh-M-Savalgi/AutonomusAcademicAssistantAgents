"""Worker policy, dispatch, error safety and cancellation without external services."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from apps.worker.config import WorkerSettings
from apps.worker.handlers import HandlerFailure, HandlerResult
from apps.worker.runner import Worker
from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import (
    ClaimedJob,
    JobErrorCode,
    failure_status,
    retry_delay,
    validate_transition,
)
from packages.persistence.job_wakeups import JOB_WAKEUP_CHANNEL, notify_jobs
from packages.persistence.jobs import JobRepository, claim_query


@pytest.fixture
def store():
    repository = AsyncMock(spec=JobRepository)
    repository.finish.return_value = True
    repository.heartbeat.return_value = True
    repository.reap.return_value = 0
    repository.claim.return_value = None
    return repository


def claimed(worker: Worker, *, job_type: str = "fake") -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), type=job_type, payload={"document_id": "synthetic"},
        lane=JobLane.BATCH, priority=0, attempts=1, max_attempts=3,
        worker_id=worker.worker_id, lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )


@pytest.mark.parametrize(("source", "target"), [
    (JobStatus.PENDING, JobStatus.RUNNING), (JobStatus.RETRYING, JobStatus.RUNNING),
    *[(JobStatus.RUNNING, status) for status in JobStatus if status != JobStatus.PENDING
      and status != JobStatus.RUNNING],
    (JobStatus.PARTIAL, JobStatus.RETRYING),
])
def test_valid_transitions(source, target) -> None:
    validate_transition(source, target)


@pytest.mark.parametrize("source", [JobStatus.FAILED, JobStatus.SUCCEEDED, JobStatus.CANCELLED])
def test_terminal_states_cannot_be_resurrected(source) -> None:
    for target in JobStatus:
        with pytest.raises(ValueError):
            validate_transition(source, target)


def test_backoff_is_bounded_and_retry_limit_is_enforced() -> None:
    assert [retry_delay(attempt, 2, 10) for attempt in range(1, 7)] == [2, 4, 8, 10, 10, 10]
    assert retry_delay(10**9, 2, 300) == 300
    assert failure_status(2, 3, retryable=True) == JobStatus.RETRYING
    assert failure_status(3, 3, retryable=True) == JobStatus.FAILED
    assert failure_status(1, 3, retryable=False) == JobStatus.FAILED
    with pytest.raises(ValueError):
        retry_delay(0, 2, 10)


def test_claim_query_filters_eligibility_and_orders_before_lock() -> None:
    sql = str(claim_query((JobLane.BATCH,)).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "jobs.attempts < jobs.max_attempts" in sql
    assert "jobs.run_after <= clock_timestamp()" in sql
    assert "jobs.lane IN ('batch')" in sql
    assert "jobs.status IN ('PENDING', 'RETRYING')" in sql
    assert "ORDER BY jobs.priority DESC, jobs.created_at, jobs.id" in sql


@pytest.mark.parametrize("values", [
    {"heartbeat_seconds": 30}, {"concurrency": 0}, {"poll_seconds": 0},
    {"retry_max_seconds": 1}, {"lanes": ()}, {"io_timeout_seconds": 30},
])
def test_worker_config_rejects_unsafe_parameters(values) -> None:
    with pytest.raises(ValidationError):
        WorkerSettings(_env_file=None, **values)


def test_worker_identity_is_unique(store, worker_settings) -> None:
    first, second = Worker(store, {}, worker_settings), Worker(store, {}, worker_settings)
    assert first.worker_id != second.worker_id


async def test_success_dispatch(store, worker_settings, controlled_handler) -> None:
    worker = Worker(store, {"fake": controlled_handler}, worker_settings)
    job = claimed(worker)
    await worker.execute(job)
    store.finish.assert_awaited_once_with(job, JobStatus.SUCCEEDED, result_ref="synthetic-artifact")
    store.fail.assert_not_called()


@pytest.mark.parametrize(("error", "code", "retryable"), [
    (HandlerFailure(JobErrorCode.RETRYABLE_FAILURE, retryable=True),
     JobErrorCode.RETRYABLE_FAILURE, True),
    (HandlerFailure(JobErrorCode.PERMANENT_FAILURE), JobErrorCode.PERMANENT_FAILURE, False),
    (RuntimeError("password=private document body"), JobErrorCode.HANDLER_EXCEPTION, True),
])
async def test_failure_dispatch_is_safe(
    store, worker_settings, controlled_handler, error, code, retryable, caplog,
) -> None:
    controlled_handler.failure = error
    worker = Worker(store, {"fake": controlled_handler}, worker_settings)
    job = claimed(worker)
    await worker.execute(job)
    store.fail.assert_awaited_once_with(job, code, retryable=retryable)
    store.finish.assert_not_called()
    assert "private document body" not in caplog.text
    with pytest.raises(ValueError):
        HandlerFailure("password=private")


async def test_unknown_type_fails_closed(store, worker_settings) -> None:
    worker = Worker(store, {}, worker_settings)
    job = claimed(worker, job_type="unregistered")
    await worker.execute(job)
    store.fail.assert_awaited_once_with(job, JobErrorCode.UNKNOWN_JOB_TYPE, retryable=False)


@pytest.mark.parametrize("shutdown", [False, True])
async def test_handler_cancellation_distinguishes_shutdown_from_job_cancellation(
    store, worker_settings, shutdown,
) -> None:
    async def cancelled_handler(job, context):
        if shutdown:
            worker.stop()
        raise asyncio.CancelledError

    worker = Worker(store, {"fake": cancelled_handler}, worker_settings)
    job = claimed(worker)
    await worker.execute(job)
    if shutdown:
        store.fail.assert_awaited_once_with(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)
        store.finish.assert_not_called()
    else:
        store.finish.assert_awaited_once_with(
            job, JobStatus.CANCELLED, error_code=JobErrorCode.CANCELLED,
        )
        store.fail.assert_not_called()


@pytest.mark.parametrize("failure", [False, RuntimeError("database credentials")])
async def test_heartbeat_loss_stops_handler_without_terminal_write(
    store, worker_settings, controlled_handler, failure,
) -> None:
    controlled_handler.release.clear()
    if failure is False:
        store.heartbeat.return_value = False
    else:
        store.heartbeat.side_effect = failure
    worker = Worker(store, {"fake": controlled_handler}, worker_settings)
    await asyncio.wait_for(worker.execute(claimed(worker)), 2)
    await asyncio.wait_for(controlled_handler.cancelled.wait(), 1)
    store.finish.assert_not_called()
    store.fail.assert_not_called()


async def test_completion_database_failure_does_not_write_false_failure_or_success(
    store, worker_settings, controlled_handler,
) -> None:
    store.finish.side_effect = RuntimeError("sensitive SQL")
    worker = Worker(store, {"fake": controlled_handler}, worker_settings)
    await worker.execute(claimed(worker))
    store.finish.assert_awaited_once()
    store.fail.assert_not_called()


async def test_shutdown_does_not_accept_late_success_from_uncancellable_handler(
    store, worker_settings,
) -> None:
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stubborn(job, context):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return HandlerResult()

    worker = Worker(store, {"fake": stubborn}, worker_settings)
    job = claimed(worker)
    execution = asyncio.create_task(worker.execute(job))
    await started.wait()
    worker.stop()
    await asyncio.wait_for(execution, 2)
    await asyncio.wait_for(cancelled.wait(), 1)
    release.set()
    await asyncio.gather(*worker.unfinished_handlers)
    store.finish.assert_not_called()
    store.fail.assert_awaited_once_with(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)


async def test_disabled_or_stopped_worker_never_claims(store, worker_settings) -> None:
    worker = Worker(store, {}, worker_settings)
    worker.stop()
    await worker.run()
    worker_settings.enabled = False
    await Worker(store, {}, worker_settings).run()
    store.claim.assert_not_called()


async def test_redis_publish_failure_is_nonfatal() -> None:
    redis = AsyncMock()
    redis.client.publish.side_effect = ConnectionError("password=private")
    assert await notify_jobs(redis) is False


async def test_notification_has_no_job_state() -> None:
    redis = AsyncMock()
    assert await notify_jobs(redis)
    redis.client.publish.assert_awaited_once_with(JOB_WAKEUP_CHANNEL, "wake")


async def test_shutdown_while_claim_is_in_flight_does_not_invoke_handler(
    store, worker_settings, controlled_handler,
) -> None:
    worker = Worker(store, {"fake": controlled_handler}, worker_settings)
    job = claimed(worker)

    async def stop_during_claim(*args):
        worker.stop()
        return job

    store.claim.side_effect = stop_during_claim
    await worker.run()
    assert controlled_handler.calls == []
    store.fail.assert_awaited_once_with(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)
