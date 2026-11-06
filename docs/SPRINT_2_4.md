# Sprint 2.4: Curriculum draft generation

## Objective and boundaries

AAA now runs the pipeline:

`uploaded syllabus -> page-aware extraction artifact -> curriculum_draft job -> validated DRAFT artifact`

The generated object is explicitly a draft. It is not approved, confirmed, edited,
converted into a knowledge graph, embedded, or used for planning. No OCR, real model
provider, paid API, embeddings, frontend, SSE, mastery or assessment work was added.

Feature admission: the draft consumes only the persisted extraction artifact and
document/version metadata; it produces a durable curriculum draft artifact and no
student-learning evidence; the worker/persistence layer owns execution and MinIO
owns immutable artifact bytes; it does not change a graph or plan; deterministic
unit tests, live PostgreSQL/MinIO tests, checkpoint/retry tests, authenticated API
tests and the container smoke test observe it. ADR 0021 records the checkpointed
provider boundary.

## Files created

- `packages/domain/curriculum.py`: draft, provider-output, provenance and job contracts;
  stable IDs, canonical serialization and hierarchy validation.
- `packages/curriculum/drafts.py`, `packages/curriculum/config.py`: pure request
  partitioning, provider-output validation, draft assembly and bounds.
- `packages/model_client/curriculum.py`: vendor-neutral `CurriculumProvider`, typed
  `ProviderError`, deterministic `FakeProvider`.
- `packages/agents/curriculum.py`: bounded LangGraph per-root generation graph.
- `packages/persistence/artifacts.py`, `drafts.py`, `checkpoints.py`,
  `worker_storage.py`: immutable JSON artifacts, trusted draft/extraction metadata,
  PostgreSQL checkpoint ownership and bounded SDK calls.
- `apps/worker/draft.py`: durable `curriculum_draft` handler.
- `apps/api/curriculum.py`: authenticated draft enqueue/status/read API.
- `alembic/versions/0003_curriculum_checkpoints.py`: isolated checkpoint schema.
- `tests/unit/test_curriculum_drafts.py`, `tests/integration/test_curriculum_draft.py`.
- `docs/decisions/0021-curriculum-draft-provider-and-checkpoints.md`, this report.

## Files modified

- `apps/worker/syllabus.py`, `apps/worker/__main__.py`: automatic child-job enqueue
  after durable extraction and production registry integration.
- `apps/api/main.py`: curriculum router.
- `packages/domain/enums.py`, `packages/domain/jobs.py`: draft job type and safe errors.
- `packages/persistence/extractions.py`, `packages/persistence/object_storage.py`:
  trusted extraction loads and bounded storage support.
- `pyproject.toml`, `uv.lock`: LangGraph 1.2.12, langgraph-checkpoint-postgres 3.1.2,
  and psycopg[binary] 3.3.3.
- `.env.example`, `docker-compose.yml`, `docs/STACK.md`: draft bounds, dependency and
  runtime documentation.
- `tests/integration/test_migrations.py`, existing extraction/registry tests.

## Provider boundary and FakeProvider

`CurriculumProvider.generate(GenerationInput) -> bytes` is the only provider contract.
The provider returns untrusted UTF-8 JSON; it has no persistence or domain side effects.
Provider versions are recorded in the draft `VersionStamp` with model, adapter,
prompt and policy fields. `ProviderError.retryable` maps provider outages to the
existing worker retry policy.

`FakeProvider` is deterministic and offline. For every extracted root, it inspects
leaf sections and emits one bounded generated `TOPIC` or `SUBTOPIC` with the exact
source node range. It does not call a model, access the network, or use randomness.
The mock runtime profile injects this provider. Non-mock production configurations
without a provider are rejected with `PROVIDER_NOT_CONFIGURED`; no real provider was
silently substituted.

## Processing flow and checkpoints

After `syllabus_ingestion` writes the extraction artifact, it inserts a deterministic
`curriculum_draft` child job with `parent_job_id`, source document/version metadata,
and an idempotency key derived from the extraction job and artifact reference. The
insert is conflict-safe and repeated extraction attempts do not create duplicate
logical draft jobs. API `POST /api/v3/courses/{course_id}/curriculum/drafts` can
idempotently request the same child for a completed extraction.

The handler resolves the extraction job through PostgreSQL, verifies that it is
`SUCCEEDED`, validates course/document/version identity, and accepts only the exact
server-generated MinIO extraction namespace. It loads and validates the extraction
schema/checksum before generation. One LangGraph node call is made per extracted root;
each call is bounded by `DRAFT_UNIT_OUTPUT_MAX_BYTES`. The graph uses
`AsyncPostgresSaver` in the `curriculum_checkpoints` schema and an attempt-specific
thread. On retry, checkpointed JSON is independently validated before a prefix is
resumed. The worker's existing lease, heartbeat and attempt fence remains the only
authority for final job completion.

Alembic revision `0003_curriculum_checkpoints` adds only the checkpoint schema and
tables required by langgraph-checkpoint-postgres 3.1.2. It is additive and tested by
the existing upgrade/downgrade integration test. The worker never runs migrations.

## Draft schema and provenance

`CurriculumDraft` contains:

- `schema_version=curriculum-draft-v1`, stable draft UUID and `status=DRAFT`;
- source document/course/version identity and checksum through `DocumentSource`;
- source extraction job ID and trusted extraction artifact reference;
- provider/version metadata;
- ordered `CurriculumElement` records with `EXTRACTED` or `GENERATED` origin;
- element type, title, stable key/UUID, parent, source node, page/line references,
  and deterministic parse confidence;
- preserved unclassified source ranges, warnings and `COMPLETE`/`INCOMPLETE` status.

Extracted elements preserve the structural extraction hierarchy. Generated elements
must reference a real extracted source node and exact source range. Stable IDs use
UUID5 over draft identity, source node and key. Validation rejects duplicate IDs,
unstable IDs, forward/missing parents, rank-inconsistent hierarchy, invalid pages,
missing provenance, malformed provider JSON, omitted extraction elements and modified
extracted titles/types/parents. Canonical JSON uses sorted keys and compact UTF-8
serialization without timestamps or attempt-specific values.

Empty/no-text extraction is a permanent `INSUFFICIENT_EXTRACTION` failure. Low-text,
empty-page and unclassified-content warnings remain visible in otherwise usable
drafts. No source page, title or citation is invented by validation or persistence.

## Persistence and idempotency

Draft bytes are stored in the existing MinIO bucket under a document-version and
draft-ID namespace with the canonical JSON SHA-256 as the final path component.
`jobs.result_ref` is set only after storage succeeds. Existing matching bytes are
reused after bounded checksum validation; conflicting bytes fail rather than overwrite.
A failed completion leaves the job recoverable by the existing reaper and a retry
converges on the same draft artifact. Orphaned bytes are retained after uncertain
completion so a competing valid attempt cannot lose its artifact.

The authenticated API reads only a job referenced by its UUID, checks course
membership, validates the draft namespace/checksum and revalidates it against the
source extraction before returning it. HTTP routes never call a provider or generate
content.

## Worker behavior and errors

The production registry contains `syllabus_ingestion` and `curriculum_draft`; unknown
types still use `UNKNOWN_JOB_TYPE`. Invalid/missing extraction, insufficient source,
invalid provider output and draft bounds are permanent typed failures. Provider,
PostgreSQL, MinIO and checkpoint outages use safe retryable errors. Timeouts are
bounded and retry according to the existing job policy. Lease loss, shutdown and
stale attempts are handled by the unchanged Sprint 2.2 worker fencing behavior.
Logs contain job IDs and status/error codes only; no prompts, PDF text, provider JSON,
credentials or tokens are logged.

## Verification

Executed on 2026-10-03 in `/home/smsav/projects/AAAv3` with host Python 3.13.16 and
container Python 3.12.15:

| Command/check | Actual result |
|---|---|
| `make check` | PASS: Ruff, strict Mypy on 33 package files, 5 import contracts; **171 passed, 59 explicit live-service skips**, 230 collected |
| `make test` | PASS: **171 passed, 59 explicit live-service skips**, 230 collected |
| `make integration` | PASS: **60 passed, zero skips** in 69.62 seconds |
| `uv run --locked --group dev mypy --strict packages apps/worker` | PASS: **42 source files** |
| `docker compose --profile mock config --quiet` | PASS |
| `docker compose --env-file /dev/null -f infra/compose/test.yml --profile worker config --quiet` | PASS |
| Shared worker image build | PASS: `aaa-v3-api` built with LangGraph/checkpoint dependencies |
| Container health/readiness | PASS: `/healthz` and `/readyz` HTTP 200; PostgreSQL, Redis and MinIO ready |
| Container end-to-end workflow | PASS: authenticated upload → extraction → `curriculum_draft` → validated `DRAFT` artifact and authenticated API read |
| Container shutdown/logging | PASS: worker SIGTERM exit 0; extraction/draft success logs contain no PDF text or credentials |
| Git checks | PASS: `git diff --check`; `git diff --cached --exit-code`; no staged changes |

The default-suite live skips were all executed by `make integration`. New Sprint 2.4
coverage is 13 provider/contract unit tests and 4 live draft integration tests. The
live suite also reran existing upload, extraction, migration, readiness, worker
concurrency and recovery coverage. The only warning remains the pre-existing
Starlette use of deprecated `anyio.abc.BlockingPortal`.

The container smoke used disposable project `aaa-v3-draft-smoke-1d8d91f2faea`, a
temporary PostgreSQL database, tmpfs services and random loopback ports. Alembic
revisions through `0003_curriculum_checkpoints` ran only there. Containers and network
were removed and verified absent; no persistent volume was used.

## Known limitations and deferred work

- `FakeProvider` is intentionally a deterministic placeholder; no real LLM provider,
  Model Gateway call, prompt optimization or benchmark gate is implemented.
- Generated titles are minimal source-derived placeholders, not semantic curriculum
  extraction. Sprint 2.5+ can replace the provider while retaining validation.
- No curriculum editing, approval, confirmation, graph construction, prerequisites,
  concepts, embeddings, retrieval, OCR, mastery, planner, SSE or frontend exists.
- Drafts are object artifacts rather than queryable curriculum tables until editing and
  confirmation require transactional domain state.
- Per-root generation is bounded and checkpointed; arbitrary provider partial effects
  remain subject to at-least-once idempotency requirements.
- Checkpoint/artifact retention and garbage collection are deferred.

No deviation from locked architectural decisions was required. ADR 0021 documents the
new provider/checkpoint choice; no further approval is required.

## Git and workspace safety

All work stayed inside `/home/smsav/projects/AAAv3`. `/mnt/c`, `/mnt/d` and the Windows
project were not accessed. `AAA_v3_BUILD_SPEC.md`, `agents.md` and `CLAUDE.md` were
read only. Existing Sprint 2.1–2.3 tracked/untracked work and `__agent__/` were
preserved. Nothing was staged or committed. No reset, clean, stash, revert, history
rewrite, development database migration or Docker-volume deletion was performed.
Only uniquely named disposable integration/smoke containers, networks and databases
were cleaned up; existing development volumes remain.
