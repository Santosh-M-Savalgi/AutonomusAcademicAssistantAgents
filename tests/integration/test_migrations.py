"""Migration wiring and real upgrade/downgrade tests on disposable PostgreSQL."""

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from packages.persistence import Database, StudentIdentity

ROOT = Path(__file__).parents[2]


def test_alembic_has_a_runtime_foundation_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0013_sprint37_block_b"]
    assert (ROOT / "alembic" / "env.py").exists()


@pytest.mark.live_integration
async def test_live_migrations_are_repeatable(
    live_database: Database, migrate_database: Callable[..., None],
) -> None:
    await asyncio.to_thread(migrate_database)
    await asyncio.to_thread(migrate_database)
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0013_sprint37_block_b"
        )
    await asyncio.to_thread(migrate_database, "downgrade", "base")
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    await asyncio.to_thread(migrate_database)


@pytest.mark.live_integration
async def test_populated_identity_downgrade_is_refused(
    live_database: Database, migrate_database: Callable[..., None], service_settings,
) -> None:
    await asyncio.to_thread(migrate_database)
    async with live_database.session() as session, session.begin():
        session.add(StudentIdentity(
            id=uuid4(),
            provider_namespace="jwt:test:api",
            external_subject="downgrade-subject",
        ))

    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "0005_job_progress_events"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": service_settings.database_url},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "downgrade refused" in (result.stdout + result.stderr)
