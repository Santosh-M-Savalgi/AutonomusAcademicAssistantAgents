"""Redis-backed durable job queue (Part 2).

Uses Redis sorted sets for priority-ordered queuing and hash maps
for job metadata. Supports durable execution, state transitions,
and atomic dequeue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.jobs.models import Job, JobPriority, JobProgress, JobStatus, JobType, RetryPolicy

logger = logging.getLogger(__name__)

QUEUE_PREFIX = "aaa:jobs:"
QUEUE_QUEUED = f"{QUEUE_PREFIX}queued"        # sorted set (score = priority_order + timestamp)
QUEUE_RUNNING = f"{QUEUE_PREFIX}running"       # set of running job IDs
QUEUE_RETRY = f"{QUEUE_PREFIX}retry"           # sorted set (score = retry_at timestamp)
QUEUE_FAILED = f"{QUEUE_PREFIX}failed"         # list (for dead-letter)
QUEUE_JOB_META = f"{QUEUE_PREFIX}meta:"        # hash prefix for individual job metadata


class JobQueue:
    """Redis-backed durable job queue.

    Supports:
    - Priority-ordered enqueue/dequeue
    - Job state transitions (QUEUED → RUNNING → COMPLETED/FAILED)
    - Retry with exponential backoff via sorted set
    - Dead-letter handling for permanently failed jobs
    - Progress tracking
    - Job listing with filtering
    """

    def __init__(self, redis_client: Any, retry_policy: RetryPolicy | None = None) -> None:
        """Initialize the job queue.

        Args:
            redis_client: A redis.asyncio.Redis instance.
            retry_policy: Optional custom retry policy. Uses defaults if None.
        """
        self._redis = redis_client
        self._retry_policy = retry_policy or RetryPolicy()

    # ── Enqueue / Dequeue ──────────────────────────────────────────────────

    async def enqueue(self, job: Job) -> Job:
        """Enqueue a job with priority-based ordering.

        Args:
            job: The job to enqueue.

        Returns:
            The enqueued job (with updated status).
        """
        job.status = JobStatus.QUEUED
        job.created_at = datetime.now(timezone.utc)

        # Store full job metadata as a hash
        meta_key = f"{QUEUE_JOB_META}{job.job_id}"
        pipe = self._redis.pipeline()
        pipe.hset(meta_key, mapping=self._job_to_hash(job))
        pipe.expire(meta_key, 86400 * 7)  # 7 day TTL

        # Add to priority-ordered queue
        # Score = priority_order * 10^12 + timestamp (to ensure FIFO within priority)
        priority_order = job.priority.sort_order()
        score = priority_order * 10**12 + job.created_at.timestamp()
        pipe.zadd(QUEUE_QUEUED, {str(job.job_id): score})

        await pipe.execute()

        logger.info(
            "Job enqueued",
            extra={
                "job_id": str(job.job_id),
                "job_type": job.job_type.value,
                "priority": job.priority.value,
            },
        )
        return job

    async def dequeue(self, worker_id: str) -> Job | None:
        """Atomically dequeue the highest-priority job.

        Also checks the retry queue for jobs whose backoff has expired.

        Args:
            worker_id: Unique identifier of the requesting worker.

        Returns:
            A Job if one is available, None otherwise.
        """
        # Check retry queue first (jobs whose backoff has expired)
        retried_job = await self._dequeue_retry(worker_id)
        if retried_job is not None:
            return retried_job

        # Dequeue from the main queue with atomic pop
        # Use zrange + zrem in a transaction
        result = await self._redis.eval(
            """
            local job_id = redis.call('zrange', KEYS[1], 0, 0)
            if #job_id == 0 then
                return nil
            end
            redis.call('zrem', KEYS[1], job_id[1])
            return job_id[1]
            """,
            1,
            QUEUE_QUEUED,
        )

        if result is None:
            return None

        job_id = uuid.UUID(result)
        return await self._get_job(job_id)

    async def _dequeue_retry(self, worker_id: str) -> Job | None:
        """Check the retry queue for jobs whose backoff has expired.

        Args:
            worker_id: Worker identifier for ownership.

        Returns:
            A Job if a retry-ready one is found, None otherwise.
        """
        now = datetime.now(timezone.utc).timestamp()
        result = await self._redis.eval(
            """
            -- Find jobs with retry_at <= now
            local jobs = redis.call('zrangebyscore', KEYS[1], '-inf', ARGV[1], 'limit', 0, 1)
            if #jobs == 0 then
                return nil
            end
            redis.call('zrem', KEYS[1], jobs[1])
            return jobs[1]
            """,
            1,
            QUEUE_RETRY,
            str(now),
        )

        if result is None:
            return None

        job_id = uuid.UUID(result)
        return await self._get_job(job_id)

    # ── State Transitions ──────────────────────────────────────────────────

    async def start_job(self, job_id: uuid.UUID, worker_id: str) -> Job | None:
        """Mark a job as RUNNING.

        Args:
            job_id: The job ID.
            worker_id: Worker identifier for ownership.

        Returns:
            The updated Job, or None if not found.
        """
        job = await self._get_job(job_id)
        if job is None:
            return None

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.worker_id = worker_id
        job.heartbeat_at = datetime.now(timezone.utc)

        pipe = self._redis.pipeline()
        meta_key = f"{QUEUE_JOB_META}{job_id}"
        pipe.hset(meta_key, mapping=self._job_to_hash(job))
        pipe.sadd(QUEUE_RUNNING, str(job_id))
        await pipe.execute()

        return job

    async def complete_job(self, job_id: uuid.UUID, result: dict | None = None) -> Job | None:
        """Mark a job as COMPLETED.

        Args:
            job_id: The job ID.
            result: Optional result payload.

        Returns:
            The updated Job, or None if not found.
        """
        job = await self._get_job(job_id)
        if job is None:
            return None

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.result = result
        job.progress = JobProgress(percentage=100.0, current_stage="completed", message="Job completed successfully.")

        pipe = self._redis.pipeline()
        meta_key = f"{QUEUE_JOB_META}{job_id}"
        pipe.hset(meta_key, mapping=self._job_to_hash(job))
        pipe.srem(QUEUE_RUNNING, str(job_id))
        await pipe.execute()

        logger.info(
            "Job completed",
            extra={
                "job_id": str(job_id),
                "job_type": job.job_type.value if job.job_type else "unknown",
            },
        )
        return job

    async def fail_job(
        self,
        job_id: uuid.UUID,
        error_message: str,
        should_retry: bool = True,
    ) -> Job | None:
        """Mark a job as FAILED or RETRYING.

        If the job has remaining retries, schedules it for retry with
        exponential backoff. Otherwise moves to dead-letter (FAILED).

        Args:
            job_id: The job ID.
            error_message: Description of the error.
            should_retry: Whether the job type supports retry.

        Returns:
            The updated Job, or None if not found.
        """
        job = await self._get_job(job_id)
        if job is None:
            return None

        job.error_message = error_message
        job.retry_count += 1

        if should_retry and job.retry_count <= job.max_retries:
            # Schedule retry with exponential backoff
            delay = self._retry_policy.delay_for_attempt(job.retry_count - 1)
            retry_at = datetime.now(timezone.utc).timestamp() + delay
            job.status = JobStatus.RETRYING
            job.backoff_until = datetime.fromtimestamp(retry_at, tz=timezone.utc)

            pipe = self._redis.pipeline()
            meta_key = f"{QUEUE_JOB_META}{job_id}"
            pipe.hset(meta_key, mapping=self._job_to_hash(job))
            pipe.srem(QUEUE_RUNNING, str(job_id))
            pipe.zadd(QUEUE_RETRY, {str(job_id): retry_at})
            await pipe.execute()

            logger.warning(
                "Job scheduled for retry",
                extra={
                    "job_id": str(job_id),
                    "retry_count": job.retry_count,
                    "delay_seconds": delay,
                    "error": error_message,
                },
            )
        else:
            # Permanent failure — move to dead-letter
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)

            pipe = self._redis.pipeline()
            meta_key = f"{QUEUE_JOB_META}{job_id}"
            pipe.hset(meta_key, mapping=self._job_to_hash(job))
            pipe.srem(QUEUE_RUNNING, str(job_id))
            pipe.lpush(QUEUE_FAILED, str(job_id))
            await pipe.execute()

            logger.error(
                "Job failed permanently",
                extra={
                    "job_id": str(job_id),
                    "retry_count": job.retry_count,
                    "error": error_message,
                },
            )

        return job

    async def cancel_job(self, job_id: uuid.UUID) -> Job | None:
        """Cancel a job (QUEUED or RUNNING).

        Args:
            job_id: The job ID to cancel.

        Returns:
            The cancelled Job, or None if not found.
        """
        job = await self._get_job(job_id)
        if job is None:
            return None

        if job.is_terminal():
            return job

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)

        pipe = self._redis.pipeline()
        meta_key = f"{QUEUE_JOB_META}{job_id}"
        pipe.hset(meta_key, mapping=self._job_to_hash(job))
        pipe.zrem(QUEUE_QUEUED, str(job_id))
        pipe.srem(QUEUE_RUNNING, str(job_id))
        pipe.zrem(QUEUE_RETRY, str(job_id))
        await pipe.execute()

        logger.info("Job cancelled", extra={"job_id": str(job_id)})
        return job

    # ── Progress ───────────────────────────────────────────────────────────

    async def update_progress(
        self,
        job_id: uuid.UUID,
        progress: JobProgress,
    ) -> Job | None:
        """Update the progress of a running job.

        Args:
            job_id: The job ID.
            progress: Current progress state.

        Returns:
            The updated Job, or None if not found.
        """
        job = await self._get_job(job_id)
        if job is None:
            return None

        job.progress = progress
        job.heartbeat_at = datetime.now(timezone.utc)

        meta_key = f"{QUEUE_JOB_META}{job_id}"
        await self._redis.hset(meta_key, "progress", json.dumps({
            "percentage": progress.percentage,
            "current_stage": progress.current_stage,
            "message": progress.message,
            "estimated_remaining_seconds": progress.estimated_remaining_seconds,
        }))
        return job

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str) -> bool:
        """Update the heartbeat for a running job.

        Args:
            job_id: The job ID.
            worker_id: Worker identifier.

        Returns:
            True if the heartbeat was updated.
        """
        now = datetime.now(timezone.utc)
        meta_key = f"{QUEUE_JOB_META}{job_id}"
        result = await self._redis.hset(meta_key, "heartbeat_at", now.isoformat())
        return result is not None

    # ── Queries ────────────────────────────────────────────────────────────

    async def get_job(self, job_id: uuid.UUID) -> Job | None:
        """Retrieve a single job by ID.

        Args:
            job_id: The job ID.

        Returns:
            The Job, or None if not found.
        """
        return await self._get_job(job_id)

    async def list_jobs(
        self,
        user_id: uuid.UUID | None = None,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Job], int]:
        """List jobs with optional filtering and pagination.

        Args:
            user_id: Optional filter by user.
            status: Optional filter by status.
            job_type: Optional filter by job type.
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            Tuple of (list of Jobs, total count).
        """
        # Scan all job meta keys
        cursor = 0
        all_jobs: list[Job] = []
        pattern = f"{QUEUE_JOB_META}*"

        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                data = await self._redis.hgetall(key)
                if not data:
                    continue
                job = self._hash_to_job(data, key.replace(QUEUE_JOB_META, ""))
                if job is None:
                    continue

                # Apply filters
                if user_id and job.user_id != user_id:
                    continue
                if status and job.status != status:
                    continue
                if job_type and job.job_type != job_type:
                    continue

                all_jobs.append(job)

            if cursor == 0:
                break

        # Sort by created_at descending
        all_jobs.sort(key=lambda j: j.created_at, reverse=True)

        total = len(all_jobs)
        start = (page - 1) * page_size
        end = start + page_size
        return all_jobs[start:end], total

    async def count_by_status(self) -> dict[str, int]:
        """Count jobs by status.

        Returns:
            Dict of status → count.
        """
        queued = await self._redis.zcard(QUEUE_QUEUED)
        running = await self._redis.scard(QUEUE_RUNNING)
        retry = await self._redis.zcard(QUEUE_RETRY)
        failed = await self._redis.llen(QUEUE_FAILED)

        return {
            "queued": queued,
            "running": running,
            "retrying": retry,
            "failed": failed,
        }

    async def health(self) -> dict[str, Any]:
        """Get queue health statistics.

        Returns:
            Dict with queue health metrics.
        """
        counts = await self.count_by_status()
        return {
            "status": "ok",
            **counts,
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _get_job(self, job_id: uuid.UUID) -> Job | None:
        """Internal: fetch a job from its Redis hash."""
        meta_key = f"{QUEUE_JOB_META}{job_id}"
        data = await self._redis.hgetall(meta_key)
        if not data:
            return None
        return self._hash_to_job(data, str(job_id))

    def _job_to_hash(self, job: Job) -> dict[str, str]:
        """Serialize a Job to a Redis hash-compatible dictionary."""
        return {
            "job_id": str(job.job_id),
            "job_type": job.job_type.value,
            "status": job.status.value,
            "priority": job.priority.value,
            "user_id": str(job.user_id) if job.user_id else "",
            "session_id": str(job.session_id) if job.session_id else "",
            "created_at": job.created_at.isoformat() if job.created_at else "",
            "started_at": job.started_at.isoformat() if job.started_at else "",
            "completed_at": job.completed_at.isoformat() if job.completed_at else "",
            "retry_count": str(job.retry_count),
            "max_retries": str(job.max_retries),
            "error_message": job.error_message or "",
            "backoff_until": job.backoff_until.isoformat() if job.backoff_until else "",
            "progress": json.dumps({
                "percentage": job.progress.percentage,
                "current_stage": job.progress.current_stage,
                "message": job.progress.message,
                "estimated_remaining_seconds": job.progress.estimated_remaining_seconds,
            }),
            "payload": json.dumps(job.payload),
            "metadata": json.dumps(job.metadata),
            "result": json.dumps(job.result) if job.result else "",
            "worker_id": job.worker_id or "",
            "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else "",
        }

    def _hash_to_job(self, data: dict[str, str], job_id_str: str) -> Job | None:
        """Deserialize a Redis hash to a Job."""
        try:
            job_id = uuid.UUID(job_id_str)
        except ValueError:
            return None

        prog_data = json.loads(data.get("progress", "{}"))
        payload = json.loads(data.get("payload", "{}"))
        meta = json.loads(data.get("metadata", "{}"))
        result_raw = data.get("result", "")
        result = json.loads(result_raw) if result_raw else None

        return Job(
            job_id=job_id,
            job_type=JobType(data.get("job_type", "notification")),
            status=JobStatus(data.get("status", "queued")),
            priority=JobPriority(data.get("priority", "default")),
            user_id=uuid.UUID(data["user_id"]) if data.get("user_id") else None,
            session_id=uuid.UUID(data["session_id"]) if data.get("session_id") else None,
            created_at=self._parse_dt(data.get("created_at", "")),
            started_at=self._parse_dt(data.get("started_at")),
            completed_at=self._parse_dt(data.get("completed_at")),
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            error_message=data.get("error_message") or None,
            backoff_until=self._parse_dt(data.get("backoff_until")),
            progress=JobProgress(
                percentage=float(prog_data.get("percentage", 0)),
                current_stage=prog_data.get("current_stage", "initializing"),
                message=prog_data.get("message", ""),
                estimated_remaining_seconds=prog_data.get("estimated_remaining_seconds"),
            ),
            payload=payload,
            metadata=meta,
            result=result,
            worker_id=data.get("worker_id") or None,
            heartbeat_at=self._parse_dt(data.get("heartbeat_at")),
        )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        """Parse an ISO datetime string or return None."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
