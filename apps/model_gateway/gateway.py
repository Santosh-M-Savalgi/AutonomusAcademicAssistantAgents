"""Resilient in-process ModelGateway for Phase 4.4.

The gateway owns admission, retries, circuit state, cache policy, and
content-free telemetry. TaskSpec resolution and structured validation remain
the Phase 4.3 responsibilities and are reused here.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

from apps.model_gateway.cache import (
    CacheBackend,
    CachePolicy,
    InMemoryCache,
    cache_key,
)
from apps.model_gateway.config import GatewayConfig
from apps.model_gateway.telemetry import (
    GatewayTelemetryEvent,
    InMemoryTelemetry,
    NullTelemetrySink,
    TelemetrySink,
    record_best_effort,
)
from packages.model_client.contracts import (
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    UsageStats,
)
from packages.model_client.errors import (
    ModelClientError,
    ModelProviderError,
    ModelTimeoutError,
    StructuredOutputValidationError,
)
from packages.model_client.policies import (
    CircuitBreaker,
    CircuitPermit,
    CircuitState,
    PriorityAdmission,
    RetryPolicy,
)
from packages.model_client.protocols import ModelProvider
from packages.model_client.schema import (
    StructuredSchemaError,
    generate_json_schema,
    generate_question_tag_generation_schema,
    generate_subject_neutral_question_tag_generation_schema,
)
from packages.model_client.tasks import (
    QuestionTagResult,
    SubjectNeutralQuestionTagResult,
    default_task_registry,
)
from packages.model_client.taskspec import TaskSpec, TaskSpecError, TaskSpecRegistry
from packages.model_client.validation import (
    ValidationDiagnosticObserver,
    validate_structured_response,
)

Clock = Callable[[], float]


class ModelGateway:
    """Select providers and apply bounded local resilience policies."""

    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        *,
        default_provider: str,
        task_registry: TaskSpecRegistry | None = None,
        config: GatewayConfig | None = None,
        admission: PriorityAdmission | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breakers: Mapping[str, CircuitBreaker] | None = None,
        cache: CacheBackend | None = None,
        telemetry: TelemetrySink | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ModelGateway requires at least one provider")
        if default_provider not in providers:
            raise ValueError(f"default provider is not configured: {default_provider}")
        self._providers = dict(providers)
        self._default_provider = default_provider
        self._task_registry = task_registry or default_task_registry()
        self._config = config or GatewayConfig()
        self._admission = admission or PriorityAdmission(self._config.capacities())
        self._retry_policy = retry_policy or RetryPolicy(
            max_attempts=self._config.retry_max_attempts,
            base_delay_seconds=self._config.retry_base_delay_seconds,
            max_delay_seconds=self._config.retry_max_delay_seconds,
            jitter_seconds=self._config.retry_jitter_seconds,
        )
        self._clock = clock or time.monotonic
        self._circuits = dict(circuit_breakers or {})
        for provider_name in self._providers:
            self._circuits.setdefault(
                provider_name,
                CircuitBreaker(
                    provider=provider_name,
                    failure_threshold=self._config.circuit_failure_threshold,
                    open_duration_seconds=self._config.circuit_open_duration_seconds,
                    half_open_probe_capacity=self._config.circuit_half_open_probe_capacity,
                    clock=self._clock,
                ),
            )
        self._cache_policy = CachePolicy(
            enabled=self._config.cache_enabled,
            ttl_seconds=self._config.cache_ttl_seconds,
        )
        self._cache = cache or InMemoryCache(clock=self._clock)
        if telemetry is not None:
            self._telemetry = telemetry
        elif self._config.telemetry_enabled:
            self._telemetry = InMemoryTelemetry()
        else:
            self._telemetry = NullTelemetrySink()

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    @property
    def telemetry(self) -> TelemetrySink:
        """Expose the configured sink for process integration and tests."""

        return self._telemetry

    @property
    def admission(self) -> PriorityAdmission:
        return self._admission

    @property
    def circuits(self) -> Mapping[str, CircuitBreaker]:
        return self._circuits

    def _provider(self, name: str | None) -> tuple[str, ModelProvider]:
        selected = name or self._default_provider
        try:
            return selected, self._providers[selected]
        except KeyError as exc:
            raise ModelProviderError(
                f"Configured model provider is unavailable: {selected}",
                provider=selected,
                retryable=False,
            ) from exc

    @staticmethod
    def _normalize_error(error: BaseException, provider: str) -> ModelClientError:
        if isinstance(error, ModelClientError):
            if error.provider is None:
                error.provider = provider
            return error
        if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return ModelTimeoutError(provider=provider)
        return ModelProviderError(provider=provider, retryable=False)

    @staticmethod
    def _task_version(request: GenerationRequest) -> str | None:
        if isinstance(request, StructuredGenerationRequest):
            return request.task_version
        return request.metadata.get("task_version")

    def _timeout(self, request: GenerationRequest) -> float:
        return request.timeout_seconds or self._config.default_timeout_seconds

    async def _emit(
        self,
        request: GenerationRequest,
        *,
        provider: str,
        model_id: str,
        success: bool,
        error_category: str | None,
        latency_ms: float,
        retry_count: int,
        cache_status: str,
        circuit_state: CircuitState,
        circuit_result: str,
        usage: UsageStats | None = None,
    ) -> None:
        await record_best_effort(
            self._telemetry,
            GatewayTelemetryEvent(
                correlation_id=request.correlation_id,
                task=request.task,
                task_version=self._task_version(request),
                lane=request.lane,
                provider=provider,
                model_id=model_id,
                success=success,
                error_category=error_category,
                latency_ms=max(0.0, latency_ms),
                retry_count=retry_count,
                cache_status=cache_status,
                circuit_state=circuit_state,
                circuit_result=circuit_result,
                usage=usage,
            ),
        )

    async def _cache_read(
        self,
        request: GenerationRequest,
        *,
        provider: str,
        model_id: str,
        task_version: str | None = None,
        schema: Mapping[str, Any] | None = None,
        response_type: type[GenerationResponse] | type[StructuredGenerationResponse],
    ) -> tuple[str, GenerationResponse | StructuredGenerationResponse | None]:
        if not (self._cache_policy.enabled and request.cacheable):
            return "bypassed", None
        key = cache_key(
            request,
            provider=provider,
            model_id=model_id,
            task_version=task_version,
            schema=schema,
        )
        try:
            value = await self._cache.get(key)
            if value is None:
                return "miss", None
            return "hit", response_type.model_validate_json(value)
        except Exception:
            with contextlib.suppress(Exception):
                await self._cache.delete(key)
            return "error", None

    async def _cache_write(
        self,
        request: GenerationRequest,
        response: GenerationResponse | StructuredGenerationResponse,
        *,
        provider: str,
        model_id: str,
        task_version: str | None = None,
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        if not (self._cache_policy.enabled and request.cacheable):
            return "bypassed"
        key = cache_key(
            request,
            provider=provider,
            model_id=model_id,
            task_version=task_version,
            schema=schema,
        )
        try:
            await self._cache.set(
                key,
                response.model_dump_json(),
                ttl_seconds=self._cache_policy.ttl_seconds,
            )
            return "stored"
        except Exception:
            return "error"

    async def _invoke_with_resilience(
        self,
        request: GenerationRequest,
        provider_name: str,
        selected: ModelProvider,
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[Any, int, CircuitState]:
        circuit = self._circuits[provider_name]
        retries = 0
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            permit: CircuitPermit | None = None
            try:
                permit = await circuit.acquire()
                async with asyncio.timeout(self._timeout(request)):
                    async with self._admission.slot(request.lane):
                        result = await operation()
                await circuit.success(permit)
                return result, retries, circuit.state
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                if permit is not None:
                    await circuit.cancel(permit)
                raise
            except BaseException as exc:
                error = self._normalize_error(exc, provider_name)
                if permit is not None:
                    await circuit.failure(permit)
                if not error.retryable or attempt >= self._retry_policy.max_attempts:
                    raise error from exc
                retries += 1
                await self._retry_policy.sleeper(
                    self._retry_policy.delay_for_retry(retries)
                )
        raise AssertionError("retry loop did not return or raise")

    async def generate(
        self, request: GenerationRequest, *, provider: str | None = None
    ) -> GenerationResponse:
        provider_name, selected = self._provider(provider)
        model_id = request.model_id
        started = self._clock()
        cache_status, cached = await self._cache_read(
            request,
            provider=provider_name,
            model_id=model_id,
            response_type=GenerationResponse,
        )
        if isinstance(cached, GenerationResponse):
            await self._emit(
                request,
                provider=provider_name,
                model_id=model_id,
                success=True,
                error_category=None,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=0,
                cache_status="hit",
                circuit_state=self._circuits[provider_name].state,
                circuit_result="cache_hit",
                usage=cached.usage,
            )
            return cached
        retries = 0
        try:
            response, retries, state = await self._invoke_with_resilience(
                request, provider_name, selected, lambda: selected.generate(request)
            )
            assert isinstance(response, GenerationResponse)
            await self._cache_write(
                request, response, provider=provider_name, model_id=model_id
            )
            await self._emit(
                request,
                provider=provider_name,
                model_id=response.model_id,
                success=True,
                error_category=None,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=retries,
                cache_status=cache_status,
                circuit_state=state,
                circuit_result="provider_success",
                usage=response.usage,
            )
            return response
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException as exc:
            error = self._normalize_error(exc, provider_name)
            await self._emit(
                request,
                provider=provider_name,
                model_id=model_id,
                success=False,
                error_category=error.code,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=retries,
                cache_status=cache_status,
                circuit_state=self._circuits[provider_name].state,
                circuit_result="provider_failure",
            )
            raise error from exc

    async def _stream_with_resilience(
        self, request: GenerationRequest, selected: ModelProvider, provider_name: str
    ) -> AsyncIterator[GenerationChunk]:
        started = self._clock()
        circuit = self._circuits[provider_name]
        permit: CircuitPermit | None = None
        iterator: AsyncIterator[GenerationChunk] | None = None
        try:
            permit = await circuit.acquire()
            async with self._admission.slot(request.lane):
                iterator = selected.stream(request)
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            iterator.__anext__(), timeout=self._timeout(request)
                        )
                    except StopAsyncIteration:
                        break
                    yield chunk
            await circuit.success(permit)
            await self._emit(
                request,
                provider=provider_name,
                model_id=request.model_id,
                success=True,
                error_category=None,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=0,
                cache_status="bypassed",
                circuit_state=circuit.state,
                circuit_result="stream_success",
            )
        except (KeyboardInterrupt, SystemExit):
            if permit is not None:
                await circuit.cancel(permit)
            raise
        except asyncio.CancelledError:
            if permit is not None:
                await circuit.cancel(permit)
            raise
        except BaseException as exc:
            error = self._normalize_error(exc, provider_name)
            if permit is not None:
                await circuit.failure(permit)
            await self._emit(
                request,
                provider=provider_name,
                model_id=request.model_id,
                success=False,
                error_category=error.code,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=0,
                cache_status="bypassed",
                circuit_state=circuit.state,
                circuit_result="stream_failure",
            )
            raise error from exc
        finally:
            if iterator is not None:
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    await close()

    def stream(
        self, request: GenerationRequest, *, provider: str | None = None
    ) -> AsyncIterator[GenerationChunk]:
        provider_name, selected = self._provider(provider)
        return self._stream_with_resilience(request, selected, provider_name)

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        *,
        provider: str | None = None,
        task_spec: TaskSpec | None = None,
        validation_observer: ValidationDiagnosticObserver | None = None,
    ) -> StructuredGenerationResponse:
        provider_name, selected = self._provider(provider)
        started = self._clock()
        try:
            spec = task_spec or self._task_registry.resolve(request.task)
            if spec.output_mode != "structured" or spec.output_model is None:
                raise TaskSpecError(f"task does not define structured output: {request.task}")
            if request.task_version is not None and request.task_version != spec.version:
                raise TaskSpecError(
                    f"task version mismatch for {request.task}: "
                    f"expected {spec.version}, received {request.task_version}"
                )
            if (
                spec.name == "question_tag"
                and spec.version == "question-tag-v2"
                and spec.output_model is QuestionTagResult
            ):
                schema = generate_question_tag_generation_schema()
            elif (
                spec.name == "question_tag_v3"
                and spec.version == "question-tag-v3"
                and spec.output_model is SubjectNeutralQuestionTagResult
            ):
                schema = generate_subject_neutral_question_tag_generation_schema()
            else:
                schema = generate_json_schema(spec.output_model)
            structured_request = request.model_copy(
                update={
                    "schema_spec": schema,
                    "task_version": spec.version,
                    "model_id": request.model_id or spec.generation.model_id,
                    "temperature": request.temperature
                    if request.temperature is not None
                    else spec.generation.temperature,
                    "max_tokens": request.max_tokens
                    if request.max_tokens is not None
                    else spec.generation.max_tokens,
                    "timeout_seconds": request.timeout_seconds
                    if request.timeout_seconds is not None
                    else spec.generation.timeout_seconds,
                }
            )
            model_id = structured_request.model_id
            cache_status, cached = await self._cache_read(
                structured_request,
                provider=provider_name,
                model_id=model_id,
                task_version=spec.version,
                schema=schema,
                response_type=StructuredGenerationResponse,
            )
            if isinstance(cached, StructuredGenerationResponse):
                try:
                    result = validate_structured_response(
                        cached, spec, attempts=1, task_id=request.task
                    )
                except StructuredOutputValidationError:
                    cache_status = "error"
                else:
                    await self._emit(
                        request,
                        provider=provider_name,
                        model_id=model_id,
                        success=True,
                        error_category=None,
                        latency_ms=(self._clock() - started) * 1000,
                        retry_count=0,
                        cache_status="hit",
                        circuit_state=self._circuits[provider_name].state,
                        circuit_result="cache_hit",
                        usage=result.usage,
                    )
                    return result
            failures: list[str] = []
            total_retries = 0
            for validation_attempt in range(1, spec.validation.max_attempts + 1):
                try:
                    raw, retries, state = await self._invoke_with_resilience(
                        structured_request,
                        provider_name,
                        selected,
                        lambda: selected.generate_structured(structured_request),
                    )
                    total_retries += retries
                    result = validate_structured_response(
                        raw,
                        spec,
                        attempts=validation_attempt,
                        task_id=request.task,
                        diagnostic_observer=validation_observer,
                    )
                    await self._cache_write(
                        structured_request,
                        result,
                        provider=provider_name,
                        model_id=model_id,
                        task_version=spec.version,
                        schema=schema,
                    )
                    await self._emit(
                        request,
                        provider=provider_name,
                        model_id=model_id,
                        success=True,
                        error_category=None,
                        latency_ms=(self._clock() - started) * 1000,
                        retry_count=total_retries,
                        cache_status=cache_status,
                        circuit_state=state,
                        circuit_result="provider_success",
                        usage=result.usage,
                    )
                    return result
                except StructuredOutputValidationError as exc:
                    failures.extend(error for error in exc.errors if error not in failures)
                    if validation_attempt == spec.validation.max_attempts:
                        raise StructuredOutputValidationError(
                            task=request.task,
                            attempts=validation_attempt,
                            errors=failures,
                            provider=provider_name,
                        ) from exc
            raise AssertionError("structured validation loop did not return or raise")
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except (TaskSpecError, StructuredSchemaError):
            raise
        except BaseException as exc:
            error = self._normalize_error(exc, provider_name)
            await self._emit(
                request,
                provider=provider_name,
                model_id=request.model_id,
                success=False,
                error_category=error.code,
                latency_ms=(self._clock() - started) * 1000,
                retry_count=0,
                cache_status="miss",
                circuit_state=self._circuits[provider_name].state,
                circuit_result="provider_failure",
            )
            raise error from exc
