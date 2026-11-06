# Phase 4.4: Gateway resilience, cache, and telemetry

Phase 4.4 hardens the existing in-process `ModelGateway` without changing the
Phase 4.3 TaskSpec or structured-validation architecture.

## Gateway flow

```text
TaskSpec / request policy
  -> cache lookup when explicitly eligible
  -> priority admission
  -> process-local circuit breaker
  -> bounded provider retry and timeout
  -> provider
  -> Phase 4.3 structured validation when applicable
  -> cache write after successful completion
  -> best-effort content-free telemetry
```

Cache hits return before admission and do not contact the provider. An open
circuit rejects before provider invocation. Cache and telemetry failures fail
open and do not change generation semantics.

## Stage A: lanes and admission

Requests use the typed `Lane` enum:

- `interactive` — highest priority, default capacity 4
- `prefetch` — capacity 2
- `batch` — capacity 1

`PriorityAdmission` uses cancellation-safe permits and a condition-controlled
waiter list. Higher-priority waiters prevent lower-priority admission while
capacity is available for the higher lane. Every provider attempt acquires and
releases a lane permit; cancellation, timeout, provider failure, and streaming
completion release permits.

This is process-local. Distributed scheduling is deferred.

## Stage B: retry and timeout

`RetryPolicy` provides bounded attempts, exponential backoff, a maximum delay,
and bounded additive jitter. Only `ModelClientError.retryable=True` errors are
retried. Permanent provider errors, malformed responses, task errors, circuit
open errors, and structured validation failures are not infrastructure retried.

The Phase 4.3 structured-output retry remains separate: a TaskSpec permits at
most two validation attempts. Each validation attempt can independently use the
bounded infrastructure retry policy, so the combined behavior is finite and
observable rather than an uncontrolled retry loop.

Tests inject a no-op sleeper and deterministic random source; normal tests do
not wait for backoff.

## Stage C: circuit breaker

`CircuitBreaker` is process-local and has `CLOSED`, `OPEN`, and `HALF_OPEN`
states. It supports configurable failure threshold, open duration, and one or
more half-open probes. Open circuits return the typed `MODEL_CIRCUIT_OPEN` error
without contacting the provider. Successful probes close and reset the
breaker; failed probes reopen it. Tests inject a clock.

## Stage D: cache

Caching is disabled by default and requires both:

1. `MODEL_GATEWAY_CACHE_ENABLED=true`; and
2. the individual request setting `cacheable=true`.

The backend is behind the `CacheBackend` interface. Phase 4.4 uses the
dependency-free `InMemoryCache` foundation in unit tests; no second cache
system or database dependency was introduced. A later Redis adapter can
implement the same interface.

Cache keys are SHA-256 digests of canonical request material. They include the
provider, model, task/version, generation parameters, messages/prompt material,
and structured schema, but expose none of the raw prompt or student content.
Failed responses and partial streams are never cached. Cache backend failures
and corrupt entries fail open to provider generation.

## Stage E: telemetry

`GatewayTelemetryEvent` records only operational metadata:

- correlation ID
- task and task version
- lane
- provider and model ID
- success/error category
- latency
- infrastructure retry count
- cache status
- circuit state/result
- token usage when supplied by the provider

Prompts, raw outputs, student content, and cache keys are not included.
`TelemetrySink` failures are swallowed. `InMemoryTelemetry` is provided for
deterministic tests and integration into existing structured logging can be
added without changing generation contracts.

## Streaming

Streaming remains provider-neutral and is never cached. The gateway acquires a
lane permit and circuit lease for the stream, enforces a per-chunk timeout,
closes the provider iterator, releases admission, and emits success/failure
telemetry. Streaming is not retried after iteration begins because partial
output cannot safely be replayed.

## Configuration

The existing Settings system exposes:

| Setting | Default |
|---|---:|
| `MODEL_GATEWAY_RETRY_MAX_ATTEMPTS` | 2 |
| `MODEL_GATEWAY_RETRY_BASE_DELAY_SECONDS` | 0.05 |
| `MODEL_GATEWAY_RETRY_MAX_DELAY_SECONDS` | 1.0 |
| `MODEL_GATEWAY_RETRY_JITTER_SECONDS` | 0.05 |
| `MODEL_GATEWAY_INTERACTIVE_CAPACITY` | 4 |
| `MODEL_GATEWAY_PREFETCH_CAPACITY` | 2 |
| `MODEL_GATEWAY_BATCH_CAPACITY` | 1 |
| `MODEL_GATEWAY_TIMEOUT_SECONDS` | 30.0 |
| `MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD` | 3 |
| `MODEL_GATEWAY_CIRCUIT_OPEN_DURATION_SECONDS` | 30.0 |
| `MODEL_GATEWAY_CACHE_ENABLED` | false |
| `MODEL_GATEWAY_CACHE_TTL_SECONDS` | 60.0 |
| `MODEL_GATEWAY_TELEMETRY_ENABLED` | true |

Lane defaults are currently the specification defaults (4/2/1), represented
by typed policy configuration rather than arbitrary string comparisons.

## Failure behavior and privacy

Timeout, unavailable, provider, malformed response, structured validation,
circuit-open, admission, and cache-backend conditions remain distinguishable.
Cache and telemetry infrastructure are best effort. Provider and policy errors
remain typed model-client errors. No raw prompt/output is sent to telemetry or
exposed in cache keys.

## Deferred

Cloud fallback, distributed scheduling, Redis deployment wiring, priority
queues across replicas, complex quality/cost routing, retrieval, embeddings,
RAG, production lesson/question/grading tasks, agent orchestration, frontend,
database migrations, and fine-tuning remain deferred.
