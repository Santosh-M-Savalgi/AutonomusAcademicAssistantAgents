"""add_username_is_active_last_login_to_users

Revision ID: a1b2c3d4e5f6
Revises: 5e0d4ce4b303
Create Date: 2026-07-17 15:00:00.000000

Adds username, is_active, and last_login columns to the users table.
Adds unique index on username.
Preserves all existing data.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "5e0d4ce4b303"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add username column (nullable first to backfill, then set NOT NULL) ---
    op.add_column(
        "users",
        sa.Column("username", sa.String(150), nullable=True),
    )

    # Backfill existing rows with a username derived from the email prefix
    # Using the part before '@' in email, sanitized for DB constraints.
    # If the email prefix is empty or produces a duplicate, append a suffix.
    op.execute(
        sa.text(
            "UPDATE users "
            "SET username = split_part(email, '@', 1) "
            "WHERE username IS NULL"
        )
    )

    # Handle potential duplicates from email prefix collisions
    # by appending a suffix to the username.
    op.execute(
        sa.text(
            "UPDATE users u "
            "SET username = username || '_' || substr(md5(u.id::text), 1, 6) "
            "WHERE EXISTS ("
            "  SELECT 1 FROM users u2 "
            "  WHERE u2.username = u.username AND u2.id != u.id AND u2.id < u.id"
            ")"
        )
    )

    # Now set username to NOT NULL and add unique constraint + index
    op.alter_column("users", "username", nullable=False)
    op.create_index("ix_users_username", "users", ["username"])
    op.create_unique_constraint("users_username_key", "users", ["username"])

    # --- Add is_active column ---
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # --- Add last_login column (nullable is fine) ---
    op.add_column(
        "users",
        sa.Column(
            "last_login",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint("users_username_key", "users", type_="unique")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")
    op.drop_column("users", "is_active")
    op.drop_column("users", "last_login")
