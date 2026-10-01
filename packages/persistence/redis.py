"""Reusable async Redis client infrastructure."""

from redis.asyncio import Redis


class RedisClient:
    """Owns one async Redis connection pool."""

    def __init__(self, redis_url: str) -> None:
        self.client: Redis = Redis.from_url(redis_url, decode_responses=True)

    async def check(self) -> None:
        """Verify that Redis responds to PING."""

        if not await self.client.ping():
            raise RuntimeError("Redis did not respond to PING")

    async def close(self) -> None:
        """Close the async Redis pool."""

        await self.client.aclose()
