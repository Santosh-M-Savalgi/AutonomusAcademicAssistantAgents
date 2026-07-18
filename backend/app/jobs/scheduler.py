"""Job Scheduler — recurring scheduled job management.

Supports cron-like scheduling for nightly maintenance tasks such as
analytics refresh, session cleanup, and checkpoint purging.

Reference: Sprint 9 Part 7.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from app.jobs.models import JobPriority, JobType

logger = logging.getLogger(__name__)


class ScheduledTask:
    """A single scheduled recurring task definition."""

    def __init__(
        self,
        name: str,
        job_type: JobType,
        cron_expression: str,
        callback: Callable | None = None,
        payload: dict | None = None,
        priority: JobPriority = JobPriority.LOW,
    ) -> None:
        """Initialize a scheduled task.

        Args:
            name: Human-readable task name.
            job_type: The JobType to enqueue when triggered.
            cron_expression: Simplified cron expression (supports 'daily @ HH:MM').
            callback: Optional async callback to run when triggered.
            payload: Optional job payload.
            priority: Job priority for scheduled tasks.
        """
        self.name = name
        self.job_type = job_type
        self.cron_expression = cron_expression
        self.callback = callback
        self.payload = payload or {}
        self.priority = priority
        self._last_run: datetime | None = None

    def should_run(self, now: datetime) -> bool:
        """Check if this task should run at the given time.

        Args:
            now: Current time.

        Returns:
            True if the task should be triggered.
        """
        if self._last_run and self._last_run.date() == now.date():
            return False  # Already ran today

        if self.cron_expression.startswith("daily @ "):
            run_time_str = self.cron_expression.replace("daily @ ", "")
            try:
                run_hour, run_min = run_time_str.split(":")
                run_hour = int(run_hour.strip())
                run_min = int(run_min.strip())
                return now.hour == run_hour and now.minute == run_min
            except (ValueError, IndexError):
                pass

        return False

    def mark_run(self, now: datetime) -> None:
        """Mark this task as having run.

        Args:
            now: Current time.
        """
        self._last_run = now


# ── Default Schedules ──────────────────────────────────────────────────────


DEFAULT_SCHEDULED_TASKS: list[ScheduledTask] = [
    ScheduledTask(
        name="Nightly Analytics Refresh",
        job_type=JobType.COMPUTE_ANALYTICS,
        cron_expression="daily @ 02:00",
        priority=JobPriority.LOW,
        payload={"scope": "all_users"},
    ),
    ScheduledTask(
        name="Recommendation Recalculation",
        job_type=JobType.REFRESH_RECOMMENDATIONS,
        cron_expression="daily @ 03:00",
        priority=JobPriority.LOW,
        payload={"scope": "all_users"},
    ),
    ScheduledTask(
        name="Inactive Learner Cleanup",
        job_type=JobType.EXPIRE_SESSIONS,
        cron_expression="daily @ 04:00",
        priority=JobPriority.LOW,
    ),
    ScheduledTask(
        name="Expired Session Cleanup",
        job_type=JobType.EXPIRE_SESSIONS,
        cron_expression="daily @ 04:30",
        priority=JobPriority.LOW,
    ),
    ScheduledTask(
        name="Old Checkpoint Cleanup",
        job_type=JobType.CLEANUP_CHECKPOINTS,
        cron_expression="daily @ 05:00",
        priority=JobPriority.LOW,
    ),
    ScheduledTask(
        name="Adaptive Data Rebuild",
        job_type=JobType.REBUILD_ADAPTIVE,
        cron_expression="daily @ 06:00",
        priority=JobPriority.LOW,
    ),
]


# ── Scheduler ──────────────────────────────────────────────────────────────


class JobScheduler:
    """Manage recurring scheduled jobs.

    Checks every 60 seconds whether any scheduled tasks should be triggered.
    When a task is due, it enqueues a job of the appropriate type.

    Usage::

        scheduler = JobScheduler(enqueue_callback)
        await scheduler.start()
        # ... in background ...
        await scheduler.stop()
    """

    CHECK_INTERVAL_SECONDS: int = 60

    def __init__(
        self,
        enqueue_callback: Callable,
        tasks: list[ScheduledTask] | None = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            enqueue_callback: Async callable that takes (job_type, payload, priority).
            tasks: Optional custom task list. Uses defaults if None.
        """
        self._enqueue = enqueue_callback
        self._tasks = tasks if tasks is not None else DEFAULT_SCHEDULED_TASKS
        self._running = False
        self._loop_task: asyncio.Task | None = None

    @property
    def tasks(self) -> list[ScheduledTask]:
        """Get the list of registered tasks (read-only)."""
        return list(self._tasks)

    def add_task(self, task: ScheduledTask) -> None:
        """Add a scheduled task.

        Args:
            task: The task to add.
        """
        self._tasks.append(task)
        logger.info("Scheduled task added", extra={"task_name": task.name})

    def remove_task(self, name: str) -> bool:
        """Remove a scheduled task by name.

        Args:
            name: Task name to remove.

        Returns:
            True if a task was removed.
        """
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.name != name]
        return len(self._tasks) < before

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            logger.warning("Scheduler already running.")
            return

        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "Job scheduler started",
            extra={"scheduled_tasks": len(self._tasks)},
        )

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Job scheduler stopped.")

    async def run_pending(self) -> int:
        """Check and run all pending scheduled tasks.

        Called by the scheduler loop or externally for manual trigger.

        Returns:
            Number of tasks triggered.
        """
        now = datetime.now(timezone.utc)
        triggered = 0

        for task in self._tasks:
            if task.should_run(now):
                logger.info(
                    "Scheduled task triggered",
                    extra={"task_name": task.name, "job_type": task.job_type.value},
                )
                try:
                    if task.callback:
                        await task.callback()
                    else:
                        await self._enqueue(task.job_type, task.payload, task.priority)
                    task.mark_run(now)
                    triggered += 1
                except Exception:
                    logger.exception(
                        "Scheduled task failed",
                        extra={"task_name": task.name},
                    )

        return triggered

    # ── Scheduler Loop ─────────────────────────────────────────────────────

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop — periodically checks for pending tasks."""
        while self._running:
            try:
                triggered = await self.run_pending()
                if triggered > 0:
                    logger.info(
                        "Scheduled tasks triggered",
                        extra={"count": triggered},
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
