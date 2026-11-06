# Sprint 2.2: Durable PostgreSQL worker infrastructure

Owned by the worker/persistence layer: consumes committed job metadata and payload,
produces durable status/error/result references. It does not change the curriculum
graph or learning plan and produces no new student mastery evidence. Behavior is
observed through safe structured worker logs and tested below.

## Implementation and files

Created:
- `packages/domain/jobs.py`: detached claim snapshot, error vocabulary, lifecycle and backoff.
- `packages/persistence/jobs.py`: claim, heartbeat, finish/failure, cancel and reaper repository.
- `packages/persistence/job_wakeups.py`: bounded post-commit publisher and reconnecting subscriber.
- `apps/worker/config.py`, `handlers.py`, `runner.py`, `__main__.py`: validated settings,
  typed handlers, concurrent execution lifecycle and signal-aware process entrypoint.
- `tests/unit/test_worker.py`, `tests/integration/test_worker_runtime.py`: policy and real DB tests.
- `tests/__init__.py`, `tests/worker_process.py`: deterministic blocked crash-test subprocess.
- `docs/decisions/0019-worker-lease-ownership.md`, this implementation note.

Modified:
- `apps/api/documents/service.py`: publish a wake-up only after the upload commit.
- `apps/api/logging.py`: reuse safe JSON logging with worker service/job/worker identifiers.
- `apps/worker/__init__.py`: replace scaffold description.
- `.env.example`, `docs/STACK.md`: worker settings, commands and operational behavior.
- `docker-compose.yml`, `infra/compose/test.yml`: independent worker using the application image.
- `tests/conftest.py`: deterministic handler controls and short validated worker settings.
- `tests/integration/test_curriculum_upload.py`: committed upload survives Redis publication failure.

## Schema, claiming and locking

Uses Sprint 2.1 `Job` / `jobs` exactly as implemented by revision
`0002_curriculum_upload`. No migration or schema modification. PostgreSQL remains
the sole job store. Existing idempotency uniqueness and claiming indexes are retained.

Each slot selects one eligible `PENDING`/`RETRYING` row with `run_after` due,
attempts remaining, and lane allowed. `FOR UPDATE SKIP LOCKED`, priority descending,
creation ascending, and UUID tie-breaking allow independent concurrent claims.
`RUNNING`, attempt increment, owner UUID, lease and heartbeat are committed in
the same short transaction. Handlers receive detached metadata/payload and run
outside all database transactions.

## Lease, execution, retries and recovery

Default lease/heartbeat are 60/15 seconds. Heartbeats and handler completions check ID,
owner, attempt, RUNNING and unexpired PostgreSQL-clock lease. A late heartbeat
cannot revive a terminal job, an expired attempt, or another worker's job.

Typed handlers return an opaque artifact reference or raise a controlled failure.
Success -> `SUCCEEDED`; retryable errors -> `RETRYING` until attempts reach the
limit; permanent errors/exhaustion -> `FAILED`; explicit cancellation -> `CANCELLED`.
Unhandled exceptions use `HANDLER_EXCEPTION`; unknown types use `UNKNOWN_JOB_TYPE`.
Only closed-vocabulary error codes are persisted, never exception text.

Backoff is `min(300, 2 * 2**(attempt-1))` seconds by default, without jitter.
The reaper scans every 15 seconds in batches of 100 with row locks and SKIP LOCKED.
Expired RUNNING jobs become RETRYING or FAILED with `LEASE_EXPIRED`, ownership
cleared, and retry scheduling persisted. Concurrent reapers are idempotent;
renewed or locked leases are not overwritten.

## Redis and failure behavior

The upload transaction still commits document/version/event/job together.
Redis publication is outside its transaction/compensation scope. Hints contain
only `wake`. Subscriber disconnect/reconnect never blocks independent polling
(default every 2 seconds). Duplicate messages cannot bypass a PostgreSQL claim.

Heartbeat errors fail closed: cancel execution, stop new claims, stop renewing
and leave uncertain ownership for the reaper. Completion failure never invents
success or writes a contradictory failure after an uncertain commit.

## Shutdown

SIGTERM/SIGINT stops new claims immediately; an already-committing claim is
returned to retry/failure without executing it. In-flight jobs get 30 seconds
to finish while heartbeats continue. On expiry, cancel them and retry/fail with
`WORKER_SHUTDOWN`, ignoring any late handler return. Handlers voluntarily cancelling
on the shutdown event also retry, rather than becoming permanently cancelled.
Explicit user cancellation is terminal and distinct from a process restart.
DB and Redis owners are closed on exit. Uncooperative async handlers are terminated with the process after
cleanup; Compose provides a final 45-second stop deadline for blocking code.
Abrupt process death leaves the committed lease for deterministic recovery.

## Coverage and verification

Unit tests cover lifecycle validation, terminal-state rejection, backoff bounds,
attempt limits, SQL eligibility/order, settings, unique identity, handler outcomes,
unknown types, safe errors, heartbeat loss, uncertain completion, shutdown during
claim, late success suppression and state-free Redis hints.

Live tests exercise concurrent claims, locked-row skipping, lane/priority/due-time
eligibility, attempt increments, outcomes, fencing, renewal, expiry, concurrent
reapers, cancellation, slow-handler heartbeats, an actual PostgreSQL error before
completion commit, Redis loss/missing/duplicate notifications, concurrent handler
slots, graceful shutdown, SIGKILL recovery and CLI startup/SIGTERM shutdown.
Existing upload, migration, resource-isolation, `/healthz` and `/readyz` tests remain.

Final results on 2026-10-03 (Linux Python 3.13.16; container Python 3.12.15):

| Command/check | Result |
|---|---|
| `make check` | PASS: Ruff, strict Mypy on 20 package files, all 5 import contracts; 112 passed / 36 explicit live-service skips |
| `make test` | PASS: 112 passed / 36 explicit live-service skips, 148 collected |
| `make integration` | PASS: 37 passed, zero skips, disposable PostgreSQL/Redis/MinIO |
| `uv run --locked --group dev mypy --strict packages apps/worker` | PASS: 25 source files |
| `docker compose --profile mock config --quiet` | PASS |
| `docker compose --env-file /dev/null -f infra/compose/test.yml --profile worker config --quiet` | PASS |
| `docker compose --env-file /dev/null -f infra/compose/test.yml --profile worker build worker` | PASS: shared `aaa-v3-api` image built |
| Disposable container smoke | PASS: worker startup, SIGTERM exit 0 and structured start/stop logs; API `/healthz` and `/readyz` both HTTP 200 |

Default-test skips explicitly require `make integration`; every skipped live
case was executed successfully there. New coverage comprises 35 worker unit
cases, 26 worker integration cases and one upload/publication regression.
The existing offline migration check runs in both default and integration suites.

Container smoke used unique project `aaa-v3-worker-smoke-56c57e8549c2`, tmpfs
data and random loopback ports. Ran the existing Alembic migrations **only in that
disposable PostgreSQL**, started the Compose worker, and launched the shared image
as an API container on the same isolated network. `/readyz` confirmed PostgreSQL,
Redis and authenticated MinIO access. Worker stopped with exit 0 and no polling
or reaper errors. All smoke containers and the network were removed and absence
verified. No development database migration was run.

Resolved during validation: duplicate pytest module basenames (integration file
renamed `test_worker_runtime.py`), a Redis async timeout typing error, and voluntary
shutdown cancellation incorrectly becoming terminal. The last has unit and live
regression coverage. Remaining test warning is the pre-existing Starlette use of
deprecated `anyio.abc.BlockingPortal`; no dependency changes were made for it.

## Limitations and decisions

Delivery is at least once: future handlers must implement idempotent effects;
fencing only guarantees job ownership/state safety. No curriculum handler is
registered yet. Unsupported types fail, including syllabus jobs if the worker
is enabled; disable the worker to leave those pending for Sprint 2.3. PARTIAL is
reserved for later explicit resumption; no public cancel/resume endpoint is added.
Non-yielding/blocking handlers require process isolation in their future implementation.
Ownership loss stops the worker conservatively; restart it after repairing a database
outage. Another running/restarted worker reaps abandoned attempts. Compose does not
currently add an automatic restart policy.
No PDF extraction, OCR, curriculum parsing, model call, graph construction, SSE,
broker or LangGraph was introduced. No new dependency or locked decision change.
ADR 0019 documents attempt fencing, shutdown/retry semantics and delivery limits;
no architectural decision requires approval.

## Git safety

All work is confined to `/home/smsav/projects/AAAv3`. Existing Sprint 2.1 tracked
and untracked work was preserved; `__agent__/` and ignored source documents were
untouched. No staging, commit, reset, clean, stash, revert, history rewrite or
Windows-project access. No development migration or persistent volume deletion was
performed; smoke and integration cleanup targeted only their uniquely named projects.
Final `git diff --check` and `git diff --cached --exit-code` passed. The index is
empty; development PostgreSQL/Redis/MinIO named volumes still exist. No test or
smoke containers/networks remain.
