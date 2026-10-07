"""Bounded async worker slots, independent PostgreSQL polling, and lease monitoring."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Protocol
from uuid import UUID, uuid4

import structlog

from apps.worker.config import WorkerSettings
from apps.worker.handlers import (
    HandlerContext,
    HandlerFailure,
    HandlerResult,
    JobHandler,
    ProgressContext,
)
from packages.domain.enums import JobLane, JobStatus
from packages.domain.jobs import ClaimedJob, JobErrorCode, JobEventPayload, JobEventType

logger = structlog.get_logger("aaa.worker")


class JobStore(Protocol):
    async def claim(
        self, worker_id: str, lanes: tuple[JobLane, ...], lease_seconds: float,
    ) -> ClaimedJob | None: ...
    async def heartbeat(self, job: ClaimedJob, lease_seconds: float) -> bool: ...
    async def finish(
        self, job: ClaimedJob, status: JobStatus, *,
        error_code: JobErrorCode | None = None, result_ref: str | None = None,
    ) -> bool: ...
    async def fail(self, job: ClaimedJob, code: JobErrorCode, *, retryable: bool) -> bool: ...
    async def report_progress(
        self, job: ClaimedJob, event_type: JobEventType, payload: JobEventPayload,
        idempotency_key: str,
    ) -> bool: ...
    async def reap(self, limit: int = 100) -> int: ...


class WakeupSource(Protocol):
    async def listen(self, wake: asyncio.Event, stop: asyncio.Event) -> None: ...


ProgressNotifier = Callable[[UUID], Awaitable[bool]]


class Worker:
    def __init__(
        self, store: JobStore, handlers: Mapping[str, JobHandler], settings: WorkerSettings,
        *, wakeups: WakeupSource | None = None,
        progress_notifier: ProgressNotifier | None = None,
    ) -> None:
        self.store = store
        self.handlers = dict(handlers)
        self.settings = settings
        self.worker_id = f"worker-{uuid4()}"
        self.stopping = asyncio.Event()
        self.wake = asyncio.Event()
        self.wakeups = wakeups
        self.progress_notifier = progress_notifier
        self.unfinished_handlers: set[asyncio.Task[HandlerResult]] = set()

    def stop(self) -> None:
        """Signal shutdown synchronously, before another slot can start a claim."""

        self.stopping.set()
        self.wake.set()

    async def run(self) -> None:
        if not self.settings.enabled:
            logger.info("worker_disabled")
            return
        logger.info("worker_started", worker_id=self.worker_id)
        background = [asyncio.create_task(self._reaper())]
        if self.wakeups is not None:
            background.append(asyncio.create_task(self.wakeups.listen(self.wake, self.stopping)))
        slots = [asyncio.create_task(self._slot()) for _ in range(self.settings.concurrency)]
        try:
            await asyncio.gather(*slots)
        finally:
            self.stop()
            for task in [*slots, *background]:
                task.cancel()
            await asyncio.gather(*slots, *background, return_exceptions=True)
            logger.info("worker_stopped", worker_id=self.worker_id)

    async def _slot(self) -> None:
        while not self.stopping.is_set():
            self.wake.clear()
            try:
                async with asyncio.timeout(self.settings.io_timeout_seconds):
                    job = await self.store.claim(
                        self.worker_id, self.settings.lanes, self.settings.lease_seconds,
                    )
                if job is not None:
                    await self._notify_job(job.id)
                    # A signal can arrive while a claim transaction is committing.
                    if self.stopping.is_set():
                        await self._failure(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)
                        return
                    await self.execute(job)
                    continue
            except Exception:
                # No exception message, payload, SQL parameters, or credentials in logs.
                logger.error("worker_poll_failed", worker_id=self.worker_id)
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=self.settings.poll_seconds)

    async def _reaper(self) -> None:
        while not self.stopping.is_set():
            try:
                async with asyncio.timeout(self.settings.io_timeout_seconds):
                    count = await self.store.reap()
                if count:
                    self.wake.set()
                    logger.info("worker_leases_reaped", worker_id=self.worker_id)
            except Exception:
                logger.error("worker_reaper_failed", worker_id=self.worker_id)
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stopping.wait(), timeout=self.settings.reaper_seconds)

    async def _heartbeat(self, job: ClaimedJob, lost: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.heartbeat_seconds)
                async with asyncio.timeout(self.settings.io_timeout_seconds):
                    renewed = await self.store.heartbeat(job, self.settings.lease_seconds)
                if not renewed:
                    break
        except Exception:
            logger.error("worker_heartbeat_failed", job_id=str(job.id))
        lost.set()

    async def _dispatch(self, job: ClaimedJob, context: HandlerContext) -> HandlerResult:
        handler = self.handlers.get(job.type)
        if handler is None:
            raise HandlerFailure(JobErrorCode.UNKNOWN_JOB_TYPE)
        result = await handler(job, context)
        if not isinstance(result, HandlerResult):
            raise HandlerFailure(JobErrorCode.HANDLER_EXCEPTION)
        return result

    def _cancel_handler(self, task: asyncio.Task[HandlerResult], context: HandlerContext) -> None:
        context.cancelled.set()
        if task in self.unfinished_handlers:
            return
        if not task.done():
            task.cancel()
        # Never await an uncooperative handler indefinitely or let its late return commit success.
        self.unfinished_handlers.add(task)

        def consume(done: asyncio.Task[HandlerResult]) -> None:
            self.unfinished_handlers.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(consume)

    async def _failure(self, job: ClaimedJob, code: JobErrorCode, *, retryable: bool) -> None:
        async with asyncio.timeout(self.settings.io_timeout_seconds):
            updated = await self.store.fail(job, code, retryable=retryable)
        if updated:
            await self._notify_job(job.id)

    async def _notify_job(self, job_id: UUID) -> None:
        if self.progress_notifier is None:
            return
        try:
            await self.progress_notifier(job_id)
        except Exception:
            logger.warning("job_event_notification_failed", job_id=str(job_id))

    async def _report_progress(
        self, job: ClaimedJob, event_type: JobEventType, payload: JobEventPayload,
        idempotency_key: str,
    ) -> bool:
        try:
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                updated = await self.store.report_progress(
                    job, event_type, payload, idempotency_key,
                )
        except Exception:
            logger.error("worker_progress_write_failed", job_id=str(job.id))
            return False
        if updated:
            await self._notify_job(job.id)
        return updated

    async def execute(self, job: ClaimedJob) -> None:
        """Execute one already-claimed job; all outcomes are fenced by the repository."""

        async def report(
            event_type: JobEventType, payload: JobEventPayload, idempotency_key: str,
        ) -> bool:
            return await self._report_progress(job, event_type, payload, idempotency_key)

        context = HandlerContext(
            self.worker_id, self.stopping,
            progress=ProgressContext(job_id=job.id, attempt=job.attempts, callback=report),
        )
        lost = asyncio.Event()
        handler = asyncio.create_task(self._dispatch(job, context))
        heartbeat = asyncio.create_task(self._heartbeat(job, lost))
        loss_wait = asyncio.create_task(lost.wait())
        stop_wait = asyncio.create_task(self.stopping.wait())
        try:
            await asyncio.wait([handler, loss_wait, stop_wait], return_when=asyncio.FIRST_COMPLETED)
            if self.stopping.is_set() and not handler.done() and not lost.is_set():
                await asyncio.wait(
                    [handler, loss_wait], timeout=self.settings.shutdown_grace_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            if lost.is_set():
                self._cancel_handler(handler, context)
                # Fail closed: do not claim more work while an old handler may still be running.
                self.stop()
                logger.warning("worker_lease_lost", job_id=str(job.id))
                # Unknown DB/ownership state: no more state writes from this attempt.
                return
            if not handler.done():
                self._cancel_handler(handler, context)
                await self._failure(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)
                return
            try:
                result = handler.result()
            except asyncio.CancelledError:
                if self.stopping.is_set():
                    # A handler may honor the shutdown event before the grace period elapses.
                    await self._failure(job, JobErrorCode.WORKER_SHUTDOWN, retryable=True)
                else:
                    async with asyncio.timeout(self.settings.io_timeout_seconds):
                        updated = await self.store.finish(
                            job, JobStatus.CANCELLED, error_code=JobErrorCode.CANCELLED,
                        )
                        if updated:
                            await self._notify_job(job.id)
            except HandlerFailure as error:
                await self._failure(job, error.code, retryable=error.retryable)
            except Exception:
                await self._failure(job, JobErrorCode.HANDLER_EXCEPTION, retryable=True)
            else:
                async with asyncio.timeout(self.settings.io_timeout_seconds):
                    updated = await self.store.finish(
                        job, JobStatus.SUCCEEDED, result_ref=result.result_ref,
                    )
                if updated:
                    await self._notify_job(job.id)
                    logger.info("worker_job_succeeded", job_id=str(job.id))
        except Exception as error:
            # An uncertain completion must NOT be followed by another conflicting write.
            # Leave RUNNING to expire if commit failed; handler retry effects must be idempotent.
            logger.error(
                "worker_state_write_failed",
                job_id=str(job.id), error_type=type(error).__name__,
            )
        finally:
            if not handler.done():
                self._cancel_handler(handler, context)
            for task in (heartbeat, loss_wait, stop_wait):
                task.cancel()
            await asyncio.gather(heartbeat, loss_wait, stop_wait, return_exceptions=True)
