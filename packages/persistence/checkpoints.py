"""Owned PostgreSQL checkpointer; Alembic provisions its isolated schema, never workers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url


@asynccontextmanager
async def draft_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    url = make_url(database_url)
    conninfo = make_conninfo(
        host=url.host, port=url.port or 5432, dbname=url.database,
        user=url.username, password=url.password, connect_timeout=5,
        options="-c search_path=curriculum_checkpoints -c statement_timeout=5000",
    )
    async with await AsyncConnection.connect(
        conninfo, autocommit=True, prepare_threshold=0, row_factory=dict_row,
    ) as connection:
        yield AsyncPostgresSaver(connection)
