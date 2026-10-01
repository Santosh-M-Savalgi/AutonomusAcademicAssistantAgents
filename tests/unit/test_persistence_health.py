"""Unit tests for database, Redis, and MinIO connectivity probes."""

import asyncio
from types import SimpleNamespace
from typing import cast

from packages.persistence.database import Database
from packages.persistence.object_storage import ObjectStorage
from packages.persistence.redis import RedisClient


class FakeConnection:
    def __init__(self) -> None:
        self.queries: list[object] = []

    async def __aenter__(self) -> "FakeConnection":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, query: object) -> None:
        self.queries.append(query)


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeConnection:
        return self.connection


async def test_database_check_executes_a_probe_query() -> None:
    database = Database.__new__(Database)
    engine = FakeEngine()
    database.engine = cast(object, engine)  # type: ignore[assignment]

    await database.check()

    assert len(engine.connection.queries) == 1


async def test_redis_check_requires_a_successful_ping() -> None:
    redis = RedisClient.__new__(RedisClient)
    redis.client = SimpleNamespace(ping=lambda: asyncio.sleep(0, result=True))

    await redis.check()


async def test_minio_check_runs_list_buckets_without_network_in_the_test() -> None:
    storage = ObjectStorage.__new__(ObjectStorage)
    calls: list[str] = []

    class FakeMinio:
        def list_buckets(self) -> list[object]:
            calls.append("list_buckets")
            return []

    storage.client = FakeMinio()
    await storage.check()

    assert calls == ["list_buckets"]
