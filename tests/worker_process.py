"""Crash-test child process with a deterministic blocked handler, no real processing."""

import asyncio
import os

from apps.worker.config import WorkerSettings
from apps.worker.handlers import HandlerContext, HandlerResult
from apps.worker.runner import Worker
from packages.domain.jobs import ClaimedJob
from packages.persistence import Database
from packages.persistence.jobs import JobRepository


async def blocked(job: ClaimedJob, context: HandlerContext) -> HandlerResult:
    print("HANDLER_STARTED", flush=True)
    await asyncio.Event().wait()
    return HandlerResult()


async def main() -> None:
    database = Database(os.environ["DATABASE_URL"])
    worker = Worker(JobRepository(database), {"fake": blocked}, WorkerSettings(_env_file=None))
    # Disable informational default structlog output so stdout is a synchronization pipe.
    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))
    try:
        await worker.run()
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
