"""Unit tests for AAACheckpointSaver — Postgres rehydration path.

Tests the requirement from Section 18.1: when Redis is unavailable,
the checkpointer must fall back to Postgres and return the actual
serialized checkpoint — not ``empty_checkpoint()``.
"""

from __future__ import annotations

import json as _json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langgraph.checkpoint.base import (
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    empty_checkpoint,
)


# ── Sentinel checkpoint with full session state ────────────────────────────

def _make_checkpoint() -> Checkpoint:
    """Return a realistic checkpoint with lesson/quiz/evaluation state.

    This simulates a mid-session checkpoint right after the evaluate node
    has run — the exact kind of state that must survive Redis failure.
    """
    return {  # type: ignore[return-value]
        "id": str(uuid.uuid4()),
        "ts": "2026-07-22T15:30:00Z",
        "v": 1,
        "channel_values": {
            "session_id": "9c2c6bf5-1234-4abc-9def-0123456789ab",
            "syllabus_id": "a1b2c3d4-5678-90ef-ghij-klmnopqrstuv",
            "learning_goal": "Understand Python async/await and the event loop",
            "current_topic_id": "topic-coro-001",
            "current_topic_name": "Coroutines and the Event Loop",
            "current_topic_difficulty": "intermediate",
            "lesson": _json.dumps(
                {
                    "title": "Coroutines and the Event Loop",
                    "concept": "Coroutines are functions that can suspend...",
                    "worked_example": "async def fetch_url(url):\n    ...",
                    "real_world_analogy": "A restaurant kitchen where...",
                }
            ),
            "quiz": _json.dumps(
                {
                    "questions": [
                        {
                            "id": "q1",
                            "text": "What keyword defines a coroutine?",
                            "options": ["async", "await", "yield", "defer"],
                            "correct": 0,
                        },
                        {
                            "id": "q2",
                            "text": "What does 'await' do in an async function?",
                            "options": [
                                "Runs the coroutine in a thread pool",
                                "Suspends until the awaitable completes",
                                "Converts sync to async",
                                "Creates a new event loop",
                            ],
                            "correct": 1,
                        },
                    ]
                }
            ),
            "evaluation": _json.dumps(
                {
                    "score": 0.85,
                    "total_questions": 2,
                    "correct_count": 2,
                    "feedback": "Excellent — you got both answers right. Let's advance!",
                    "routing_decision": "NEXT_TOPIC",
                }
            ),
            "attempts_on_current": 1,
            "phase": "evaluate",
            "routing_decision": "NEXT_TOPIC",
        },
    }


def _serialize_checkpoint(checkpoint: Checkpoint) -> dict:
    """Same logic as checkpointer._serialize_checkpoint."""
    data = dict(checkpoint)
    return _json.loads(_json.dumps(data, default=str))


# ── Tests ──────────────────────────────────────────────────────────────────


class TestCheckpointerPostgresRehydration:
    """Tests for the Postgres fallback path when Redis is dead."""

    @pytest.mark.asyncio
    async def test_write_read_roundtrip_with_redis_dead(self) -> None:
        """Write a checkpoint (Redis fails), then read back from Postgres.

        The checkpoint must contain the exact lesson/quiz/evaluation state,
        not ``empty_checkpoint()``.
        """
        from app.graph.checkpointer import AAACheckpointSaver

        original_checkpoint = _make_checkpoint()
        serialized_checkpoint = _serialize_checkpoint(original_checkpoint)
        thread_id = "11111111-2222-3333-4444-555555555555"

        # ── Mock Postgres: capture writes, replay on read ────────────────
        captured_checkpoint_data: dict | None = None

        # Mock Session object — mutable so we can set checkpoint_data in write
        class MockSession:
            checkpoint_data: dict | None = None
            graph_checkpoint_id: str | None = None
            path_stack: dict | None = None
            last_active_at = None
            current_topic_id = None
            status = "active"

        mock_session = MockSession()
        mock_db = MagicMock()
        mock_db_factory = MagicMock()

        async def _mock_upsert_checkpoint(
            db, session_id, *, graph_checkpoint_id=None, path_stack=None,
            checkpoint_data=None, current_topic_id=None, status=None,
        ):
            nonlocal captured_checkpoint_data
            captured_checkpoint_data = checkpoint_data
            # Simulate what the repository does
            mock_session.checkpoint_data = checkpoint_data
            mock_session.graph_checkpoint_id = graph_checkpoint_id
            mock_session.path_stack = path_stack
            return mock_session

        # Mock get_session_by_id to return our MockSession
        async def _mock_get_session_by_id(db, session_id):
            return mock_session

        config = {"configurable": {"thread_id": thread_id}}
        metadata: CheckpointMetadata = {
            "source": "graph",
            "step": 5,
            "path_stack": {"parse": "done", "retrieve": "done", "tutor": "done"},
        }

        saver = AAACheckpointSaver()

        # --- Write: Redis fails, Postgres succeeds ---
        with (
            patch("app.graph.checkpointer.get_redis", side_effect=ConnectionError("Redis down")),
            patch("app.graph.checkpointer.get_session_factory", return_value=mock_db_factory),
            patch(
                "app.graph.checkpointer.upsert_session_checkpoint",
                _mock_upsert_checkpoint,
            ),
        ):
            # aput: __aenter__ / __aexit__ on factory context manager
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result_config = await saver.aput(
                config,
                original_checkpoint,
                metadata,
                {},  # new_versions
            )
            assert result_config["configurable"]["thread_id"] == thread_id
            assert captured_checkpoint_data is not None, (
                "checkpoint_data must be written to Postgres via upsert_session_checkpoint"
            )
            # The serialized checkpoint in Postgres must equal what we sent
            assert captured_checkpoint_data == serialized_checkpoint

        # --- Read: Redis still dead, Postgres returns the data ---
        with (
            patch("app.graph.checkpointer.get_redis", side_effect=ConnectionError("Redis down")),
            patch("app.graph.checkpointer.get_session_factory", return_value=mock_db_factory),
            patch(
                "app.graph.checkpointer.get_session_by_id",
                _mock_get_session_by_id,
            ),
        ):
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await saver.aget_tuple(config)

            assert result is not None, (
                "aget_tuple must return a CheckpointTuple from Postgres fallback"
            )
            assert isinstance(result, CheckpointTuple)

            # ── THE CORE ASSERTION ──────────────────────────────────
            checkpoint = result.checkpoint
            assert checkpoint is not empty_checkpoint(), (
                "checkpoint must not be empty_checkpoint() — "
                "the real state must be deserialized from Postgres"
            )

            # Verify channel_values survived the roundtrip
            cv = checkpoint.get("channel_values", {})
            assert cv.get("lesson") == original_checkpoint["channel_values"]["lesson"]
            assert cv.get("quiz") == original_checkpoint["channel_values"]["quiz"]
            assert cv.get("evaluation") == original_checkpoint["channel_values"]["evaluation"]
            assert cv.get("routing_decision") == "NEXT_TOPIC"
            assert cv.get("phase") == "evaluate"

            # Metadata must indicate Postgres source
            assert result.metadata.get("source") == "postgres"

    @pytest.mark.asyncio
    async def test_read_returns_none_when_no_checkpoint_data(self) -> None:
        """When a session row exists but has no checkpoint_data, return None.

        This is the case where the session was created by the API layer
        but never checkpointed by the graph.  We must NOT return
        ``empty_checkpoint()`` — that would silently mask the gap.
        """
        from app.graph.checkpointer import AAACheckpointSaver

        thread_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # Mock Session with no checkpoint_data
        mock_session = MagicMock()
        mock_session.checkpoint_data = None
        mock_session.graph_checkpoint_id = "some-checkpoint-id"

        mock_db = MagicMock()
        mock_db_factory = MagicMock()

        async def _mock_get_session_by_id(db, session_id):
            return mock_session

        saver = AAACheckpointSaver()
        config = {"configurable": {"thread_id": thread_id}}

        with (
            patch("app.graph.checkpointer.get_redis", side_effect=ConnectionError("Redis down")),
            patch("app.graph.checkpointer.get_session_factory", return_value=mock_db_factory),
            patch(
                "app.graph.checkpointer.get_session_by_id",
                _mock_get_session_by_id,
            ),
        ):
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await saver.aget_tuple(config)
            assert result is None, (
                "aget_tuple must return None when session has no checkpoint_data — "
                "a silent empty_checkpoint() would mask missing state"
            )

    @pytest.mark.asyncio
    async def test_read_returns_none_when_session_not_found(self) -> None:
        """When no session row exists at all, return None."""
        from app.graph.checkpointer import AAACheckpointSaver

        thread_id = "99999999-8888-7777-6666-555555555555"
        mock_db = MagicMock()
        mock_db_factory = MagicMock()

        async def _mock_get_session_by_id(db, session_id):
            return None

        saver = AAACheckpointSaver()
        config = {"configurable": {"thread_id": thread_id}}

        with (
            patch("app.graph.checkpointer.get_redis", side_effect=ConnectionError("Redis down")),
            patch("app.graph.checkpointer.get_session_factory", return_value=mock_db_factory),
            patch(
                "app.graph.checkpointer.get_session_by_id",
                _mock_get_session_by_id,
            ),
        ):
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await saver.aget_tuple(config)
            assert result is None

    @pytest.mark.asyncio
    async def test_alist_yields_checkpoint_from_postgres(self) -> None:
        """alist() must yield the deserialized checkpoint from Postgres."""
        from app.graph.checkpointer import AAACheckpointSaver

        original_checkpoint = _make_checkpoint()
        serialized_checkpoint = _serialize_checkpoint(original_checkpoint)
        thread_id = "feedface-dead-beef-feed-beefdeadbeef"

        mock_session = MagicMock()
        mock_session.checkpoint_data = serialized_checkpoint
        mock_session.graph_checkpoint_id = original_checkpoint["id"]
        mock_session.path_stack = {"parse": "done"}

        # mock_db doubles as the factory result AND the context-manager
        # result — factory() returns mock_db, async with factory() yields
        # await mock_db.__aenter__() which also returns mock_db.
        mock_db = MagicMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_db_factory = MagicMock(return_value=mock_db)

        async def _mock_get_session_by_id(db, session_id):
            return mock_session

        # Patch get_session_factory directly on the imported reference
        # inside the checkpointer module namespace.
        import app.graph.checkpointer as cp_mod

        saver = AAACheckpointSaver()
        config = {"configurable": {"thread_id": thread_id}}

        with (
            patch.object(cp_mod, "get_session_factory", return_value=mock_db_factory),
            patch.object(cp_mod, "get_session_by_id", _mock_get_session_by_id),
        ):
            results = [t async for t in saver.alist(config)]
            assert len(results) == 1
            result = results[0]
            cv = result.checkpoint.get("channel_values", {})
            assert cv.get("lesson") == original_checkpoint["channel_values"]["lesson"]
            assert cv.get("quiz") == original_checkpoint["channel_values"]["quiz"]
            assert cv.get("evaluation") == original_checkpoint["channel_values"]["evaluation"]
