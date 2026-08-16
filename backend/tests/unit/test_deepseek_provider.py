from __future__ import annotations

import httpx
import pytest

from app.llm.providers.base import ProviderConfig, ProviderTimeoutError
from app.llm.providers.deepseek import DeepSeekProvider


class _FakeDeepSeekClient:
    def __init__(self, events: list[object]):
        self._events = list(events)
        self.calls = 0
        self.timeouts: list[httpx.Timeout | None] = []

    async def post(self, path: str, json: dict, timeout: httpx.Timeout | None = None) -> httpx.Response:
        self.calls += 1
        self.timeouts.append(timeout)
        event = self._events[self.calls - 1]
        if isinstance(event, Exception):
            raise event
        return event


def _ok_response() -> httpx.Response:
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    return httpx.Response(
        200,
        request=request,
        json={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


@pytest.mark.asyncio
async def test_generate_retries_httpx_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = DeepSeekProvider(config=ProviderConfig(retry_count=2, timeout_seconds=30.0))
    fake_client = _FakeDeepSeekClient(
        [httpx.ReadTimeout("request timeout"), _ok_response()]
    )
    provider._client = fake_client

    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("app.llm.providers.deepseek.asyncio.sleep", _fake_sleep)

    response = await provider.generate("test prompt", timeout_seconds=55.0)

    assert response.content == "ok"
    assert fake_client.calls == 2
    assert delays == [2]
    assert fake_client.timeouts[0] is not None
    assert fake_client.timeouts[0].read == 55.0


@pytest.mark.asyncio
async def test_generate_retries_string_timeout_then_raises_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = DeepSeekProvider(config=ProviderConfig(retry_count=1, timeout_seconds=30.0))
    fake_client = _FakeDeepSeekClient(
        [RuntimeError("request timed out"), RuntimeError("request timed out")]
    )
    provider._client = fake_client

    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("app.llm.providers.deepseek.asyncio.sleep", _fake_sleep)

    with pytest.raises(ProviderTimeoutError, match="timed out after 45.0s"):
        await provider.generate("test prompt", timeout_seconds=45.0)

    assert fake_client.calls == 2
    assert delays == [2]
