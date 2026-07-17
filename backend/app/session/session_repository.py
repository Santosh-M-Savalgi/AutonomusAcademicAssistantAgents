"""Session repository — Postgres-backed CRUD for session metadata (Sprint 5).

Provides data-access operations for the SQLAlchemy ``Session`` model,
with support for creating, reading, updating, and deleting session records.

This repository complements the Redis-backed checkpoint store by providing
durable, queryable session metadata that survives Redis restarts.

Usage::

    repo = SessionRepository()
    async with session_factory() as db:
        session = await repo.create(db, user_id=..., session_id=...)
        session = await repo.get_by_id(db, session_id)
        await repo.update_status(db, session_id, SessionStatus.COMPLETED)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import Session as SessionModel


class SessionRepository:
    """Postgres-backed repository for ``Session`` model CRUD.

    All write operations require an explicit ``db.commit()`` call
    by the caller unless otherwise documented.
    """

    # ── Create ─────────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        current_topic_id: uuid.UUID | None = None,
        path_stack: dict | None = None,
        graph_checkpoint_id: str | None = None,
        status: str = "active",
    ) -> SessionModel:
        """Create a new session record.

        Args:
            db: An async SQLAlchemy session.
            session_id: UUID for the new session.
            user_id: UUID of the owning student.
            current_topic_id: Optional current topic UUID.
            path_stack: Optional path stack dict.
            graph_checkpoint_id: Optional LangGraph checkpoint pointer.
            status: Session status string (default: "active").

        Returns:
            The created ``Session`` model instance.
        """
        now = datetime.now(timezone.utc)
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            current_topic_id=current_topic_id,
            path_stack=path_stack,
            graph_checkpoint_id=graph_checkpoint_id,
            status=status,
            last_active_at=now,
            created_at=now,
        )
        db.add(session)
        return session

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_by_id(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> SessionModel | None:
        """Retrieve a session by its primary key.

        Args:
            db: An async SQLAlchemy session.
            session_id: The session UUID.

        Returns:
            The ``Session`` instance, or None if not found.
        """
        result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SessionModel]:
        """Retrieve sessions for a given user, most recent first.

        Args:
            db: An async SQLAlchemy session.
            user_id: The user UUID.
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip.

        Returns:
            A list of ``Session`` instances, ordered by ``last_active_at`` desc.
        """
        result = await db.execute(
            select(SessionModel)
            .where(SessionModel.user_id == user_id)
            .order_by(SessionModel.last_active_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_active_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[SessionModel]:
        """Retrieve active sessions for a given user.

        Args:
            db: An async SQLAlchemy session.
            user_id: The user UUID.

        Returns:
            A list of active ``Session`` instances.
        """
        result = await db.execute(
            select(SessionModel)
            .where(
                SessionModel.user_id == user_id,
                SessionModel.status.in_(["active", "idle"]),
            )
            .order_by(SessionModel.last_active_at.desc())
        )
        return list(result.scalars().all())

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_status(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        status: str,
    ) -> SessionModel | None:
        """Update the status of a session.

        Args:
            db: An async SQLAlchemy session.
            session_id: The session UUID.
            status: New status string (active, idle, completed, expired).

        Returns:
            The updated ``Session`` instance, or None if not found.
        """
        session = await self.get_by_id(db, session_id)
        if session is None:
            return None
        session.status = status
        session.last_active_at = datetime.now(timezone.utc)
        return session

    async def update_checkpoint(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        *,
        graph_checkpoint_id: str | None = None,
        path_stack: dict | None = None,
        current_topic_id: uuid.UUID | None = None,
    ) -> SessionModel | None:
        """Update checkpoint metadata for a session.

        Args:
            db: An async SQLAlchemy session.
            session_id: The session UUID.
            graph_checkpoint_id: Optional LangGraph checkpoint pointer.
            path_stack: Optional path stack dict.
            current_topic_id: Optional current topic UUID.

        Returns:
            The updated ``Session`` instance, or None.
        """
        session = await self.get_by_id(db, session_id)
        if session is None:
            return None
        session.last_active_at = datetime.now(timezone.utc)
        if graph_checkpoint_id is not None:
            session.graph_checkpoint_id = graph_checkpoint_id
        if path_stack is not None:
            session.path_stack = path_stack
        if current_topic_id is not None:
            session.current_topic_id = current_topic_id
        return session

    async def update_last_active(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> SessionModel | None:
        """Touch the last_active_at timestamp.

        Args:
            db: An async SQLAlchemy session.
            session_id: The session UUID.

        Returns:
            The updated ``Session`` instance, or None.
        """
        session = await self.get_by_id(db, session_id)
        if session is None:
            return None
        session.last_active_at = datetime.now(timezone.utc)
        return session

    # ── Delete ─────────────────────────────────────────────────────────────

    async def delete(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> bool:
        """Delete a session record.

        Args:
            db: An async SQLAlchemy session.
            session_id: The session UUID.

        Returns:
            True if a session was deleted, False otherwise.
        """
        session = await self.get_by_id(db, session_id)
        if session is None:
            return False
        await db.delete(session)
        return True

    async def delete_by_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int:
        """Delete all sessions for a given user.

        Args:
            db: An async SQLAlchemy session.
            user_id: The user UUID.

        Returns:
            The number of deleted sessions.
        """
        result = await db.execute(
            select(SessionModel).where(SessionModel.user_id == user_id)
        )
        sessions = list(result.scalars().all())
        for s in sessions:
            await db.delete(s)
        return len(sessions)
