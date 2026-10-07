"""Transaction-compatible durable job creation."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import JobCreatedPayload, JobEventType
from packages.persistence.job_events import append_event
from packages.persistence.models import Job


class JobIdempotencyConflictError(ValueError):
    """An idempotency key was reused for a different job request."""


def _same_request(
    row: Job,
    *,
    job_id: UUID,
    job_type: str,
    payload: dict[str, Any],
    lane: JobLane,
    priority: int,
    max_attempts: int,
    parent_job_id: UUID | None,
) -> bool:
    return (
        row.id == job_id
        and row.job_type == job_type
        and row.payload == payload
        and row.lane == lane.value
        and row.priority == priority
        and row.max_attempts == max_attempts
        and row.parent_job_id == parent_job_id
    )


async def create_job_in_transaction(
    session: AsyncSession,
    *,
    job_id: UUID,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    lane: JobLane = JobLane.BATCH,
    priority: int = 0,
    max_attempts: int = 3,
    parent_job_id: UUID | None = None,
) -> Job:
    """Create/replay a job without committing or publishing a wake-up.

    The caller commits this session together with its initiating domain change,
    then may publish a disposable Redis wake-up after commit.
    """

    if not job_type or len(job_type) > 64:
        raise ValueError("Invalid job type")
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("Invalid job idempotency key")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    existing = await session.scalar(
        select(Job).where(Job.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if not _same_request(
            existing, job_id=job_id, job_type=job_type, payload=payload, lane=lane,
            priority=priority, max_attempts=max_attempts, parent_job_id=parent_job_id,
        ):
            raise JobIdempotencyConflictError(
                "Job idempotency key conflicts with an existing request"
            )
        return existing

    row = Job(
        id=job_id,
        job_type=job_type,
        payload=payload,
        status=JobStatus.PENDING,
        priority=priority,
        lane=lane.value,
        attempts=0,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        parent_job_id=parent_job_id,
        latest_event_sequence=0,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
            append_event(
                session,
                row,
                JobEventType.CREATED,
                JobCreatedPayload(job_type=job_type),
                attempt=0,
                idempotency_key="created",
            )
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if not _same_request(
            existing, job_id=job_id, job_type=job_type, payload=payload, lane=lane,
            priority=priority, max_attempts=max_attempts, parent_job_id=parent_job_id,
        ):
            raise JobIdempotencyConflictError(
                "Job idempotency key conflicts with an existing request"
            ) from None
        return cast(Job, existing)
    return row
