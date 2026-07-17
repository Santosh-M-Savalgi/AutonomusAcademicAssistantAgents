"""LangGraph checkpoint adapter — Postgres (durable) + Redis (hot) tiers.

Section 18.1: Every checkpoint write persists to both:
1. Redis — sub-millisecond reads during active graph runs.
2. Postgres — authoritative pointer, survives Redis eviction/restart.

Read path: Redis first (fast path), fall back to Postgres (rehydration).
"""

from __future__ import annotations

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

# Redis key prefix for hot checkpoint storage
_CHECKPOINT_KEY_PREFIX = "aaa:v2:checkpoint"
# TTL on Redis checkpoint keys (seconds) — keeps hot cache bounded
_REDIS_TTL_SECONDS = 86_400  # 24 hours


class AAACheckpointSaver(BaseCheckpointSaver):
    """Two-tier LangGraph checkpoint saver for AAA v2."""

    async def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        """Retrieve the latest checkpoint for a config.

        Fast path: Redis → rehydration path: Postgres.
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return None

        redis_key = _checkpoint_key(thread_id)

        # --- Fast path: Redis ---
        try:
            redis = get_redis()
            raw = await redis.get(redis_key)
            if raw:
                import json

                data = json.loads(raw)
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
                if session is None or session.graph_checkpoint_id is None:
                    return None
                # Return a minimal checkpoint tuple carrying the pointer
                return CheckpointTuple(
                    config={"configurable": {"thread_id": thread_id}},
                    checkpoint=empty_checkpoint(),
                    metadata={
                        "source": "postgres",
                        "checkpoint_id": session.graph_checkpoint_id,
                        "path_stack": session.path_stack,
                    },
                    parent_config=None,
                )
        except Exception:
            return None

    async def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, str],
    ) -> dict[str, Any]:
        """Persist a checkpoint to both Redis (hot) and Postgres (durable)."""
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return config

        checkpoint_id = checkpoint.get("id", str(uuid.uuid4()))
        path_stack = metadata.get("path_stack")
        current_topic_id = metadata.get("current_topic_id")

        # --- Tier 1: Redis (hot, best-effort) ---
        try:
            import json

            redis = get_redis()
            redis_key = _checkpoint_key(thread_id)
            payload = json.dumps(
                {
                    "checkpoint": _serialize_checkpoint(checkpoint),
                    "metadata": metadata,
                    "parent_config": config,
                },
                default=str,
            )
            await redis.set(redis_key, payload, ex=_REDIS_TTL_SECONDS)
        except Exception:
            pass  # Redis failure is non-fatal; Postgres is authoritative

        # --- Tier 2: Postgres (durable, synchronous) ---
        thread_uuid = uuid.UUID(thread_id)
        factory = get_session_factory()
        async with factory() as db:
            await upsert_session_checkpoint(
                db,
                thread_uuid,
                graph_checkpoint_id=checkpoint_id,
                path_stack=path_stack,
                current_topic_id=(
                    uuid.UUID(current_topic_id)
                    if isinstance(current_topic_id, str)
                    else current_topic_id
                ),
            )
            await db.commit()

        return config

    async def put_writes(
        self,
        config: dict[str, Any],
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Store intermediate writes (no-op for now — stored inline in checkpoint)."""
        # In this design, pending writes travel inside the checkpoint payload.
        pass

    async def list(
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
                yield CheckpointTuple(
                    config={"configurable": {"thread_id": thread_id}},
                    checkpoint=empty_checkpoint(),
                    metadata={
                        "source": "postgres",
                        "checkpoint_id": session.graph_checkpoint_id,
                        "path_stack": session.path_stack,
                    },
                    parent_config=None,
                )
        except Exception:
            return


def _checkpoint_key(thread_id: str) -> str:
    return f"{_CHECKPOINT_KEY_PREFIX}:{thread_id}"


def _serialize_checkpoint(checkpoint: Checkpoint) -> dict[str, Any]:
    """Convert a Checkpoint to a JSON-serializable dict."""
    import json

    # Checkpoints are dict-like; copy and ensure JSON-safe values
    data = dict(checkpoint) if isinstance(checkpoint, dict) else {}
    # Convert any non-serializable values to strings
    return json.loads(json.dumps(data, default=str))


def _deserialize_checkpoint(data: dict[str, Any]) -> Checkpoint:
    """Reconstitute a Checkpoint from a plain dict."""
    return data
