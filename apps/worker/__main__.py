"""Standalone worker process: python -m apps.worker (no automatic migrations)."""

import asyncio
import os
import signal
from contextlib import AsyncExitStack

import structlog

from apps.api.config import get_settings
from apps.api.logging import configure_logging
from apps.worker.config import WorkerSettings
from apps.worker.extraction_config import ExtractionSettings
from apps.worker.runner import Worker
from apps.worker.syllabus import create_handler_registry
from packages.persistence import Database, RedisClient
from packages.persistence.job_wakeups import RedisWakeups, notify_job_events
from packages.persistence.jobs import JobRepository


async def main() -> None:
    settings = get_settings()
    config = WorkerSettings()
    configure_logging(settings.log_level, service="aaa-worker")
    logger = structlog.get_logger("aaa.worker")
    if not config.enabled:
        logger.info("worker_disabled")
        return
    database = Database(settings.database_url)
    redis = RedisClient(settings.redis_url)
    jobs = JobRepository(database, retry_base=config.retry_base_seconds,
                         retry_max=config.retry_max_seconds)
    worker = Worker(
        jobs,
        create_handler_registry(database, settings, ExtractionSettings()),
        config, wakeups=RedisWakeups(redis),
        progress_notifier=lambda job_id: notify_job_events(redis, job_id),
    )
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, worker.stop)
    try:
        async with AsyncExitStack() as stack:
            stack.push_async_callback(redis.close)
            stack.push_async_callback(database.close)
            await worker.run()
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
    if worker.unfinished_handlers:
        # asyncio.run would otherwise wait forever for tasks suppressing cancellation.
        # Resources are closed; stop the process so orphaned handlers cannot keep running.
        logger.error("worker_handler_did_not_stop")
        os._exit(1)


if __name__ == "__main__":
    asyncio.run(main())
