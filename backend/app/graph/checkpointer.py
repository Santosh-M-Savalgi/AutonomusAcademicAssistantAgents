"""LangGraph checkpoint adapter — Postgres (durable) + Redis (hot) tiers.

Section 18.1: Every checkpoint write persists to both:
1. Redis — sub-millisecond reads during active graph runs.
2. Postgres — authoritative pointer, survives Redis eviction/restart.

Read path: Redis first (fast path), fall back to Postgres (rehydration).

Async methods (aget_tuple/aput/aput_writes/alist) contain the real
implementation.  Sync methods (get_tuple/put/put_writes/list) delegate
to their async counterparts — this avoids the classic bug where
overriding a sync base method with an ``async def`` causes the base's
sync callers to receive a coroutine instead of a value.
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    empty_checkpoint,
)

from app.db.postgres import get_session_factory
from app.db.redis import get_redis
from app.db.repository import get_session_by_id, upsert_session_checkpoint

logger = logging.getLogger(__name__)

# Redis key prefix for hot checkpoint storage
_CHECKPOINT_KEY_PREFIX = "aaa:v2:checkpoint"
# TTL on Redis checkpoint keys (seconds)
_REDIS_TTL_SECONDS = 86_400  # 24 hours


def _checkpoint_key(thread_id: str) -> str:
    return f"{_CHECKPOINT_KEY_PREFIX}:{thread_id}"


def _serialize_checkpoint(checkpoint: Checkpoint) -> dict[str, Any]:
    data = dict(checkpoint) if isinstance(checkpoint, dict) else {}
    return _json.loads(_json.dumps(data, default=str))


def _deserialize_checkpoint(data: dict[str, Any]) -> Checkpoint:
    return empty_checkpoint() if not data else data


class AAACheckpointSaver(BaseCheckpointSaver):
    """Two-tier LangGraph checkpoint saver for AAA v2.

    All real logic lives in the ``a*`` async methods.  The sync methods
    delegate to them — this keeps the base class's sync callers working
    while ``ainvoke()`` / ``astream()`` get the native async path.
    """

    # ── Sync stubs (delegated to async) ────────────────────────────────────

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        raise NotImplementedError("Use aget_tuple for async access")

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, str],
    ) -> dict[str, Any]:
        raise NotImplementedError("Use aput for async access")

    def put_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        raise NotImplementedError("Use aput_writes for async access")

    def list(
        self,
        config: Optional[dict[str, Any]],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        raise NotImplementedError("Use alist for async access")

    # ── Async implementation ──────────────────────────────────────────────

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        """Retrieve the latest checkpoint for a config (async).

        Fast path: Redis → rehydration path: Postgres.
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        logger.info("aget_tuple() called: thread_id=%s", thread_id)
        if not thread_id:
            logger.warning("aget_tuple() — no thread_id, returning None")
            return None

        redis_key = _checkpoint_key(thread_id)

        # --- Fast path: Redis ---
        try:
            redis = get_redis()
            raw = await redis.get(redis_key)
            if raw:
                data = _json.loads(raw)
                checkpoint = _deserialize_checkpoint(data.get("checkpoint", {}))
                metadata = data.get("metadata", {})
                parent_config = data.get("parent_config")
                return CheckpointTuple(
                    config={"configurable": {"thread_id": thread_id}},
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                )
        except Exception:
            pass  # Redis miss or error — fall through to Postgres

        # --- Rehydration path: Postgres ---
        try:
            thread_uuid = uuid.UUID(thread_id)
            factory = get_session_factory()
            async with factory() as db:
                session = await get_session_by_id(db, thread_uuid)
                if session is None:
                    return None
                if session.checkpoint_data:
                    checkpoint = _deserialize_checkpoint(session.checkpoint_data)
                    return CheckpointTuple(
                        config={"configurable": {"thread_id": thread_id}},
                        checkpoint=checkpoint,
                        metadata={
                            "source": "postgres",
                            "checkpoint_id": (
                                session.checkpoint_data.get("id")
                                or session.graph_checkpoint_id
                            ),
                            "path_stack": session.path_stack,
                        },
                        parent_config=None,
                    )
                # No checkpoint_data — the session exists but was never checkpointed.
                # Return None rather than a silent empty state so callers can
                # distinguish "no checkpoint" from "empty checkpoint."
                logger.warning(
                    "aget_tuple() Postgres fallback: session %s has no checkpoint_data",
                    thread_id,
                )
                return None
        except Exception:
            logger.exception("aget_tuple() Postgres fallback failed for thread %s", thread_id)
            return None

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, str],
    ) -> dict[str, Any]:
        """Persist a checkpoint to both Redis and Postgres (async)."""
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.warning("aput() called with NO thread_id — returning raw config")
            return config

        checkpoint_id = checkpoint.get("id", str(uuid.uuid4()))
        path_stack = metadata.get("path_stack")
        current_topic_id = metadata.get("current_topic_id")

        # --- Tier 1: Redis (hot, best-effort) ---
        try:
            redis = get_redis()
            redis_key = _checkpoint_key(thread_id)
            payload = _json.dumps(
                {
                    "checkpoint": _serialize_checkpoint(checkpoint),
                    "metadata": metadata,
                    "parent_config": config,
                },
                default=str,
            )
            await redis.set(redis_key, payload, ex=_REDIS_TTL_SECONDS)
        except Exception:
            pass  # Redis failure is non-fatal

        # --- Tier 2: Postgres (durable, best-effort) ---
        try:
            thread_uuid = uuid.UUID(thread_id)
            factory = get_session_factory()
            async with factory() as db:
                result = await upsert_session_checkpoint(
                    db,
                    thread_uuid,
                    graph_checkpoint_id=checkpoint_id,
                    path_stack=path_stack,
                    checkpoint_data=_serialize_checkpoint(checkpoint),
                    current_topic_id=(
                        uuid.UUID(current_topic_id)
                        if isinstance(current_topic_id, str)
                        else current_topic_id
                    ),
                )
                if result is not None:
                    await db.commit()
        except Exception:
            logger.exception(
                "Postgres checkpoint write failed for thread %s",
                thread_id,
            )

        logger.info(
            "aput() CHECKPOINT SAVED: thread=%s checkpoint_id=%s path_stack=%s",
            thread_id, checkpoint_id, path_stack,
        )
        # LangGraph requires checkpoint_id in the returned config so
        # ainvoke() can track state.  MemorySaver.put() returns:
        # {"configurable": {"thread_id": ..., "checkpoint_id": ...}}
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        return_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }
        logger.info(
            "aput() RETURNING: %s",
            repr(return_config),
        )
        return return_config

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Store intermediate writes (no-op — stored inline in checkpoint)."""
        pass

    async def alist(
        self,
        config: Optional[dict[str, Any]],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """List checkpoints — yields from Postgres for the given thread."""
        if config is None:
            return

        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return

        try:
            thread_uuid = uuid.UUID(thread_id)
            factory = get_session_factory()
            async with factory() as db:
                session = await get_session_by_id(db, thread_uuid)
                if session is None:
                    return
                if session.checkpoint_data:
                    checkpoint = _deserialize_checkpoint(session.checkpoint_data)
                    yield CheckpointTuple(
                        config={"configurable": {"thread_id": thread_id}},
                        checkpoint=checkpoint,
                        metadata={
                            "source": "postgres",
                            "checkpoint_id": (
                                session.checkpoint_data.get("id")
                                or session.graph_checkpoint_id
                            ),
                            "path_stack": session.path_stack,
                        },
                        parent_config=None,
                    )
                # No checkpoint_data — silently yield nothing
        except Exception:
            logger.exception("alist() failed for thread %s", thread_id)
            return
