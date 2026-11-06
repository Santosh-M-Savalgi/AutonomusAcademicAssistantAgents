"""Deterministic Phase 4.4 resilience, cache, and telemetry tests."""

import asyncio

import pytest

from apps.model_gateway.cache import InMemoryCache, cache_key
from apps.model_gateway.config import GatewayConfig
from apps.model_gateway.gateway import ModelGateway
from apps.model_gateway.telemetry import GatewayTelemetryEvent, InMemoryTelemetry
from packages.model_client.contracts import GenerationRequest
from packages.model_client.errors import (
    ModelProviderError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from packages.model_client.fake import FakeProvider
from packages.model_client.policies import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    Lane,
    PriorityAdmission,
    RetryPolicy,
)


def request(
    *, lane: Lane = Lane.INTERACTIVE, cacheable: bool = False, prompt: str = "private prompt"
) -> GenerationRequest:
    return GenerationRequest(task="plain", prompt=prompt, lane=lane, cacheable=cacheable)


async def no_sleep(delay: float) -> None:
    del delay


@pytest.mark.asyncio
async def test_priority_admission_caps_and_cancellation_release_capacity() -> None:
    admission = PriorityAdmission({Lane.INTERACTIVE: 1, Lane.PREFETCH: 1, Lane.BATCH: 1})
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with admission.slot(Lane.INTERACTIVE):
            entered.set()
            await release.wait()

    first = asyncio.create_task(holder())
    await entered.wait()
    waiting = asyncio.create_task(admission.slot(Lane.INTERACTIVE).__aenter__())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert admission.active[Lane.INTERACTIVE] == 1
    release.set()
    await first
    assert admission.active[Lane.INTERACTIVE] == 0


@pytest.mark.asyncio
async def test_priority_admission_prefers_interactive_waiter() -> None:
    admission = PriorityAdmission({Lane.INTERACTIVE: 1, Lane.PREFETCH: 1, Lane.BATCH: 1})
    order: list[Lane] = []
    release = asyncio.Event()

    async def run(lane: Lane) -> None:
        async with admission.slot(lane):
            order.append(lane)
            await release.wait()

    async with admission.slot(Lane.BATCH):
        batch_waiter = asyncio.create_task(run(Lane.BATCH))
        interactive_waiter = asyncio.create_task(run(Lane.INTERACTIVE))
        await asyncio.sleep(0)
        release.set()
        await interactive_waiter
        batch_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await batch_waiter
    assert order == [Lane.INTERACTIVE]


def test_retry_policy_is_bounded_and_jitter_is_bounded() -> None:
    policy = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=0.5,
        max_delay_seconds=1.0,
        jitter_seconds=0.25,
        random_source=lambda: 1.0,
    )

    assert policy.delay_for_retry(1) == 0.75
    assert policy.delay_for_retry(2) == 1.0
    assert policy.delay_for_retry(3) == 1.0


@pytest.mark.asyncio
async def test_gateway_retries_only_retryable_provider_errors() -> None:
    retrying = FakeProvider(
        error_sequences={
            "plain": [ModelUnavailableError(provider="fake")],
        },
        response_text="recovered",
    )
    gateway = ModelGateway(
        {"fake": retrying},
        default_provider="fake",
        retry_policy=RetryPolicy(max_attempts=2, sleeper=no_sleep, jitter_seconds=0),
    )

    response = await gateway.generate(request())

    assert response.text == "recovered"
    assert len(retrying.requests) == 2
    event = gateway.telemetry.events[-1]  # type: ignore[attr-defined]
    assert event.retry_count == 1

    permanent = FakeProvider(
        error_sequences={
            "plain": [ModelProviderError(provider="fake", retryable=False)],
        }
    )
    permanent_gateway = ModelGateway(
        {"fake": permanent},
        default_provider="fake",
        retry_policy=RetryPolicy(max_attempts=3, sleeper=no_sleep, jitter_seconds=0),
    )
    with pytest.raises(ModelProviderError):
        await permanent_gateway.generate(request())
    assert len(permanent.requests) == 1


@pytest.mark.asyncio
async def test_timeout_releases_admission_capacity() -> None:
    class BlockingProvider(FakeProvider):
        async def generate(self, model_request: GenerationRequest):
            self.requests.append(model_request)
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    provider = BlockingProvider()
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        retry_policy=RetryPolicy(max_attempts=1, sleeper=no_sleep),
    )

    with pytest.raises(ModelTimeoutError):
        await gateway.generate(request().model_copy(update={"timeout_seconds": 0.001}))
    assert gateway.admission.active[Lane.INTERACTIVE] == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_recovers_and_limits_half_open_probe() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        provider="fake",
        failure_threshold=2,
        open_duration_seconds=10,
        clock=lambda: now[0],
    )

    for _ in range(2):
        permit = await breaker.acquire()
        await breaker.failure(permit)
    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.acquire()

    now[0] = 10.0
    probe = await breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN
    with pytest.raises(CircuitOpenError):
        await breaker.acquire()
    await breaker.success(probe)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


def test_cache_key_is_digest_only_and_sensitive_to_parameters() -> None:
    first = cache_key(request(prompt="one"), provider="fake", model_id="model")
    second = cache_key(request(prompt="two"), provider="fake", model_id="model")
    assert first.startswith("aaa:model:v1:")
    assert "one" not in first
    assert "two" not in second
    assert first != second
    assert first == cache_key(request(prompt="one"), provider="fake", model_id="model")
    assert first != cache_key(request(prompt="one"), provider="other", model_id="model")
    assert first != cache_key(request(prompt="one"), provider="fake", model_id="other")


def test_structured_cache_key_changes_with_schema() -> None:
    base = request(prompt="one")
    first = cache_key(base, provider="fake", model_id="model", schema={"type": "object"})
    second = cache_key(
        base,
        provider="fake",
        model_id="model",
        schema={"type": "object", "required": ["answer"]},
    )
    assert first != second


@pytest.mark.asyncio
async def test_cache_ttl_expires_deterministically() -> None:
    now = [0.0]
    cache = InMemoryCache(clock=lambda: now[0])
    await cache.set("key", "value", ttl_seconds=5)
    assert await cache.get("key") == "value"
    now[0] = 5.0
    assert await cache.get("key") is None


@pytest.mark.asyncio
async def test_gateway_cache_hit_skips_provider_and_failed_response_is_not_cached() -> None:
    provider = FakeProvider(response_text="stable")
    telemetry = InMemoryTelemetry()
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        config=GatewayConfig(cache_enabled=True, cache_ttl_seconds=60),
        cache=InMemoryCache(),
        telemetry=telemetry,
        retry_policy=RetryPolicy(max_attempts=1, sleeper=no_sleep),
    )

    first = await gateway.generate(request(cacheable=True))
    second = await gateway.generate(request(cacheable=True))
    assert first.text == second.text == "stable"
    assert len(provider.requests) == 1
    assert telemetry.events[-1].cache_status == "hit"

    failing = FakeProvider(
        error_sequences={"plain": [ModelProviderError(provider="fake", retryable=False)]}
    )
    failing_gateway = ModelGateway(
        {"fake": failing},
        default_provider="fake",
        config=GatewayConfig(cache_enabled=True),
        retry_policy=RetryPolicy(max_attempts=1, sleeper=no_sleep),
    )
    with pytest.raises(ModelProviderError):
        await failing_gateway.generate(request(cacheable=True))
    assert len(failing.requests) == 1


@pytest.mark.asyncio
async def test_non_cacheable_requests_always_call_provider() -> None:
    provider = FakeProvider(response_text="stable")
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        config=GatewayConfig(cache_enabled=True),
    )

    await gateway.generate(request(cacheable=False))
    await gateway.generate(request(cacheable=False))

    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_cache_backend_failure_fails_open_and_telemetry_has_no_content() -> None:
    class BrokenCache:
        async def get(self, key: str) -> None:
            raise RuntimeError(key)

        async def set(self, key: str, value: str, *, ttl_seconds: float) -> None:
            raise RuntimeError(key)

        async def delete(self, key: str) -> None:
            raise RuntimeError(key)

    telemetry = InMemoryTelemetry()
    gateway = ModelGateway(
        {"fake": FakeProvider(response_text="safe")},
        default_provider="fake",
        config=GatewayConfig(cache_enabled=True),
        cache=BrokenCache(),  # type: ignore[arg-type]
        telemetry=telemetry,
    )

    response = await gateway.generate(request(cacheable=True, prompt="student secret"))

    assert response.text == "safe"
    event = telemetry.events[-1]
    assert event.success is True
    assert "student secret" not in event.model_dump_json()
    assert "prompt" not in event.model_dump_json()


@pytest.mark.asyncio
async def test_streaming_releases_capacity_and_emits_telemetry_without_cache() -> None:
    provider = FakeProvider(stream_chunks=("a", "b"))
    telemetry = InMemoryTelemetry()
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        config=GatewayConfig(cache_enabled=True),
        telemetry=telemetry,
    )

    chunks = [chunk async for chunk in gateway.stream(request(cacheable=True))]

    assert "".join(chunk.text for chunk in chunks) == "ab"
    assert gateway.admission.active[Lane.INTERACTIVE] == 0
    assert telemetry.events[-1].cache_status == "bypassed"


def test_telemetry_sink_model_is_content_free() -> None:
    event = GatewayTelemetryEvent(
        task="plain",
        lane=Lane.INTERACTIVE,
        provider="fake",
        model_id="model",
        success=True,
        latency_ms=1.0,
        retry_count=0,
        cache_status="bypassed",
        circuit_state=CircuitState.CLOSED,
        circuit_result="provider_success",
    )
    assert "prompt" not in event.model_dump_json()
    assert "output" not in event.model_dump_json()
