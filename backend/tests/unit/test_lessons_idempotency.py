from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.api.v2.lessons import (
    LessonRequest,
    _acquire_lesson_inflight_lock,
    _checkpoint_channel_values,
    _release_lesson_inflight_lock,
    _should_resume_from_checkpoint,
)


@dataclass
class _CheckpointTupleStub:
    checkpoint: dict


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def get(self, key: str):
        return self._store.get(key)

    async def delete(self, key: str):
        if key in self._store:
            del self._store[key]
            return 1
        return 0


def _request(**overrides) -> LessonRequest:
    base = {
        "topic_id": "topic-1",
        "topic_name": "Topic 1",
        "session_id": "session-1",
    }
    base.update(overrides)
    return LessonRequest(**base)


def test_should_resume_when_same_topic_lesson_exists_and_phase_quiz() -> None:
    request = _request()
    channel_values = {
        "current_topic_id": "topic-1",
        "lesson": {"title": "lesson"},
        "phase": "quiz",
    }

    decision = _should_resume_from_checkpoint(
        request=request,
        checkpoint_channel_values=channel_values,
    )

    assert decision.should_return_checkpoint is True
    assert decision.checkpoint_channel_values == channel_values


def test_should_not_resume_when_topic_changed() -> None:
    request = _request(topic_id="topic-2")
    channel_values = {
        "current_topic_id": "topic-1",
        "lesson": {"title": "lesson"},
        "phase": "quiz",
    }

    decision = _should_resume_from_checkpoint(
        request=request,
        checkpoint_channel_values=channel_values,
    )

    assert decision.should_return_checkpoint is False
    assert decision.reason == "topic-changed"


def test_should_require_explicit_retry_after_checkpoint_error() -> None:
    request = _request(retry_on_error=False)
    channel_values = {
        "current_topic_id": "topic-1",
        "lesson": {"title": "lesson"},
        "phase": "quiz",
        "error": "Lesson generation failed",
    }

    blocked = _should_resume_from_checkpoint(
        request=request,
        checkpoint_channel_values=channel_values,
    )
    assert blocked.should_return_checkpoint is True

    retried = _should_resume_from_checkpoint(
        request=_request(retry_on_error=True),
        checkpoint_channel_values=channel_values,
    )
    assert retried.should_return_checkpoint is False
    assert retried.reason == "explicit-retry-after-error"


def test_checkpoint_channel_values_extracts_channel_values() -> None:
    checkpoint_tuple = _CheckpointTupleStub(
        checkpoint={"channel_values": {"lesson": {"title": "lesson"}}}
    )

    values = _checkpoint_channel_values(checkpoint_tuple)
    assert values.get("lesson", {}).get("title") == "lesson"


@pytest.mark.asyncio
async def test_lesson_inflight_lock_blocks_second_request(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr("app.api.v2.lessons.get_redis", lambda: fake_redis)

    acquired_first = await _acquire_lesson_inflight_lock("thread-1", "topic-1", "token-1")
    acquired_second = await _acquire_lesson_inflight_lock("thread-1", "topic-1", "token-2")

    assert acquired_first is True
    assert acquired_second is False

    await _release_lesson_inflight_lock("thread-1", "topic-1", "token-1")
    acquired_after_release = await _acquire_lesson_inflight_lock("thread-1", "topic-1", "token-3")
    assert acquired_after_release is True
