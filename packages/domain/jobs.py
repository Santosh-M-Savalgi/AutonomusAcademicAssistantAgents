"""Pure job lifecycle policy and detached execution metadata."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from packages.domain.enums import JobLane, JobStatus
from packages.domain.models import DomainModel


class JobErrorCode(StrEnum):
    """Closed vocabulary: exception messages/payloads never become stored errors."""

    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    UNKNOWN_JOB_TYPE = "UNKNOWN_JOB_TYPE"
    HANDLER_EXCEPTION = "HANDLER_EXCEPTION"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    WORKER_SHUTDOWN = "WORKER_SHUTDOWN"
    CANCELLED = "CANCELLED"
    INVALID_DOCUMENT = "INVALID_DOCUMENT"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    INVALID_PDF = "INVALID_PDF"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    PDF_LIMIT_EXCEEDED = "PDF_LIMIT_EXCEEDED"
    EXTRACTION_OUTPUT_LIMIT = "EXTRACTION_OUTPUT_LIMIT"
    EXTRACTION_TIMEOUT = "EXTRACTION_TIMEOUT"
    EXTRACTION_RESOURCE_LIMIT = "EXTRACTION_RESOURCE_LIMIT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"
    INVALID_EXTRACTION = "INVALID_EXTRACTION"
    EXTRACTION_NOT_READY = "EXTRACTION_NOT_READY"
    INSUFFICIENT_EXTRACTION = "INSUFFICIENT_EXTRACTION"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    DRAFT_TIMEOUT = "DRAFT_TIMEOUT"
    DRAFT_LIMIT_EXCEEDED = "DRAFT_LIMIT_EXCEEDED"
    GRAPH_REVISION_MISMATCH = "GRAPH_REVISION_MISMATCH"
    GRAPH_CHECKSUM_MISMATCH = "GRAPH_CHECKSUM_MISMATCH"
    GRAPH_DAG_INVALID = "GRAPH_DAG_INVALID"
    GRAPH_PUBLICATION_CONFLICT = "GRAPH_PUBLICATION_CONFLICT"


class JobEventType(StrEnum):
    """Stable public names for durable job progress events."""

    CREATED = "job.created"
    STARTED = "job.started"
    STAGE_STARTED = "job.stage_started"
    PROGRESS_UPDATED = "job.progress_updated"
    PARTIAL_RESULT_AVAILABLE = "job.partial_result_available"
    RETRY_SCHEDULED = "job.retry_scheduled"
    RECOVERED = "job.recovered"
    FAILED = "job.failed"
    COMPLETED = "job.completed"
    CANCELLED = "job.cancelled"


class JobCreatedPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    job_type: str = Field(min_length=1, max_length=64)
    status: Literal[JobStatus.PENDING] = JobStatus.PENDING


class JobStartedPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    status: Literal[JobStatus.RUNNING] = JobStatus.RUNNING


class JobStagePayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    stage: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    progress_percent: int = Field(ge=0, le=100)
    message: str | None = Field(default=None, max_length=160)


class JobPartialResultPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    result_kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")


class JobRetryPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    error_code: JobErrorCode
    retry_at: datetime


class JobRecoveredPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    previous_attempt: int = Field(ge=1)
    next_attempt: int = Field(ge=1)
    error_code: Literal[JobErrorCode.LEASE_EXPIRED] = JobErrorCode.LEASE_EXPIRED


class JobFailedPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    error_code: JobErrorCode


class JobCompletedPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    result_available: bool


class JobCancelledPayload(DomainModel):
    schema_version: Literal["job-event-v1"] = "job-event-v1"
    error_code: Literal[JobErrorCode.CANCELLED] = JobErrorCode.CANCELLED


JobEventPayload = (
    JobCreatedPayload | JobStartedPayload | JobStagePayload | JobPartialResultPayload
    | JobRetryPayload | JobRecoveredPayload | JobFailedPayload | JobCompletedPayload
    | JobCancelledPayload
)


class JobProgressEvent(DomainModel):
    """Publicly serializable durable event envelope."""

    event_id: UUID
    job_id: UUID
    sequence: int = Field(ge=1)
    type: JobEventType
    payload: dict[str, Any]
    attempt: int = Field(ge=0)
    created_at: datetime


class JobProgressState(DomainModel):
    stage: str | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    message: str | None = Field(default=None, max_length=160)


class JobSnapshot(DomainModel):
    """Safe current job state used to reconcile a reconnecting client."""

    id: UUID
    type: str
    status: JobStatus
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    progress: JobProgressState
    latest_event_id: UUID | None
    latest_event_sequence: int = Field(ge=0)
    result_available: bool
    error_code: str | None
    created_at: datetime
    updated_at: datetime


_TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RETRYING: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.PARTIAL, JobStatus.SUCCEEDED, JobStatus.FAILED,
        JobStatus.CANCELLED, JobStatus.RETRYING,
    },
    JobStatus.PARTIAL: {JobStatus.RETRYING, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


def validate_transition(source: JobStatus, target: JobStatus) -> None:
    if target not in _TRANSITIONS[source]:
        raise ValueError(f"Invalid job transition: {source} -> {target}")


def failure_status(attempts: int, max_attempts: int, *, retryable: bool) -> JobStatus:
    return JobStatus.RETRYING if retryable and attempts < max_attempts else JobStatus.FAILED


def retry_delay(attempts: int, base: float, maximum: float) -> float:
    """Bounded exponential delay; no jitter makes local scheduling deterministic."""

    if attempts < 1 or base <= 0 or maximum < base:
        raise ValueError("Invalid retry policy")
    # Stop doubling at the cap without constructing huge integers for corrupt attempt counts.
    delay = base
    for _ in range(attempts - 1):
        delay = min(maximum, delay * 2)
        if delay == maximum:
            break
    return delay


@dataclass(frozen=True)
class ClaimedJob:
    """Snapshot detached from SQLAlchemy; attempt is also an ownership fence."""

    id: UUID
    type: str
    payload: dict[str, Any]
    lane: JobLane
    priority: int
    attempts: int
    max_attempts: int
    worker_id: str
    lease_expires_at: datetime
