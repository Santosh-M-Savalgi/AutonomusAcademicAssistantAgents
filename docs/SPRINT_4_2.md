# Phase 4.2: Model Gateway and provider boundary

Phase 4.2 adds the first provider-neutral model boundary without changing
application, planner, mastery, persistence, or database behavior.

## Boundary

Application code depends on `packages.model_client` contracts and protocols.
The internal `apps.model_gateway` package owns provider selection and the only
direct llama-server HTTP implementation:

```text
application -> packages.model_client contracts/protocols -> apps.model_gateway
                                                        -> provider
                                             FakeProvider / LlamaCppProvider
                                                               |
                                                               v
                                                        llama-server
```

`FakeProvider` is deterministic, in-memory, and the default for `AAA_PROFILE=mock`.
`LlamaCppProvider` translates the OpenAI-compatible `/v1/chat/completions`
endpoint into provider-neutral responses and streaming chunks. It never starts
llama-server; the Phase 4.1 runtime command layer remains responsible for that.

Every response carries `ModelMetadata` with provider, model, llama.cpp release,
commit, artifact filename, quantization, and optional SHA-256 provenance.
Transport failures, invalid responses, and timeouts are normalized into typed
model-client errors before they cross the gateway boundary.

## Configuration

`MODEL_PROVIDER` accepts:

| Value | Selection |
|---|---|
| `auto` | `FakeProvider` for `mock`; `LlamaCppProvider` for `cpu`/`gpu` |
| `fake` | deterministic provider for any profile |
| `llama_cpp` | host-native llama-server provider |

The default `MODEL_PROVIDER=auto` plus `AAA_PROFILE=mock` makes normal tests and
development independent of a running model. Tests inject `FakeProvider` or a
mocked `httpx` transport; pytest never calls a real llama-server.

## Structured generation

`StructuredGenerationRequest` carries a provider-neutral JSON-schema/format
specification. Phase 4.2 translates that specification to the llama-server
OpenAI-compatible `response_format` field and parses JSON into
`StructuredGenerationResponse`. Full schema support testing, semantic
revalidation, retry policy, and application-specific output models are deferred
to Phase 4.3.

## Deferred work

The gateway is intentionally a small selection/delegation boundary in this
phase. The following remain later work:

- FastAPI gateway routes/service deployment wiring
- global interactive/prefetch/batch priority queues and admission limits
- retries with jitter, circuit breakers, Redis response caching, and telemetry
- TaskSpec registry and routing policies
- cloud providers or fallback
- embeddings and retrieval integration
- complete structured-output validation and benchmark/eval harnesses

Ollama is not part of the AAA runtime architecture. The real local provider is
host-native llama.cpp `llama-server` behind the gateway boundary.
