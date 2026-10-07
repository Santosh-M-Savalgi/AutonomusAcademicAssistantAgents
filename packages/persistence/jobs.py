"""Short PostgreSQL transactions for claims, fenced ownership, and recovery."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.sql.elements import ColumnElement

from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import (
    ClaimedJob,
    JobCancelledPayload,
    JobCompletedPayload,
    JobErrorCode,
    JobEventPayload,
    JobEventType,
    JobFailedPayload,
    JobPartialResultPayload,
    JobRecoveredPayload,
    JobRetryPayload,
    JobStartedPayload,
    failure_status,
    retry_delay,
    validate_transition,
)
from packages.persistence.database import Database
from packages.persistence.job_events import append_event
from packages.persistence.models import Job, JobProgressEvent


def claim_query(lanes: tuple[JobLane, ...]) -> Select[tuple[Job]]:
    """Lane is an eligibility filter; priority leads within the configured lanes."""

    return (
        select(Job)
        .where(
            Job.status.in_([JobStatus.PENDING, JobStatus.RETRYING]),
            Job.run_after <= func.clock_timestamp(),
            Job.attempts < Job.max_attempts,
            Job.lane.in_(lanes),
        )
        .order_by(Job.priority.desc(), Job.created_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def ownership(job: ClaimedJob) -> tuple[ColumnElement[bool], ...]:
    return (
        Job.id == job.id,
        Job.locked_by == job.worker_id,
        Job.attempts == job.attempts,
        Job.status == JobStatus.RUNNING,
        Job.lease_expires_at > func.clock_timestamp(),
    )


class JobRepository:
    """Every operation commits before returning; handlers never hold transactions."""

    def __init__(self, database: Database, *, retry_base: float = 2, retry_max: float = 300):
        retry_delay(1, retry_base, retry_max)
        self.database = database
        self.retry_base = retry_base
        self.retry_max = retry_max

    async def claim(
        self, worker_id: str, lanes: tuple[JobLane, ...], lease_seconds: float,
    ) -> ClaimedJob | None:
        if not worker_id or len(worker_id) > 255 or lease_seconds <= 0:
            raise ValueError("Invalid worker ownership configuration")
        async with self.database.session() as session, session.begin():
            job = (await session.execute(claim_query(lanes))).scalar_one_or_none()
            if job is None:
                return None
            validate_transition(JobStatus(job.status), JobStatus.RUNNING)
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            job.status = JobStatus.RUNNING
            job.attempts += 1
            job.locked_by = worker_id
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            job.error_code = None
            append_event(
                session, job, JobEventType.STARTED, JobStartedPayload(),
                attempt=job.attempts, idempotency_key=f"attempt:{job.attempts}:started",
            )
            return ClaimedJob(
                id=job.id, type=job.job_type, payload=dict(job.payload), lane=JobLane(job.lane),
                priority=job.priority, attempts=job.attempts, max_attempts=job.max_attempts,
                worker_id=worker_id, lease_expires_at=job.lease_expires_at,
            )

    async def heartbeat(self, job: ClaimedJob, lease_seconds: float) -> bool:
        if lease_seconds <= 0:
            raise ValueError("Lease duration must be positive")
        async with self.database.session() as session, session.begin():
            result = await session.execute(
                update(Job).where(*ownership(job)).values(
                    heartbeat_at=func.clock_timestamp(),
                    lease_expires_at=func.clock_timestamp() + timedelta(seconds=lease_seconds),
                    updated_at=func.clock_timestamp(),
                ).returning(Job.id)
            )
            return result.scalar_one_or_none() is not None

    async def finish(
        self, job: ClaimedJob, status: JobStatus, *,
        error_code: JobErrorCode | None = None, result_ref: str | None = None,
    ) -> bool:
        validate_transition(JobStatus.RUNNING, status)
        if status == JobStatus.RETRYING and job.attempts >= job.max_attempts:
            status = JobStatus.FAILED
        if error_code is not None:
            error_code = JobErrorCode(error_code)  # Reject arbitrary error text at the DB boundary.
        delay = retry_delay(job.attempts, self.retry_base, self.retry_max)
        async with self.database.session() as session, session.begin():
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            result = await session.execute(
                update(Job).where(*ownership(job)).values(
                    status=status,
                    error_code=error_code,
                    result_ref=result_ref if status in {JobStatus.SUCCEEDED, JobStatus.PARTIAL}
                    else None,
                    run_after=now + timedelta(seconds=delay if status == JobStatus.RETRYING else 0),
                    locked_by=None, lease_expires_at=None, heartbeat_at=None, updated_at=now,
                ).returning(Job)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return False
            if status == JobStatus.RETRYING:
                append_event(
                    session, row, JobEventType.RETRY_SCHEDULED,
                    JobRetryPayload(
                        error_code=error_code or JobErrorCode.RETRYABLE_FAILURE,
                        retry_at=now + timedelta(seconds=delay),
                    ), attempt=job.attempts,
                    idempotency_key=f"attempt:{job.attempts}:retry",
                )
                # Event append updates the ORM row and its Python on-update
                # timestamp during the eventual flush. Recompute the retry
                # deadline from PostgreSQL clock time so the persisted delay
                # remains strictly after that final update timestamp.
                row.run_after = func.clock_timestamp() + timedelta(seconds=delay)
            elif status == JobStatus.FAILED:
                append_event(
                    session, row, JobEventType.FAILED,
                    JobFailedPayload(error_code=error_code or JobErrorCode.PERMANENT_FAILURE),
                    attempt=job.attempts, idempotency_key=f"attempt:{job.attempts}:failed",
                )
            elif status == JobStatus.CANCELLED:
                append_event(
                    session, row, JobEventType.CANCELLED, JobCancelledPayload(),
                    attempt=job.attempts, idempotency_key=f"attempt:{job.attempts}:cancelled",
                )
            elif status == JobStatus.PARTIAL:
                append_event(
                    session, row, JobEventType.PARTIAL_RESULT_AVAILABLE,
                    JobPartialResultPayload(result_kind="job_result"), attempt=job.attempts,
                    idempotency_key=f"attempt:{job.attempts}:partial",
                )
            elif status == JobStatus.SUCCEEDED:
                append_event(
                    session, row, JobEventType.COMPLETED,
                    JobCompletedPayload(result_available=result_ref is not None),
                    attempt=job.attempts, idempotency_key=f"attempt:{job.attempts}:completed",
                )
            return True

    async def fail(self, job: ClaimedJob, code: JobErrorCode, *, retryable: bool) -> bool:
        return await self.finish(
            job, failure_status(job.attempts, job.max_attempts, retryable=retryable),
            error_code=code,
        )

    async def cancel(self, job_id: UUID) -> bool:
        """Explicit cancellation by a trusted caller; no public cancellation API yet."""

        sources = [JobStatus.PENDING, JobStatus.RETRYING, JobStatus.RUNNING, JobStatus.PARTIAL]
        for source in sources:
            validate_transition(source, JobStatus.CANCELLED)
        async with self.database.session() as session, session.begin():
            job = (await session.scalars(select(Job).where(
                Job.id == job_id, Job.status.in_(sources),
            ).with_for_update())).one_or_none()
            if job is None:
                return False
            job.status = JobStatus.CANCELLED
            job.error_code = JobErrorCode.CANCELLED
            job.locked_by = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.updated_at = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            append_event(
                session, job, JobEventType.CANCELLED,
                JobCancelledPayload(),
                attempt=job.attempts, idempotency_key=f"cancel:{job.id}",
            )
            return True

    async def report_progress(
        self, job: ClaimedJob, event_type: JobEventType, payload: JobEventPayload,
        idempotency_key: str,
    ) -> bool:
        """Append a meaningful progress event only while this attempt owns the lease."""

        if event_type not in {
            JobEventType.STAGE_STARTED,
            JobEventType.PROGRESS_UPDATED,
            JobEventType.PARTIAL_RESULT_AVAILABLE,
        }:
            raise ValueError("Worker progress accepts progress event types only")
        async with self.database.session() as session, session.begin():
            existing = (await session.scalars(select(JobProgressEvent).where(
                JobProgressEvent.job_id == job.id,
                JobProgressEvent.idempotency_key == idempotency_key,
            ))).one_or_none()
            if existing is not None:
                return True
            row = (await session.scalars(
                select(Job).where(*ownership(job)).with_for_update()
            )).one_or_none()
            if row is None:
                return False
            append_event(
                session, row, event_type, payload, attempt=job.attempts,
                idempotency_key=idempotency_key,
            )
            return True

    async def reap(self, limit: int = 100) -> int:
        """Lock expired rows; concurrent reapers and heartbeats cannot overwrite each other."""

        if limit < 1:
            raise ValueError("Reaper batch size must be positive")
        async with self.database.session() as session, session.begin():
            jobs = (await session.scalars(
                select(Job).where(
                    Job.status == JobStatus.RUNNING,
                    Job.lease_expires_at <= func.clock_timestamp(),
                ).order_by(Job.lease_expires_at, Job.id).limit(limit)
                .with_for_update(skip_locked=True)
            )).all()
            now: datetime = (await session.execute(select(func.clock_timestamp()))).scalar_one()
            for job in jobs:
                target = failure_status(job.attempts, job.max_attempts, retryable=True)
                validate_transition(JobStatus(job.status), target)
                job.status = target
                job.error_code = JobErrorCode.LEASE_EXPIRED
                job.locked_by = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.updated_at = now
                job.run_after = now + timedelta(seconds=retry_delay(
                    max(1, job.attempts), self.retry_base, self.retry_max
                ))
                if target == JobStatus.RETRYING:
                    append_event(
                        session, job, JobEventType.RECOVERED,
                        JobRecoveredPayload(
                            previous_attempt=job.attempts, next_attempt=job.attempts + 1,
                        ), attempt=job.attempts,
                        idempotency_key=f"attempt:{job.attempts}:recovered",
                    )
                    append_event(
                        session, job, JobEventType.RETRY_SCHEDULED,
                        JobRetryPayload(
                            error_code=JobErrorCode.LEASE_EXPIRED, retry_at=job.run_after,
                        ), attempt=job.attempts,
                        idempotency_key=f"attempt:{job.attempts}:reaper-retry",
                    )
                else:
                    append_event(
                        session, job, JobEventType.FAILED,
                        JobFailedPayload(error_code=JobErrorCode.LEASE_EXPIRED),
                        attempt=job.attempts,
                        idempotency_key=f"attempt:{job.attempts}:reaper-failed",
                    )
            return len(jobs)
