"""Migration wiring and real upgrade/downgrade tests on disposable PostgreSQL."""

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from packages.persistence import Database

ROOT = Path(__file__).parents[2]


def test_alembic_has_a_runtime_foundation_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0001_runtime_foundation"]
    assert (ROOT / "alembic" / "env.py").exists()


@pytest.mark.live_integration
async def test_live_migrations_are_repeatable(
    live_database: Database, migrate_database: Callable[..., None],
) -> None:
    await asyncio.to_thread(migrate_database)
    await asyncio.to_thread(migrate_database)
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0001_runtime_foundation"
        )
    await asyncio.to_thread(migrate_database, "downgrade", "base")
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    await asyncio.to_thread(migrate_database)
