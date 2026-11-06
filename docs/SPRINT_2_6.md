# Sprint 2.6: SSE progress and recovery

## Objective

Expose durable, authenticated background-job progress that survives worker
restarts and client disconnects. PostgreSQL remains the source of truth; Redis
only wakes subscribers and is never required for replay correctness.

## Existing extension points

- `Job` and `JobRepository` continue to own status, attempts, leases, fencing,
  retry limits and result references.
- `job_progress_events` is additive metadata attached to the existing `jobs`
  table; no parallel queue or lifecycle was introduced.
- `Worker` emits start, progress, terminal and recovery notifications through
  the existing repository transactions.
- `SyllabusHandler` and `DraftHandler` report bounded meaningful stages.
- Existing LangGraph PostgreSQL checkpointing and attempt-specific threads are
  unchanged.

## Durable event schema

Migration `0005_job_progress_events` adds:

| Field | Meaning |
|---|---|
| `event_id` | Stable UUID for the event |
| `job_id` | Existing durable job foreign key |
| `sequence` | Monotonic per-job replay cursor |
| `type` | Stable event name, such as `job.progress_updated` |
| `payload` | Validated `job-event-v1` JSON contract |
| `attempt` | Worker attempt associated with the event |
| `idempotency_key` | Unique per job for retry-safe writes |
| `created_at` | Event creation timestamp |

`jobs.latest_event_sequence`, `progress_stage`, `progress_percent` and
`progress_message` provide the current reconciliation snapshot. Existing jobs
receive a deterministic `job.created` event during migration.

## Event contracts

The stable event names are:

`job.created`, `job.started`, `job.stage_started`, `job.progress_updated`,
`job.partial_result_available`, `job.retry_scheduled`, `job.recovered`,
`job.failed`, `job.completed`, and `job.cancelled`.

Every payload includes `schema_version: "job-event-v1"`. Stage payloads contain
only a controlled stage name, bounded percentage and optional safe message. Error
payloads use the closed `JobErrorCode` enum. Storage references, document text,
credentials, stack traces and worker IDs are not emitted to clients.

Example event:

```text
id: 7
event: job.progress_updated
data: {"event_id":"...","job_id":"...","sequence":7,"type":"job.progress_updated","payload":{"schema_version":"job-event-v1","stage":"generating_curriculum","progress_percent":75,"message":"Validating generated sections"},"attempt":1,"created_at":"..."}
```

## API contract

### Current snapshot

`GET /api/v3/jobs/{job_id}` requires Bearer authentication and membership in
the course encoded by the existing job payload. It returns status, current
attempt, maximum attempts, latest progress, latest event ID/sequence, result
availability, safe error code and timestamps. It never returns `result_ref`.

### SSE stream

`GET /api/v3/jobs/{job_id}/events` uses the same authentication and membership
requirements. It returns `text/event-stream` frames with `id`, `event` and one
JSON `data` line. Clients send `Last-Event-ID: <sequence>` to resume strictly
after that sequence. Invalid cursors return `400`; future cursors are clamped
to the current durable sequence. Events are replayed in order, then PostgreSQL
is polled again before waiting on a Redis hint, so the replay-to-live transition
cannot lose an event. Keepalive comments are sent while a non-terminal job has
no new events. The stream closes after replaying the event that makes a job
terminal. Disconnects release the current Redis pub/sub object and hold no DB
session open.

## Worker progress and recovery

Claiming a job appends `job.started` in the same transaction as the RUNNING
claim. Handler stage/progress writes require the same job ID, worker ID, attempt,
RUNNING state and unexpired lease as all other fenced writes. A stale worker's
progress returns false and cannot advance the job snapshot. Terminal completion,
retry scheduling, cancellation and lease reaping append events atomically with
their state changes. Reaping emits `job.recovered` followed by
`job.retry_scheduled`; the next claim starts a new fenced attempt. Existing
checkpoint resume and idempotent artifact behavior remain unchanged.

## Limitations

- Event history retention and garbage collection are deferred.
- Event hints share the existing Redis wakeup channel; PostgreSQL polling is the
  required fallback when Redis is unavailable.
- The browser-native `EventSource` API cannot provide the existing Bearer header;
  authenticated fetch-streaming is the supported client approach.
- There is no public cancellation route in this sprint; repository cancellation
  still emits `job.cancelled` for trusted internal callers.

## Verification on 2026-10-03

Final exact command results after all Sprint 2.6 changes:

| Command/check | Result |
|---|---|
| `make test` | **186 passed, 76 skipped**, 1 expected Starlette/AnyIO warning |
| `make check` | Ruff passed; package Mypy passed on 36 files; import contracts 5 kept/0 broken; pytest **186 passed, 76 skipped** |
| `make integration` | **77 passed**, 1 expected Starlette/AnyIO warning |
| `uv run --locked --group dev mypy --strict packages apps/worker` | **Success**, no issues in 45 source files |
| Migration checks | Alembic head `0005_job_progress_events`; live upgrade/repeat/downgrade/re-upgrade passed |
| Compose configuration checks | Mock and worker profiles passed validation |
| Git safety checks | `git diff --check` passed; nothing staged |

The expected Starlette/AnyIO deprecation warning remains. No dependency or
provider changes were made. Sprint 2.7 was not started.
