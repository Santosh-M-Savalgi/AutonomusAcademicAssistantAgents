# Sprint 4.5 — Evaluation and Benchmark Scaffold

## Scope

Phase 4.5 adds an isolated evaluation package under `packages/evalkit`. It
defines reproducible benchmark inputs, pure metrics, closed-fail gates, a
`ModelGateway` adapter, deterministic reports, and an embedding comparison
seam. It does not run a production benchmark and does not make the Phase 4.6
go/no-go decision.

## Dataset contracts

Every example carries a `DatasetIdentity` (`dataset_id` and semantic `version`)
and a stable `example_id`. The current typed example contracts cover:

- syllabus topic extraction (`SyllabusExample`);
- question tagging (`QuestionTagExample`);
- rubric grading labels (`GradingExample`);
- lesson grounding source IDs (`GroundingExample`); and
- retrieval candidates and relevant document IDs (`RetrievalExample`).

Examples also carry short provenance and metadata maps. Reports contain dataset
identity, evaluation-code version, configuration fingerprint, timestamp,
random seed when applicable, sample counts, failure counts, model provenance,
latency, throughput, metrics, and sanitized error categories. Raw prompts and
raw model outputs are not included in reports.

Canonical JSON uses sorted keys and compact separators. Configuration
fingerprints hash only configuration material, making report identity stable
without hashing prompt content.

## Metrics and gates

`packages/evalkit/metrics.py` contains provider-independent functions for:

- set precision, recall, and F1;
- syllabus and question-tag aggregate metrics;
- exact agreement and Cohen’s kappa;
- grounding pass rate;
- Recall@k with deterministic duplicate handling;
- p50/p95/p99 latency;
- prompt/generation throughput; and
- structured-output first-attempt validity, retry recovery, and final validity.

Metric functions do not fabricate empty results. Missing denominators return
`None`, and `evaluate_gates` treats missing or non-finite values as unavailable
and failed closed. The Phase 4.6 floor definitions are represented as data for
later use; this sprint does not evaluate a release decision.

## Gateway runner

`GatewayTaskAdapter` accepts a provider-neutral `ModelGatewayProtocol` and
builds either `GenerationRequest` or `StructuredGenerationRequest`. It never
calls llama-server or a concrete provider directly. `BenchmarkRunner` executes
examples serially for deterministic tests, collects sanitized prediction
metadata, and delegates task-specific scoring to pure evaluator functions.

The adapter supports TaskSpec-backed structured generation through the existing
gateway resolution and validation path. It records first-attempt and retry
recovery flags when structured validation information is available.

## Embedding comparison

The `Embedder` protocol is a small local interface with a CPU-only
`EmbedderConfig`. The locked baseline identity is
`BAAI/bge-small-en-v1.5` with dimension `384`. `FakeEmbedder` accepts explicit
fixture vectors and uses a stable digest fallback; it never downloads or loads
a model. `evaluate_embedder` reports Recall@1, Recall@5, and latency, while
`compare_embedders` computes the challenger Recall@5 delta against the
configured `0.03` criterion. No challenger improvement is claimed by this
scaffold.

## Fixtures and verification

`packages/evalkit/fixtures.py` contains small synthetic, non-production fixtures
for each evaluation domain. Focused tests use `FakeProvider`, `FakeEmbedder`,
and a fake-compatible `ModelGateway`; they make no network calls and do not
require PostgreSQL, Redis, MinIO, a vector database, or model artifacts.

No project dependency was added for Phase 4.5.
