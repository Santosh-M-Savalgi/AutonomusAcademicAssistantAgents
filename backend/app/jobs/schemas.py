"""Background Jobs — Pydantic API schemas.

Request/response schemas for job API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.jobs.models import JobPriority, JobStatus, JobType


class JobProgressSchema(BaseModel):
    """Schema for job progress."""

    percentage: float = 0.0
    current_stage: str = "initializing"
    message: str = ""
    estimated_remaining_seconds: float | None = None


class JobResponse(BaseModel):
    """Full job response schema."""

    job_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    priority: JobPriority = JobPriority.DEFAULT
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    progress: JobProgressSchema = Field(default_factory=JobProgressSchema)
    metadata: dict = Field(default_factory=dict)
    worker_id: str | None = None


class JobCreateRequest(BaseModel):
    """Request to create/enqueue a new background job."""

    job_type: JobType
    payload: dict = Field(default_factory=dict)
    priority: JobPriority = JobPriority.DEFAULT
    max_retries: int = 3
    metadata: dict = Field(default_factory=dict)
    session_id: uuid.UUID | None = None


class JobCreateResponse(BaseModel):
    """Response after creating/enqueuing a new job."""

    job_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    message: str = "Job enqueued successfully."


class JobListResponse(BaseModel):
    """Paginated job listing response."""

    jobs: list[JobResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class JobHealthResponse(BaseModel):
    """Job system health check response."""

    status: str = "ok"
    queued_jobs: int = 0
    running_jobs: int = 0
    failed_jobs_last_hour: int = 0
    completed_jobs_last_hour: int = 0
    active_workers: int = 0
    worker_ids: list[str] = Field(default_factory=list)
    uptime_seconds: float = 0.0
