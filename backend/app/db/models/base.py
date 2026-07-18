"""SQLAlchemy declarative base and common mixins for AAA v2 models.

IMPORTANT: `id` is NOT declared on Base because several tables (concept_mastery,
topic_closure, preferences, student_profiles) use composite primary keys or a
user_id foreign-key PK. Each model that needs a single UUID PK must declare
``id`` explicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all AAA v2 models.

    .. note::

        ``id`` is intentionally *not* defined here because several tables
        (``concept_mastery``, ``topic_closure``, ``preferences``,
        ``student_profiles``) use composite or foreign-key primary keys.
        Each model that requires a single UUID primary-key column must
        declare it explicitly::

            id: Mapped[uuid.UUID] = mapped_column(
                UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
            )
    """
    pass


class IdMixin:
    """Mixin that adds an auto-generated UUID primary-key column named ``id``.

    Use this for every model whose database table has a single ``id`` column::

        class User(Base, IdMixin, TimestampMixin):
            __tablename__ = "users"
            ...
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Add ``created_at`` and ``updated_at`` columns with server defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
