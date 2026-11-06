# AAA v3 stack

This document records dependencies introduced through Sprint 2.4. Versions are pinned in
`pyproject.toml` and resolved in `uv.lock`. Runtime images are pinned where the upstream
release is stable; no model image or model artifact is introduced in these sprints.

## Sprint 1.1 runtime dependencies

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| Python | 3.12 | Supported runtime | PSF-2.0 |
| FastAPI | 0.115.12 | HTTP application framework | MIT |
| Uvicorn | 0.34.2 | ASGI server | BSD-3-Clause |
| Pydantic | 2.13.5 | Typed validation and domain contracts | MIT |
| pydantic-settings | 2.9.1 | Environment-backed settings | MIT |
| SQLAlchemy | 2.0.40 | Async database engine/session foundation | MIT |
| asyncpg | 0.30.0 | PostgreSQL async driver | Apache-2.0 |
| Alembic | 1.15.2 | Database migration runner | MIT |
| redis-py | 5.2.1 | Async Redis client | MIT |
| MinIO Python SDK | 7.2.15 | S3-compatible object-storage client | Apache-2.0 |
| structlog | 25.2.0 | Structured application logging | MIT |
| HTTPX | 0.28.1 | Test client and HTTP utilities | BSD-3-Clause |
| pypdf | 5.9.0 | Approved PDF parsing, encryption, and page validation | BSD-3-Clause |
| python-multipart | 0.0.20 | FastAPI multipart upload parsing | Apache-2.0 |

## Sprint 2.4 curriculum draft dependencies

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| LangGraph | 1.2.12 | Bounded per-job draft generation graph | MIT |
| langgraph-checkpoint-postgres | 3.1.2 | PostgreSQL checkpoint saver for resumable draft jobs | MIT |
| psycopg[binary] | 3.3.3 | Async PostgreSQL connection used by the checkpoint saver | LGPL-3.0-or-later |

No provider SDK, cloud API, model, embedding library or frontend package was added.
The production `mock` profile uses the local deterministic `FakeProvider`.

## Phase 4.1 local model runtime foundation

The runtime foundation adds no Python or container dependency. It records the
host-native llama.cpp release `v0.6.0` (commit
`8345f333951c661d166b00e6f9362e553768f292`, MIT) as the pinned server tool for
the accepted D-02 model decision. The selected model is Llama 3.2 3B Instruct
GGUF Q4_K_M under the Llama 3.2 Community License; no model weights or digest
are downloaded by the application. The human-verified artifact is recorded in
`models/MODELS.lock` with SHA-256
`c55a83bfb6396799337853ca69918a0b9bbb2917621078c34570bc17d20fd7a1`.
The verified development environment is CUDA Toolkit 13.3 on an NVIDIA RTX
3050 4 GB GPU. See `docs/runbooks/llama.md`.

## Phase 4.2 model gateway foundation

No new dependency was added. Existing **httpx 0.28.1** provides the mocked and
runtime HTTP transport. `packages/model_client` contains provider-neutral
contracts, protocols, normalized errors, and deterministic `FakeProvider`.
`apps/model_gateway` contains the small `ModelGateway` delegation boundary and
the only llama-server HTTP adapter, `LlamaCppProvider`. Ollama and cloud
providers are not dependencies or runtime options. Queueing, retries, circuit
breaking, caching, telemetry, TaskSpec routing, and complete structured-output
validation remain deferred.

## Phase 4.3 structured output foundation

No new dependency was added. Existing Pydantic 2.13.5 generates deterministic
JSON Schema, and the gateway strictly revalidates raw provider JSON against the
TaskSpec output model. The Phase 4.3 provider subset rejects unsupported schema
constructs rather than weakening them. Validation permits at most one retry;
TaskSpec failures, structured validation failures, and provider errors remain
separate typed outcomes.

## Phase 4.4 gateway resilience

No new dependency was added. Existing asyncio, Pydantic, structlog-compatible
application boundaries, and the already-pinned HTTP/runtime stack are sufficient
for process-local priority admission, bounded retry, circuit breaking, the
explicitly opt-in cache interface, and content-free telemetry. Phase 4.4 uses
an in-memory cache backend for deterministic tests; it does not introduce a
second cache technology or Redis deployment wiring. See `docs/SPRINT_4_4.md`.

## Sprint 1.2 authentication dependencies

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| argon2-cffi | 25.1.0 | Argon2id password hashing and verification | MIT |
| PyJWT | 2.10.1 | JWT signing and strict claim validation | MIT |

The JWT signing secret is required from `JWT_SECRET_KEY` before tokens can be issued
or validated. No default signing secret is supplied. This sprint adds no user tables,
login route, registration route, or refresh-token workflow.

## Development tooling

| Dependency | Version | Purpose | License |
|---|---:|---|---|
| pytest | 8.4.2 | Test runner | MIT |
| pytest-asyncio | 0.26.0 | Async test support | Apache-2.0 |
| Hypothesis | 6.144.0 | Property-based testing for deterministic graph algorithms | MPL-2.0 |
| Ruff | 0.16.9 | Linting and import checks | MIT |
| mypy | 1.20.2 | Strict static typing for `packages/` | MIT |
| import-linter | 2.15.0 | Internal package boundary checks | BSD-3-Clause |
| uv | 0.11.15 | Environment and lockfile management | Apache-2.0 |

## Observability foundation

The API uses the existing `structlog` dependency (25.2.0); Sprint 1.3 adds no
observability package. Application and standard-library records are rendered as
JSON with UTC timestamps, log levels, logger names, and request context. The
request middleware creates or safely accepts an `X-Request-ID`, binds it to
structlog context variables, and returns it on successful, rejected, readiness,
and generic server-error responses.

The logging processor redacts credentials, passwords and password hashes, JWT or
Bearer token fields, database DSNs, request/response bodies, and student-answer
fields. Request bodies are not read by the middleware. Health probes report
PostgreSQL, Redis, and MinIO independently through `/readyz`; expected
dependency outages are logged as warnings without exception details, while
unexpected application failures are classified as server errors and return a
generic public response.

OpenTelemetry, Prometheus, distributed tracing, and dashboard infrastructure
remain later-phase work from the build specification. This sprint keeps the
Phase 1 logging and readiness foundation small and dependency-free.

## Test and CI infrastructure

`make test` runs unit tests and the migration wiring test without Docker. Live
dependency checks are marked `live_integration`; `make integration` starts a
fixture-owned disposable Compose stack and runs them:

```bash
make integration
```

The live command requires Docker and uses `infra/compose/test.yml` with a unique
Compose project, random loopback ports, test-only credentials, a per-test
database, and tmpfs-backed service data. It applies Alembic migrations, runs
readiness and client probes, rolls back database writes, removes Redis keys and
MinIO objects, and tears down only those ephemeral resources. CI installs from
the committed lockfile and runs Ruff, strict Mypy for `packages/`, all
import-linter contracts, unit tests, migration tests, and live service
integration tests on Linux for Python 3.12 and 3.13.

The reusable fixtures in `tests/conftest.py` build the production FastAPI app,
HTTP clients, async database sessions, Redis and MinIO owners, JWT identities,
Bearer headers, and authentication dependency overrides. Live service fixtures
are kept in `tests/integration/conftest.py`; the ordinary suite reports an
explicit skip, while `make integration` enables the live fixtures so unit tests
never access external services.

## Audited v2 infrastructure

The selective audit is recorded in
`docs/decisions/0017-phase-1-infrastructure-audit.md`. The v2 ref contains
useful reference implementations, but v3 retains its own typed boundaries and
does not restore v2 routes, orchestration, ChromaDB, cloud providers, metrics,
or OpenTelemetry dependencies.

## Local runtime images

- PostgreSQL + pgvector: `pgvector/pgvector:pg16`
- Redis: `redis:7-alpine`
- MinIO Community Edition (third-party build):
  `ghcr.io/golithus/minio:RELEASE.2025-10-15T17-29-55Z@sha256:8793e960474071520bdb91bb9a6d1793eb229fdbc9dcb7ec75ad836b69bbab40`
  Source: `https://github.com/golithus/minio-builds`; license: AGPL-3.0.
- MinIO HTTP readiness probe: `curlimages/curl:8.16.0@sha256:463eaf6072688fe96ac64fa623fe73e1dbe25d8ad6c34404a669ad3ce1f104b6`
  (dedicated Compose-sidecar probe; it is not part of the MinIO image or API runtime).
- API image: built locally from `infra/docker/api.Dockerfile`

The Compose profiles start PostgreSQL, Redis, MinIO with its HTTP probe, API, and
the independently restartable worker. API and worker use the same application image.
No model weights, datasets, runtime databases, or secrets belong in Git.

## Sprint 2.2 worker

No new dependencies: uses existing SQLAlchemy/asyncpg, redis-py, Pydantic settings,
structlog and Python asyncio. `python -m apps.worker` runs a separate process.
PostgreSQL, Redis and (since Sprint 2.3) the MinIO HTTP probe are Compose startup
dependencies. Redis loss after startup does not stop PostgreSQL polling.
The opt-in `worker` profile in `infra/compose/test.yml` extends the same service
definition with test credentials and disposable PostgreSQL; ordinary integration
tests inject worker instances against fixture-owned services.

| Variable | Default | Meaning |
|---|---:|---|
| `WORKER_ENABLED` | true | Run the worker process; false exits without opening resources |
| `WORKER_CONCURRENCY` | 2 | Independent claim/execution slots per process |
| `WORKER_POLL_SECONDS` | 2 | Maximum idle polling interval without a wake-up |
| `WORKER_LEASE_SECONDS` | 60 | PostgreSQL-clock ownership lease |
| `WORKER_HEARTBEAT_SECONDS` | 15 | Renewal interval, at most one third of lease |
| `WORKER_REAPER_SECONDS` | 15 | Expired lease scan interval, 100 rows per batch |
| `WORKER_RETRY_BASE_SECONDS` | 2 | Exponential retry base |
| `WORKER_RETRY_MAX_SECONDS` | 300 | Retry cap; deterministic, no jitter |
| `WORKER_SHUTDOWN_GRACE_SECONDS` | 30 | Time for in-flight handlers to finish |
| `WORKER_IO_TIMEOUT_SECONDS` | 5 | Bound on each claim/heartbeat/state operation |
| `WORKER_LANES` | `["interactive","prefetch","batch"]` | JSON list of admitted lanes |

Redis channel `aaa:v3:jobs:wakeup` carries only `wake`, never payloads or queue
state. Publication has a 0.5-second bound and failure does not affect committed
uploads. Worker pub/sub reconnection is independent of PostgreSQL polling.

Run `make unit`, `make integration`, `make test`, and `make check` for verification.
The live suite includes subprocess SIGTERM/SIGKILL tests on disposable databases.
Development requires the Sprint 2.4 migrations (`make migrate`) before
jobs can be claimed; the worker never runs migrations automatically. Restart
API and worker independently with `docker compose restart api` / `worker`.
Compose's 45-second stop deadline assumes the default 30-second grace; raise
that deadline if you configure a longer grace period.

**Handler registry:** Sprint 2.3 registers `syllabus_ingestion` for deterministic
PDF extraction. Sprint 2.4 also registers `curriculum_draft`; other types still
fail with `UNKNOWN_JOB_TYPE`. See `docs/SPRINT_2_2.md`, `docs/SPRINT_2_3.md`,
`docs/SPRINT_2_4.md`, and ADRs 0019–0020.

## Sprint 2.3 deterministic extraction

Uses approved **pypdf 5.9.0** (BSD-3-Clause), existing Pydantic/MinIO, and Python's
subprocess/resource/tempfile libraries. The bounded SDK HTTP pool uses urllib3,
already locked as a MinIO dependency. No dependency or schema migration added.
`MAX_UPLOAD_SIZE_BYTES` and `MAX_PDF_PAGES` apply to API validation and worker
extraction; Compose passes the same environment overrides to both processes.

| Variable | Default | Meaning |
|---|---:|---|
| `EXTRACTION_TIMEOUT_SECONDS` | 60 | Wall deadline for DB lookup, download, parse and persistence; CPU seconds also capped |
| `EXTRACTION_MAX_OUTPUT_BYTES` | 4194304 | Bound on canonical JSON artifact and accumulated extracted text |
| `EXTRACTION_MEMORY_MB` | 512 | Linux address-space limit per extraction subprocess |
| `EXTRACTION_MINIMUM_USEFUL_CHARACTERS` | 40 | Non-whitespace character floor for `LOW_TEXT` status |

Each concurrent handler uses one disposable child process. Local MinIO credentials
are inherited through stdin, never command arguments. The child owns anonymous
temporary PDF files in its working directory, with file size capped at the shared
upload limit. Timeout, cancellation or parent death terminates it and the OS closes
descriptors. This runtime requires Linux/WSL (including `prctl` parent-death signaling).
SDK connect/read operations are bounded to at most 10 seconds, with retry decisions
owned by the durable worker.

Outputs are schema-versioned JSON in the existing MinIO bucket, using content-addressed
document-version keys and `minio://bucket/key` job result references. Repeated work
converges on one artifact for identical source and policy. The job becomes successful
only after durable artifact persistence and fenced PostgreSQL completion. Empty/scanned
pages produce `OCR_CANDIDATE` warnings and `NO_TEXT`/`LOW_TEXT` summaries; the structural
artifact is still a successful extraction result. No OCR or LLM curriculum draft is
created. Previously terminal `UNKNOWN_JOB_TYPE` jobs are not automatically resurrected.

## Sprint 2.4 curriculum draft generation

`syllabus_ingestion` inserts one deterministic `curriculum_draft` child job after
the extraction artifact is durable. The stable key is derived from extraction job
ID and artifact reference; duplicate inserts are conflict-safe. The child validates
the exact MinIO namespace/checksum/schema/source identity, then runs a bounded
LangGraph graph with one provider call per extracted root section. Checkpoints use
the isolated `curriculum_checkpoints` schema and attempt-specific threads. Saved
provider JSON is revalidated before resume.

`CurriculumProvider` is vendor-neutral. `FakeProvider` is deterministic and copies
source leaf headings into bounded generated `TOPIC`/`SUBTOPIC` elements with exact
source ranges. The `mock` profile uses it. Every provider result is parsed through
Pydantic, checked for stable UUIDs, source identity, parent hierarchy and exact
source references, then assembled with the extracted hierarchy. Output is always
`status=DRAFT`; it is never approved, confirmed, edited, graphed, embedded or sent
to an external model.

| Variable | Default | Meaning |
|---|---:|---|
| `DRAFT_TIMEOUT_SECONDS` | 30 | Bound for source load, checkpointed generation and persistence |
| `DRAFT_ARTIFACT_MAX_BYTES` | 4194304 | Canonical draft artifact limit |
| `DRAFT_MAX_SECTIONS` | 128 | Maximum extracted root generation requests |
| `DRAFT_UNIT_OUTPUT_MAX_BYTES` | 65536 | Maximum untrusted provider JSON per root |

Draft artifacts use content-addressed versioned MinIO keys and `jobs.result_ref`.
The artifact is stored before fenced job success. Authenticated API routes expose
`POST /api/v3/courses/{course_id}/curriculum/drafts` for idempotent submission of
a completed extraction and `GET /api/v3/curriculum/{draft_id}/draft` for status and
readback. Membership is checked; HTTP never performs generation. Unclassified
content and low-text warnings remain in a draft when useful structure exists.

## Sprint 2.5 curriculum review

No dependency or runtime technology changed. Alembic revision
`0004_curriculum_review` adds only PostgreSQL metadata for review lifecycle pointers
and immutable revision records. Full reviewed curriculum JSON remains in separate
MinIO objects; the Sprint 2.4 generated draft object is never overwritten. Review
status is `DRAFT -> UNDER_REVIEW -> CONFIRMED`, with row locking, expected revision
numbers and idempotent repeated snapshots preventing last-write-wins behavior.
The authenticated API provides begin-review, current revision, revision history,
save, confirm and confirmed-read routes. Confirmation has no downstream side effects.

## Sprint 2.6 durable job progress and SSE

Alembic revision `0005_job_progress_events` adds an append-only PostgreSQL event
history and a per-job `latest_event_sequence` cursor. Job mutations and their
corresponding events are committed in the same transaction. Event payloads use
the closed `job-event-v1` contracts; Redis remains a loss-tolerant wakeup hint,
and PostgreSQL polling is authoritative for replay and recovery.

Authenticated clients reconcile with `GET /api/v3/jobs/{job_id}` and stream
`GET /api/v3/jobs/{job_id}/events` using the existing Bearer authentication and
course membership. The SSE endpoint accepts numeric `Last-Event-ID` values,
replays strictly greater per-job sequences, emits keepalive comments, and closes
after the final terminal event. It exposes result availability and safe error
codes, never storage references or internal exception details. Extraction and
curriculum-draft handlers report bounded source-validation, generation and
persistence stages through the same fenced worker attempt that owns the job.
Lease reaping emits durable recovery/retry events; existing LangGraph checkpoint
threads and retry limits are unchanged.
