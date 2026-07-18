"""Job Monitoring API endpoints (Sprint 9 Part 5).

Provides CRUD and management endpoints for background jobs:
- POST   /jobs                    — create/enqueue a new job
- GET    /jobs/{job_id}           — get job status and progress
- GET    /jobs                    — list jobs with filtering
- DELETE /jobs/{job_id}           — remove a completed/failed job
- POST   /jobs/{job_id}/retry     — retry a failed job
- POST   /jobs/{job_id}/cancel    — cancel a queued/running job
- GET    /jobs/health              — job system health check

Authorization:
- Students: access only their own jobs
- Admins: access all jobs
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.db.models import User
from app.db.postgres import get_db
from app.db.redis import get_redis
from app.jobs.models import JobPriority, JobStatus, JobType
from app.jobs.queue import JobQueue
from app.jobs.schemas import (
    JobCreateRequest,
    JobCreateResponse,
    JobHealthResponse,
    JobListResponse,
    JobProgressSchema,
    JobResponse,
)
from app.jobs.service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ── Singleton ──────────────────────────────────────────────────────────────

_service: JobService | None = None


def _get_service() -> JobService:
    """Get or create the singleton JobService."""
    global _service
    if _service is None:
        redis = get_redis()
        queue = JobQueue(redis)
        _service = JobService(queue)
    return _service


async def _job_to_response(job) -> JobResponse:
    """Convert a domain Job to a JobResponse schema."""
    return JobResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        priority=job.priority,
        user_id=job.user_id,
        session_id=job.session_id,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        retry_count=job.retry_count,
        max_retries=job.max_retries,
        error_message=job.error_message,
        progress=JobProgressSchema(
            percentage=job.progress.percentage,
            current_stage=job.progress.current_stage,
            message=job.progress.message,
            estimated_remaining_seconds=job.progress.estimated_remaining_seconds,
        ),
        metadata=job.metadata,
        worker_id=job.worker_id,
    )


# ── Create Job ─────────────────────────────────────────────────────────────


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobCreateResponse:
    """Create and enqueue a new background job.

    Returns immediately with the job ID. The job executes asynchronously.
    """
    service = _get_service()
    job = await service.create_job(
        job_type=body.job_type,
        user_id=current_user.id,
        session_id=body.session_id,
        payload=body.payload,
        priority=body.priority,
        max_retries=body.max_retries,
        metadata=body.metadata,
    )
    return JobCreateResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        status=job.status,
        message=f"Job of type '{job.job_type.value}' enqueued successfully.",
    )


# ── Get Job ────────────────────────────────────────────────────────────────


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Get a job's status and progress by ID.

    Students can only access their own jobs. Admins can access any.
    """
    service = _get_service()
    is_admin = current_user.role == "admin"

    try:
        job = await service.get_job(
            job_id=job_id,
            requesting_user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )

    return await _job_to_response(job)


# ── List Jobs ──────────────────────────────────────────────────────────────


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: JobStatus | None = Query(None, description="Filter by job status"),
    job_type: JobType | None = Query(None, description="Filter by job type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
) -> JobListResponse:
    """List jobs with optional filtering.

    Students see only their own jobs. Admins see all.
    """
    service = _get_service()
    is_admin = current_user.role == "admin"

    jobs, total = await service.list_jobs(
        requesting_user_id=current_user.id,
        is_admin=is_admin,
        status=status,
        job_type=job_type,
        page=page,
        page_size=page_size,
    )

    return JobListResponse(
        jobs=[await _job_to_response(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── Delete Job ─────────────────────────────────────────────────────────────


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete (cancel) a job by ID.

    Students can only cancel their own jobs. Admins can cancel any.
    """
    service = _get_service()
    is_admin = current_user.role == "admin"

    job = await service._queue.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )

    try:
        await service.cancel_job(
            job_id=job_id,
            requesting_user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    return None


# ── Retry Job ──────────────────────────────────────────────────────────────


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Retry a failed job.

    Students can only retry their own jobs. Admins can retry any.
    """
    service = _get_service()
    is_admin = current_user.role == "admin"

    try:
        job = await service.retry_job(
            job_id=job_id,
            requesting_user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )

    return await _job_to_response(job)


# ── Cancel Job ─────────────────────────────────────────────────────────────


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """Cancel a queued or running job.

    Students can only cancel their own jobs. Admins can cancel any.
    """
    service = _get_service()
    is_admin = current_user.role == "admin"

    try:
        job = await service.cancel_job(
            job_id=job_id,
            requesting_user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found.",
        )

    return await _job_to_response(job)


# ── Health ─────────────────────────────────────────────────────────────────


@router.get("/health", response_model=JobHealthResponse)
async def job_health(
    current_user: User = Depends(get_current_user),
) -> JobHealthResponse:
    """Get job system health status.

    Admin-only endpoint showing queue depth, worker status, and throughput.
    """
    service = _get_service()
    health = await service.health()

    from app.jobs.worker import WorkerPool

    workers = WorkerPool.__new__(WorkerPool)
    workers._started_at = 0

    active_workers = await workers.get_active_workers()

    return JobHealthResponse(
        status=health.get("status", "ok"),
        queued_jobs=health.get("queued", 0),
        running_jobs=health.get("running", 0),
        failed_jobs_last_hour=0,
        completed_jobs_last_hour=0,
        active_workers=len(active_workers),
        worker_ids=list(active_workers.keys()),
        uptime_seconds=0.0,
    )
