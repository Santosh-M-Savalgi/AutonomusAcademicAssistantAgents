"""add_checkpoint_data_to_sessions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-22 00:00:00.000000

Adds ``checkpoint_data`` (JSONB) column to the ``sessions`` table so
the Postgres rehydration path in ``AAACheckpointSaver`` can return the
full serialized LangGraph Checkpoint instead of ``empty_checkpoint()``.

Section 18.1: every checkpoint write persists to both Redis (hot) and
Postgres (durable).  The existing ``graph_checkpoint_id`` column is a
pointer, not the data — this migration adds the data column itself.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("checkpoint_data", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "checkpoint_data")
