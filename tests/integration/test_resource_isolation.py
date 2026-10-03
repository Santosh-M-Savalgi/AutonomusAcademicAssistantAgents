"""Real persistence round trips and cleanup contracts on disposable services."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from io import BytesIO

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.persistence import Database, ObjectStorage, RedisClient

pytestmark = pytest.mark.live_integration


async def test_session_commit_is_rolled_back(
    live_database: Database,
    session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> None:
    # SQL/rows here are synthetic infrastructure data, not a domain table.
    async with live_database.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE fixture_probe (value integer NOT NULL)"))
    async with session_scope() as session:
        await session.execute(text("INSERT INTO fixture_probe VALUES (7)"))
        await session.commit()
        assert await session.scalar(text("SELECT value FROM fixture_probe")) == 7
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM fixture_probe")) == 0


async def test_async_session_executes_postgresql(async_session: AsyncSession) -> None:
    assert await async_session.scalar(text("SELECT 1")) == 1


async def test_redis_round_trip(live_redis: RedisClient, redis_key: str) -> None:
    assert await live_redis.client.get(redis_key) is None
    await live_redis.client.set(redis_key, "synthetic-test-value", ex=60)
    assert await live_redis.client.get(redis_key) == "synthetic-test-value"
    assert await live_redis.client.ttl(redis_key) > 0


async def test_minio_round_trip(live_object_storage: ObjectStorage, minio_bucket: str) -> None:
    client = live_object_storage.client
    content = b"synthetic infrastructure fixture"
    await asyncio.to_thread(
        client.put_object, minio_bucket, "probe.txt", BytesIO(content), len(content)
    )

    def read_object() -> bytes:
        response = client.get_object(minio_bucket, "probe.txt")
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    assert await asyncio.to_thread(read_object) == content
