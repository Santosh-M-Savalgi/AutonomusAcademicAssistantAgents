"""Loss-tolerant Redis pub/sub hints. Messages contain no job identity or state."""

import asyncio
from contextlib import suppress
from uuid import UUID

import structlog

from packages.persistence.redis import RedisClient

JOB_WAKEUP_CHANNEL = "aaa:v3:jobs:wakeup"
logger = structlog.get_logger("aaa.jobs")


async def notify_jobs(redis: RedisClient, timeout: float = 0.5) -> bool:
    """Call only after committing the job; publication failure is non-authoritative."""

    try:
        async with asyncio.timeout(timeout):
            await redis.client.publish(JOB_WAKEUP_CHANNEL, "wake")
    except Exception:
        logger.warning("job_wakeup_publish_failed")
        return False
    return True


def job_event_channel(job_id: UUID) -> str:
    # Event hints share the existing loss-tolerant channel and carry no job state.
    return JOB_WAKEUP_CHANNEL


async def notify_job_events(redis: RedisClient, job_id: UUID, timeout: float = 0.5) -> bool:
    """Publish a non-authoritative hint after a PostgreSQL event commit."""

    try:
        async with asyncio.timeout(timeout):
            await redis.client.publish(job_event_channel(job_id), "event")
    except Exception:
        logger.warning("job_event_publish_failed", job_id=str(job_id))
        return False
    return True


async def wait_for_job_events(redis: RedisClient, job_id: UUID, timeout: float = 1) -> bool:
    """Wait for a hint; callers must always poll PostgreSQL before/after waiting."""

    subscription = redis.client.pubsub()
    try:
        async with asyncio.timeout(timeout):
            await subscription.subscribe(job_event_channel(job_id))
            while True:
                message = await subscription.get_message(timeout=timeout)
                if message is not None and message.get("type") == "message":
                    return True
    except Exception:
        return False
    finally:
        with suppress(Exception):
            async with asyncio.timeout(timeout):
                await subscription.aclose()  # type: ignore[no-untyped-call]
    return False


class RedisWakeups:
    def __init__(self, redis: RedisClient, *, timeout: float = 1, reconnect: float = 2):
        self.redis = redis
        self.timeout = timeout
        self.reconnect = reconnect

    async def listen(self, wake: asyncio.Event, stop: asyncio.Event) -> None:
        """Reconnect independently; PostgreSQL slots keep polling even while Redis is down."""

        while not stop.is_set():
            subscription = self.redis.client.pubsub()
            try:
                async with asyncio.timeout(self.timeout):
                    await subscription.subscribe(JOB_WAKEUP_CHANNEL)
                while not stop.is_set():
                    async with asyncio.timeout(self.timeout + 1):
                        message = await subscription.get_message(timeout=self.timeout)
                    # Subscribe acknowledgement also triggers a poll, covering reconnect races.
                    if message is not None:
                        wake.set()
            except Exception:
                logger.warning("job_wakeup_disconnected")
            finally:
                with suppress(Exception):
                    async with asyncio.timeout(self.timeout):
                        await subscription.aclose()  # type: ignore[no-untyped-call]
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.reconnect)
