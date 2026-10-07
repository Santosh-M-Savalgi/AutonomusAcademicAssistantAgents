"""Typed durable job events, ordered replay, and safe job snapshots."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select

from packages.domain.enums import JobStatus
from packages.domain.jobs import (
    JobCancelledPayload,
    JobCompletedPayload,
    JobCreatedPayload,
    JobEventPayload,
    JobEventType,
    JobFailedPayload,
    JobPartialResultPayload,
    JobProgressEvent,
    JobProgressState,
    JobRecoveredPayload,
    JobRetryPayload,
    JobSnapshot,
    JobStagePayload,
    JobStartedPayload,
)
from packages.domain.models import DomainModel
from packages.persistence.database import Database
from packages.persistence.models import Job
from packages.persistence.models import JobProgressEvent as JobProgressEventRow

_PAYLOAD_TYPES: dict[JobEventType, type[DomainModel]] = {
    JobEventType.CREATED: JobCreatedPayload,
    JobEventType.STARTED: JobStartedPayload,
    JobEventType.STAGE_STARTED: JobStagePayload,
    JobEventType.PROGRESS_UPDATED: JobStagePayload,
    JobEventType.PARTIAL_RESULT_AVAILABLE: JobPartialResultPayload,
    JobEventType.RETRY_SCHEDULED: JobRetryPayload,
    JobEventType.RECOVERED: JobRecoveredPayload,
    JobEventType.FAILED: JobFailedPayload,
    JobEventType.COMPLETED: JobCompletedPayload,
    JobEventType.CANCELLED: JobCancelledPayload,
}


def validate_event_payload(
    event_type: JobEventType, payload: JobEventPayload | Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an event against the closed payload contract before persistence."""

    model = _PAYLOAD_TYPES[event_type].model_validate(
        payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    )
    return model.model_dump(mode="json")


def append_event(
    session: Any, job: Job, event_type: JobEventType,
    payload: JobEventPayload | Mapping[str, Any], *, attempt: int, idempotency_key: str,
) -> JobProgressEventRow:
    """Append to a locked/new job in the caller's transaction."""

    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("Invalid job event idempotency key")
    body = validate_event_payload(event_type, payload)
    sequence = int(job.latest_event_sequence or 0) + 1
    job.latest_event_sequence = sequence
    if event_type in {JobEventType.STAGE_STARTED, JobEventType.PROGRESS_UPDATED}:
        job.progress_stage = str(body["stage"])
        job.progress_percent = int(body["progress_percent"])
        job.progress_message = body.get("message")
    row = JobProgressEventRow(
        event_id=uuid5(job.id, f"job-event:{idempotency_key}"), job_id=job.id,
        sequence=sequence, event_type=event_type.value, payload=body,
        attempt=attempt, idempotency_key=idempotency_key, created_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def _event_domain(row: JobProgressEventRow) -> JobProgressEvent:
    event_type = JobEventType(row.event_type)
    payload = validate_event_payload(event_type, row.payload)
    return JobProgressEvent(
        event_id=row.event_id, job_id=row.job_id, sequence=row.sequence,
        type=event_type, payload=payload, attempt=row.attempt, created_at=row.created_at,
    )


async def events_after(
    database: Database, job_id: UUID, after_sequence: int, *, limit: int = 100,
) -> list[JobProgressEvent]:
    if after_sequence < 0 or limit < 1 or limit > 1000:
        raise ValueError("Invalid job event replay bounds")
    async with database.session() as session:
        rows = (await session.scalars(select(JobProgressEventRow).where(
            JobProgressEventRow.job_id == job_id,
            JobProgressEventRow.sequence > after_sequence,
        ).order_by(JobProgressEventRow.sequence).limit(limit))).all()
    return [_event_domain(row) for row in rows]


async def job_snapshot(database: Database, job_id: UUID) -> JobSnapshot | None:
    async with database.session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return None
        latest = (await session.scalars(select(JobProgressEventRow).where(
            JobProgressEventRow.job_id == job_id,
            JobProgressEventRow.sequence == job.latest_event_sequence,
        ))).one_or_none()
    return JobSnapshot(
        id=job.id, type=job.job_type, status=JobStatus(job.status), attempt=job.attempts,
        max_attempts=job.max_attempts,
        progress=JobProgressState(
            stage=job.progress_stage, progress_percent=job.progress_percent,
            message=job.progress_message,
        ),
        latest_event_id=latest.event_id if latest is not None else None,
        latest_event_sequence=job.latest_event_sequence,
        result_available=job.result_ref is not None,
        error_code=job.error_code, created_at=job.created_at, updated_at=job.updated_at,
    )


async def job_course_id(database: Database, job_id: UUID) -> UUID | None:
    async with database.session() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return None
        value = job.payload.get("course_id")
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
