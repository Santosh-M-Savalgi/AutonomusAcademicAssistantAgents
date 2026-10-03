"""Fixture-owned, disposable service integration; missing Docker is explicit."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import Settings
from apps.api.runtime import RuntimeResources, create_runtime_resources
from packages.persistence import Database, ObjectStorage, RedisClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def service_ports() -> Iterator[dict[str, int]]:
    """Start a unique Compose project with random loopback ports and tmpfs data.

    No developer service endpoint or volume can be inherited. Cleanup is
    registered before startup so partially started services are also removed.
    """

    if os.getenv("AAA_RUN_SERVICE_INTEGRATION") != "1":
        pytest.skip(
            "live service integration disabled; run `make integration` to start disposable services"
        )

    compose = [
        "docker", "compose", "--env-file", "/dev/null",
        "-f", str(ROOT / "infra/compose/test.yml"),
        "-p", f"aaa-v3-test-{uuid4().hex}",
    ]

    def run(*args: str, timeout: int = 180) -> str:
        try:
            result = subprocess.run(
                [*compose, *args], cwd=ROOT, text=True, capture_output=True, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            pytest.fail(f"Isolated integration requires Docker Compose: {error}", pytrace=False)
        if result.returncode:
            pytest.fail(
                f"Isolated test services failed ({' '.join(args)}):\n{result.stderr}",
                pytrace=False,
            )
        return result.stdout

    # Check the daemon before any startup attempt; a permission failure creates nothing.
    run("ps")
    try:
        run("up", "-d", "--wait", "--wait-timeout", "90", "postgres", "redis", "minio_probe")
        yield {
            service: int(run("port", service, str(port)).strip().rsplit(":", 1)[1])
            for service, port in (("postgres", 5432), ("redis", 6379), ("minio", 9000))
        }
    finally:
        run("down", "--volumes", "--remove-orphans", timeout=60)


@pytest.fixture
async def service_settings(
    service_ports: dict[str, int], test_settings: Settings,
) -> AsyncIterator[Settings]:
    """Create a fresh database for each test on the fixture-owned PostgreSQL."""

    admin_url = f"postgresql+asyncpg://aaa_test:aaa_test@127.0.0.1:{service_ports['postgres']}/aaa_test"
    database_name = f"aaa_test_{uuid4().hex}"
    admin = Database(admin_url)
    try:
        async with admin.engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            try:
                yield test_settings.model_copy(update={
                    "database_url": make_url(admin_url).set(database=database_name)
                    .render_as_string(hide_password=False),
                    "redis_url": f"redis://127.0.0.1:{service_ports['redis']}/0",
                    "minio_endpoint": f"127.0.0.1:{service_ports['minio']}",
                    "minio_access_key": "aaa-test-minio",
                    "minio_secret_key": SecretStr("aaa-test-minio-secret"),
                    "minio_bucket": f"aaa-test-{uuid4().hex}",
                    "minio_secure": False,
                })
            finally:
                await connection.execute(text(f'DROP DATABASE "{database_name}"'))
    finally:
        await admin.close()


@pytest.fixture
def migrate_database(service_settings: Settings) -> Callable[..., None]:
    """Run the real Alembic CLI only against the fixture-created database."""

    def migrate(command: str = "upgrade", revision: str = "head") -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", command, revision], cwd=ROOT,
            env={**os.environ, "DATABASE_URL": service_settings.database_url},
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    return migrate


@pytest.fixture
async def live_runtime(service_settings: Settings) -> AsyncIterator[RuntimeResources]:
    resources = create_runtime_resources(service_settings)
    try:
        # Bounded authenticated readiness, beyond container liveness checks.
        await asyncio.wait_for(asyncio.gather(
            resources.database.check(), resources.redis.check(), resources.object_storage.check(),
        ), timeout=10)
        yield resources
    finally:
        await resources.close()


@pytest.fixture
def live_database(live_runtime: RuntimeResources) -> Database:
    return live_runtime.database


@pytest.fixture
def live_redis(live_runtime: RuntimeResources) -> RedisClient:
    return live_runtime.redis


@pytest.fixture
def live_object_storage(live_runtime: RuntimeResources) -> ObjectStorage:
    return live_runtime.object_storage


@pytest.fixture
def session_scope(
    live_database: Database,
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Rollback all test writes, even when application code commits its session."""

    @asynccontextmanager
    async def scope() -> AsyncIterator[AsyncSession]:
        async with live_database.engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection, join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as session:
                    yield session
            finally:
                await transaction.rollback()

    return scope


@pytest.fixture
async def async_session(
    session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


@pytest.fixture
async def redis_key(live_redis: RedisClient) -> AsyncIterator[str]:
    key = f"aaa-test:{uuid4().hex}"
    try:
        yield key
    finally:
        await live_redis.client.delete(key)


@pytest.fixture
async def minio_bucket(live_object_storage: ObjectStorage) -> AsyncIterator[str]:
    client = live_object_storage.client
    bucket = live_object_storage.bucket
    await asyncio.to_thread(client.make_bucket, bucket)

    def cleanup() -> None:
        for item in client.list_objects(bucket, recursive=True):
            client.remove_object(bucket, item.object_name)
        client.remove_bucket(bucket)

    try:
        yield bucket
    finally:
        await asyncio.to_thread(cleanup)


@pytest.fixture
def test_app(app_factory: Callable[..., FastAPI], service_settings: Settings) -> FastAPI:
    """Override the unit substitute: inherited HTTP clients use real resources."""

    return app_factory(service_settings)
