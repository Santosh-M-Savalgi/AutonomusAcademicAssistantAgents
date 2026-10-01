"""Async SQLAlchemy engine, session, and base infrastructure."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for persistence models added by later phases."""


class Database:
    """Owns the async SQLAlchemy engine and session factory."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def check(self) -> None:
        """Verify that PostgreSQL accepts a lightweight query."""

        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transaction-scoped session for later persistence work."""

        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        """Dispose all pooled database connections."""

        await self.engine.dispose()


def sqlalchemy_health_query() -> Any:
    """Expose the health query for migration and test wiring without app logic."""

    return text("SELECT 1")
