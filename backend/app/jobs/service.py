"""Job service — orchestration layer for the API.

Coordinates between the JobQueue, task handlers, and authorization.
Provides the high-level interface that the API endpoints call.

Reference: Sprint 9 Parts 5, 10.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.jobs.models import Job, JobPriority, JobProgress, JobStatus, JobType
from app.jobs.queue import JobQueue
from app.jobs.tasks import get_task_handler

logger = logging.getLogger(__name__)


class JobService:
    """High-level job orchestration service.

    Usage::

        service = JobService(queue)
        job = await service.create_job(user_id, JobType.PARSE_SYLLABUS, {...})
        result = await service.get_job(job.job_id, current_user)
    """

    def __init__(self, queue: JobQueue) -> None:
        """Initialize the job service.

        Args:
            queue: A JobQueue instance.
        """
        self._queue = queue

    # ── Job Creation ───────────────────────────────────────────────────────

    async def create_job(
        self,
        job_type: JobType,
        user_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        payload: dict | None = None,
        priority: JobPriority = JobPriority.DEFAULT,
        max_retries: int = 3,
        metadata: dict | None = None,
    ) -> Job:
        """Create and enqueue a new job.

        Args:
            job_type: Type of job to create.
            user_id: Optional user who owns the job.
            session_id: Optional session context.
            payload: Optional job-specific payload.
            priority: Job priority level.
            max_retries: Maximum retry attempts.
            metadata: Optional metadata for observability.

        Returns:
            The created and enqueued Job.
        """
        job = Job(
            job_type=job_type,
            user_id=user_id,
            session_id=session_id,
            payload=payload or {},
            priority=priority,
            max_retries=max_retries,
            metadata=metadata or {},
        )
        return await self._queue.enqueue(job)

    # ── Job Queries (with authorization) ───────────────────────────────────

    async def get_job(
        self,
        job_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        is_admin: bool = False,
    ) -> Job | None:
        """Get a job by ID with authorization check.

        Args:
            job_id: The job ID.
            requesting_user_id: The user making the request.
            is_admin: Whether the user is an admin.

        Returns:
            The Job, or None if not found.

        Raises:
            PermissionError: If the user is not authorized.
        """
        job = await self._queue.get_job(job_id)
        if job is None:
            return None

        # Authorization: admins can see all, students only their own
        if not is_admin and job.user_id is not None and job.user_id != requesting_user_id:
            raise PermissionError("Access denied: you can only view your own jobs.")

        return job

    async def list_jobs(
        self,
        requesting_user_id: uuid.UUID,
        is_admin: bool = False,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Job], int]:
        """List jobs with authorization filtering.

        Students see only their own jobs. Admins see all.

        Args:
            requesting_user_id: The user making the request.
            is_admin: Whether the user is an admin.
            status: Optional filter by status.
            job_type: Optional filter by job type.
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            Tuple of (list of Jobs, total count).
        """
        if is_admin:
            user_filter = None
        else:
            user_filter = requesting_user_id

        return await self._queue.list_jobs(
            user_id=user_filter,
            status=status,
            job_type=job_type,
            page=page,
            page_size=page_size,
        )

    # ── Job Actions ────────────────────────────────────────────────────────

    async def cancel_job(
        self,
        job_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        is_admin: bool = False,
    ) -> Job | None:
        """Cancel a job with authorization check.

        Args:
            job_id: The job ID.
            requesting_user_id: The user making the request.
            is_admin: Whether the user is an admin.

        Returns:
            The cancelled Job, or None if not found.
        """
        job = await self._queue.get_job(job_id)
        if job is None:
            return None

        if not is_admin and job.user_id is not None and job.user_id != requesting_user_id:
            raise PermissionError("Access denied: you can only cancel your own jobs.")

        return await self._queue.cancel_job(job_id)

    async def retry_job(
        self,
        job_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        is_admin: bool = False,
    ) -> Job | None:
        """Re-enqueue a failed job for retry.

        Args:
            job_id: The job ID.
            requesting_user_id: The user making the request.
            is_admin: Whether the user is an admin.

        Returns:
            The re-enqueued Job, or None if not found.
        """
        job = await self._queue.get_job(job_id)
        if job is None:
            return None

        if not is_admin and job.user_id is not None and job.user_id != requesting_user_id:
            raise PermissionError("Access denied: you can only retry your own jobs.")

        if job.status != JobStatus.FAILED:
            raise ValueError(f"Cannot retry job in state '{job.status.value}'. Only FAILED jobs can be retried.")

        # Reset and re-enqueue
        job.status = JobStatus.QUEUED
        job.retry_count = 0
        job.error_message = None
        job.started_at = None
        job.completed_at = None

        return await self._queue.enqueue(job)

    # ── Execution ──────────────────────────────────────────────────────────

    async def execute_job(self, job: Job, worker_id: str) -> None:
        """Execute a single job by looking up its task handler.

        This is the main execution loop for workers.

        Args:
            job: The job to execute.
            worker_id: Worker identifier for ownership.
        """
        handler = get_task_handler(job.job_type)
        if handler is None:
            await self._queue.fail_job(
                job.job_id,
                f"No handler registered for job type '{job.job_type.value}'",
                should_retry=False,
            )
            return

        # Mark as running
        await self._queue.start_job(job.job_id, worker_id)

        try:
            result = await handler(job, self._queue)
            await self._queue.complete_job(job.job_id, result)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Job execution failed", extra={"job_id": str(job.job_id), "job_type": job.job_type.value})
            await self._queue.fail_job(job.job_id, error_msg, should_retry=True)

    # ── Health ─────────────────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Get job system health status."""
        return await self._queue.health()
