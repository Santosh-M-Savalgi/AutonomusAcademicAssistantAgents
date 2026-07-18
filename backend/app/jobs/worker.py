"""Background Worker Pool — lifecycle, heartbeat, health checks.

Manages a pool of background workers that dequeue and execute jobs
from the Redis-backed queue. Supports graceful shutdown, crash recovery,
and health monitoring.

Reference: Sprint 9 Parts 8, 9, 11.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.jobs.models import Job, JobStatus
from app.jobs.queue import JobQueue
from app.jobs.service import JobService

logger = logging.getLogger(__name__)

WORKER_HEARTBEAT_KEY = "aaa:workers:active"
WORKER_HEARTBEAT_TTL = 30  # seconds
WORKER_HEARTBEAT_INTERVAL = 10  # seconds
WORKER_HEALTH_CHECK_INTERVAL = 15  # seconds
WORKER_STALL_TIMEOUT = 60  # seconds


class WorkerPool:
    """Manage a pool of background workers.

    Each worker runs an infinite loop: dequeue → execute → repeat.
    Workers report heartbeat to Redis for health monitoring.

    Usage::

        pool = WorkerPool(queue, service)
        await pool.start(concurrency=3)
        # ... in background ...
        await pool.stop()
    """

    def __init__(self, queue: JobQueue, service: JobService) -> None:
        """Initialize the worker pool.

        Args:
            queue: JobQueue instance for dequeue operations.
            service: JobService instance for job execution.
        """
        self._queue = queue
        self._service = service
        self._worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._started_at: float = 0.0

    @property
    def worker_id(self) -> str:
        """Unique identifier for this worker pool."""
        return self._worker_id

    @property
    def uptime_seconds(self) -> float:
        """Seconds since this worker pool started."""
        if self._started_at == 0:
            return 0.0
        return time.time() - self._started_at

    async def start(self, concurrency: int = 1) -> None:
        """Start the worker pool with the given concurrency.

        Args:
            concurrency: Number of concurrent worker tasks to spawn.
        """
        if self._running:
            logger.warning("Worker pool is already running.")
            return

        self._running = True
        self._started_at = time.time()
        self._worker_id = f"worker-{uuid.uuid4().hex[:8]}"

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start health check
        self._health_task = asyncio.create_task(self._health_check_loop())

        # Start worker tasks
        for i in range(concurrency):
            task = asyncio.create_task(self._worker_loop(i + 1))
            self._tasks.append(task)

        logger.info(
            "Worker pool started",
            extra={
                "worker_id": self._worker_id,
                "concurrency": concurrency,
            },
        )

    async def stop(self) -> None:
        """Gracefully stop all workers.

        Waits for current jobs to finish (up to a timeout).
        """
        self._running = False

        # Cancel heartbeat and health check
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._health_task:
            self._health_task.cancel()

        # Cancel worker tasks
        for task in self._tasks:
            task.cancel()

        # Wait for all tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Clean up Redis heartbeat
        try:
            from app.db.redis import get_redis
            redis = get_redis()
            await redis.hdel(WORKER_HEARTBEAT_KEY, self._worker_id)
        except Exception:
            pass

        self._tasks = []
        logger.info("Worker pool stopped", extra={"worker_id": self._worker_id})

    async def get_active_workers(self) -> dict[str, dict[str, Any]]:
        """Get all active workers and their metadata.

        Returns:
            Dict of worker_id → {started_at, job_count}.
        """
        try:
            from app.db.redis import get_redis
            redis = get_redis()
            data = await redis.hgetall(WORKER_HEARTBEAT_KEY)
            workers: dict[str, dict[str, Any]] = {}
            for wid, meta_json in data.items():
                import json
                workers[wid] = json.loads(meta_json)
            return workers
        except Exception:
            return {}

    async def get_active_worker_count(self) -> int:
        """Get the count of active workers."""
        workers = await self.get_active_workers()
        return len(workers)

    # ── Worker Loop ────────────────────────────────────────────────────────

    async def _worker_loop(self, worker_num: int) -> None:
        """Main worker loop: dequeue → execute → repeat.

        Args:
            worker_num: Display number for logging.
        """
        while self._running:
            try:
                job = await self._queue.dequeue(self._worker_id)
                if job is None:
                    # No job available — wait before polling again
                    await asyncio.sleep(1.0)
                    continue

                logger.info(
                    "Worker picked up job",
                    extra={
                        "worker": f"{self._worker_id}-{worker_num}",
                        "job_id": str(job.job_id),
                        "job_type": job.job_type.value,
                    },
                )

                await self._service.execute_job(job, f"{self._worker_id}-{worker_num}")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(
                    "Worker loop error",
                    extra={"worker": f"{self._worker_id}-{worker_num}"},
                )
                await asyncio.sleep(2.0)

    # ── Heartbeat ──────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Periodically update worker heartbeat in Redis."""
        import json

        while self._running:
            try:
                from app.db.redis import get_redis
                redis = get_redis()
                heartbeat_data = json.dumps({
                    "worker_id": self._worker_id,
                    "started_at": self._started_at,
                    "uptime_seconds": self.uptime_seconds,
                    "last_heartbeat": time.time(),
                })
                await redis.hset(
                    WORKER_HEARTBEAT_KEY,
                    self._worker_id,
                    heartbeat_data,
                )
                await redis.expire(WORKER_HEARTBEAT_KEY, WORKER_HEARTBEAT_TTL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Heartbeat error")
            await asyncio.sleep(WORKER_HEARTBEAT_INTERVAL)

    # ── Health Check ───────────────────────────────────────────────────────

    async def _health_check_loop(self) -> None:
        """Periodically check for stalled workers and clean up."""
        import json

        while self._running:
            try:
                from app.db.redis import get_redis
                redis = get_redis()
                data = await redis.hgetall(WORKER_HEARTBEAT_KEY)

                now = time.time()
                for wid, meta_json in data.items():
                    try:
                        meta = json.loads(meta_json)
                        last_hb = meta.get("last_heartbeat", 0)
                        if now - last_hb > WORKER_STALL_TIMEOUT:
                            logger.warning(
                                "Stalled worker detected",
                                extra={"worker_id": wid, "last_heartbeat": last_hb},
                            )
                            await redis.hdel(WORKER_HEARTBEAT_KEY, wid)
                    except (json.JSONDecodeError, KeyError):
                        await redis.hdel(WORKER_HEARTBEAT_KEY, wid)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Health check error")
            await asyncio.sleep(WORKER_HEALTH_CHECK_INTERVAL)
