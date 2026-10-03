"""Integration checks against the isolated Phase 1 dependency services."""

import httpx
import pytest

from packages.persistence import Database, ObjectStorage, RedisClient

pytestmark = pytest.mark.live_integration


async def test_dependency_clients_reach_isolated_services(
    live_database: Database,
    live_redis: RedisClient,
    live_object_storage: ObjectStorage,
) -> None:
    """Verify the three production health probes against real service endpoints."""

    await live_database.check()
    await live_redis.check()
    await live_object_storage.check()


async def test_readyz_reports_all_isolated_dependencies(
    async_http_client: httpx.AsyncClient,
) -> None:
    """Verify the API exposes dependency-level readiness after startup."""

    response = await async_http_client.get("/readyz")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "postgresql": {"status": "ok"},
            "redis": {"status": "ok"},
            "minio": {"status": "ok"},
        },
    }
    assert (await async_http_client.get("/healthz")).status_code == 200
