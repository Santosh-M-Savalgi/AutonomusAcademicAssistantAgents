"""Redis-backed checkpoint store for durable session persistence (Sprint 5).

Provides save/load/resume/delete operations for session checkpoints
using the existing Redis infrastructure with namespaced keys.

Key pattern: ``aaa:sessions:{session_id}``

The checkpoint store is the hot-path persistence layer. All session
data goes through Redis first, with optional Postgres durability.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.redis import get_redis

logger = logging.getLogger(__name__)

# Redis key prefix for session data
_SESSION_KEY_PREFIX = "aaa:sessions"

# TTL for active session data in Redis (seconds)
_ACTIVE_TTL_SECONDS = 86_400  # 24 hours

# TTL for idle session data (longer retention for recovery)
_IDLE_TTL_SECONDS = 604_800  # 7 days


def _session_key(session_id: str) -> str:
    """Build the Redis key for a session.

    Args:
        session_id: The unique session identifier.

    Returns:
        A namespaced Redis key: ``aaa:sessions:{session_id}``.
    """
    return f"{_SESSION_KEY_PREFIX}:{session_id}"


def _resolve_redis() -> Any:
    """Resolve the Redis client, handling missing ``redis`` package gracefully.

    Returns:
        A Redis client instance from ``get_redis()``.

    Raises:
        RuntimeError: If the ``redis`` package is not installed and no
            client was injected.
    """
    try:
        from app.db.redis import get_redis

        return get_redis()
    except ModuleNotFoundError:
        raise RuntimeError(
            "The 'redis' package is required for session persistence. "
            "Install it with: pip install redis. "
            "In tests, inject a mock redis_client into RedisCheckpointBackend."
        )


class RedisCheckpointBackend:
    """Redis-backed persistence for session checkpoints.

    This backend handles serialization, key management, and TTL
    for checkpoint data. It reuses the existing ``get_redis()``
    connection from ``app.db.redis``.

    All data is stored as JSON strings. Read operations return
    ``None`` for missing keys (no exceptions).
    """

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client or _resolve_redis()

    # ── Core CRUD ──────────────────────────────────────────────────────────

    async def save(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """Save session data to Redis.

        Args:
            session_id: The session identifier.
            data: A JSON-serializable dict of session data.
            ttl: Time-to-live in seconds. Defaults to ``_ACTIVE_TTL_SECONDS``.

        Returns:
            True if the save succeeded, False otherwise.
        """
        try:
            key = _session_key(session_id)
            payload = json.dumps(data, default=str)
            await self._redis.set(key, payload, ex=ttl or _ACTIVE_TTL_SECONDS)
            return True
        except Exception:
            logger.exception("Failed to save checkpoint for session %s", session_id)
            return False

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load session data from Redis.

        Args:
            session_id: The session identifier.

        Returns:
            The session data dict, or None if not found.
        """
        try:
            key = _session_key(session_id)
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.exception("Failed to load checkpoint for session %s", session_id)
            return None

    async def delete(self, session_id: str) -> bool:
        """Delete session data from Redis.

        Args:
            session_id: The session identifier.

        Returns:
            True if the delete succeeded (key existed), False otherwise.
        """
        try:
            key = _session_key(session_id)
            result = await self._redis.delete(key)
            return result > 0
        except Exception:
            logger.exception("Failed to delete checkpoint for session %s", session_id)
            return False

    async def exists(self, session_id: str) -> bool:
        """Check if a session checkpoint exists in Redis.

        Args:
            session_id: The session identifier.

        Returns:
            True if the session key exists.
        """
        try:
            key = _session_key(session_id)
            result = await self._redis.exists(key)
            return result > 0
        except Exception:
            return False

    # ── TTL management ────────────────────────────────────────────────────

    async def update_ttl(
        self,
        session_id: str,
        ttl: int | None = None,
    ) -> bool:
        """Refresh the TTL on an existing session key.

        Args:
            session_id: The session identifier.
            ttl: New TTL in seconds. Defaults to ``_ACTIVE_TTL_SECONDS``.

        Returns:
            True if the TTL was updated, False otherwise.
        """
        try:
            key = _session_key(session_id)
            await self._redis.expire(key, ttl or _ACTIVE_TTL_SECONDS)
            return True
        except Exception:
            logger.exception("Failed to update TTL for session %s", session_id)
            return False

    async def mark_idle(self, session_id: str) -> bool:
        """Mark a session as idle by extending its TTL.

        Idle sessions get a longer TTL so they remain recoverable
        for a longer period.

        Args:
            session_id: The session identifier.

        Returns:
            True if the TTL was updated.
        """
        return await self.update_ttl(session_id, _IDLE_TTL_SECONDS)

    async def touch(self, session_id: str) -> bool:
        """Refresh the TTL on an active session.

        This is called on every API operation to keep the session alive.

        Args:
            session_id: The session identifier.
        """
        return await self.update_ttl(session_id, _ACTIVE_TTL_SECONDS)

    # ── Listing ───────────────────────────────────────────────────────────

    async def list_session_ids(self, pattern: str = "*") -> list[str]:
        """List all session IDs matching a pattern.

        Args:
            pattern: Redis key glob pattern (appended to prefix).

        Returns:
            A list of session IDs (without the prefix).
        """
        try:
            glob = f"{_SESSION_KEY_PREFIX}:{pattern}"
            keys = await self._redis.keys(glob)
            prefix_len = len(_SESSION_KEY_PREFIX) + 1  # +1 for ':'
            return [key[prefix_len:] for key in keys]
        except Exception:
            logger.exception("Failed to list session IDs")
            return []


class CheckpointStore:
    """High-level checkpoint store for session persistence.

    Provides a simplified API for saving and loading complete session
    state, with automatic serialization/deserialization.

    ``CheckpointStore`` wraps ``RedisCheckpointBackend`` and adds
    domain-specific operations like ``save_checkpoint``,
    ``load_checkpoint``, and ``resume_checkpoint``.

    Usage::

        store = CheckpointStore()
        session_data = SessionData(...)

        # Save a checkpoint
        await store.save_checkpoint(session_data)

        # Load a checkpoint
        restored = await store.load_checkpoint(session_id)

        # Resume a checkpoint (extends TTL)
        resumed = await store.resume_checkpoint(session_id)
    """

    def __init__(self, backend: RedisCheckpointBackend | None = None) -> None:
        self._backend = backend or RedisCheckpointBackend()

    @property
    def backend(self) -> RedisCheckpointBackend:
        """Expose the underlying backend for direct operations."""
        return self._backend

    async def save_checkpoint(
        self,
        session_data: Any,
        ttl: int | None = None,
    ) -> bool:
        """Save a session checkpoint.

        Args:
            session_data: A ``SessionData`` instance (or any object with
                ``session_id`` and ``to_dict()``).
            ttl: Optional TTL override in seconds.

        Returns:
            True if the save succeeded.
        """
        if not session_data.session_id:
            logger.error("Cannot save checkpoint: no session_id")
            return False
        data = session_data.to_dict()
        return await self._backend.save(session_data.session_id, data, ttl=ttl)

    async def load_checkpoint(
        self,
        session_id: str,
    ) -> Any | None:
        """Load a session checkpoint and deserialize to ``SessionData``.

        Args:
            session_id: The session identifier.

        Returns:
            A ``SessionData`` instance, or None if not found.
        """
        from app.session.session_models import SessionData

        data = await self._backend.load(session_id)
        if data is None:
            return None
        return SessionData.from_dict(data)

    async def resume_checkpoint(
        self,
        session_id: str,
    ) -> Any | None:
        """Load a session and extend its TTL (resume from inactivity).

        This is the primary method for session recovery. It loads the
        session data and refreshes the TTL so the session stays alive.

        Args:
            session_id: The session identifier.

        Returns:
            A ``SessionData`` instance with refreshed TTL, or None.
        """
        session = await self.load_checkpoint(session_id)
        if session is None:
            return None
        await self._backend.touch(session_id)
        session.touch()
        # Re-save with updated timestamps
        await self._backend.save(session_id, session.to_dict())
        return session

    async def delete_checkpoint(self, session_id: str) -> bool:
        """Delete a session checkpoint.

        Args:
            session_id: The session identifier.

        Returns:
            True if the checkpoint was deleted.
        """
        return await self._backend.delete(session_id)

    async def mark_idle(self, session_id: str) -> bool:
        """Mark a session as idle (extended TTL, recoverable).

        Args:
            session_id: The session identifier.

        Returns:
            True if the session was marked idle.
        """
        return await self._backend.mark_idle(session_id)

    async def exists(self, session_id: str) -> bool:
        """Check if a session checkpoint exists.

        Args:
            session_id: The session identifier.

        Returns:
            True if the checkpoint exists.
        """
        return await self._backend.exists(session_id)
