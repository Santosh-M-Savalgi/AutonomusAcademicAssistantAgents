# ADR 0019: Fence worker attempts and distinguish shutdown from cancellation

## Status

Accepted for Sprint 2.2; implements D-08 without a new table, broker, or migration.

## Decision

- PostgreSQL claims use `FOR UPDATE SKIP LOCKED` and increment the existing
  `attempts` field. A lease is identified by `(job ID, worker ID, attempt)`.
  Heartbeat/completion additionally require `RUNNING` and an unexpired lease,
  evaluated using PostgreSQL's clock. The attempt fence prevents an old task
  from completing a newer attempt even if the same worker process reclaimed it.
- Lanes are an explicit eligibility filter. Within admitted lanes, ordering is
  priority descending, creation time ascending, then UUID for stable ties.
  This follows the specification's priority-first order without inventing lane
  priority overrides.
- A successful handler result is persisted only while its lease remains valid.
  Unknown job types fail with `UNKNOWN_JOB_TYPE`. No placeholder curriculum
  handler reports success; curriculum processing is still unimplemented.
- Graceful shutdown allows handlers to finish, then interrupts remaining work
  into `RETRYING` (or `FAILED` on exhaustion). Explicit cancellation means
  `CANCELLED`. These are different intentions: a process restart must not lose
  queued work by permanently cancelling it.
- Heartbeat failure or ownership loss stops new claims and cancels the handler.
  Uncertain completion commits are never followed by a contradictory state
  update: uncommitted work stays `RUNNING` until lease recovery.
- Handlers that suppress cancellation cannot be killed individually by asyncio.
  The worker discards late results, stops heartbeats, closes owned resources,
  and exits the process if handler tasks remain. Compose supplies a final
  SIGKILL deadline for a handler blocking the event loop itself.
- Delivery is **at least once**. Fencing prevents stale state writes; it cannot
  make arbitrary external handler effects exactly once. Future handlers must
  make effects idempotent by job ID and honor the cancellation context.
- Redis publishes a constant `wake` only **after** the upload transaction
  commits and outside its storage compensation block. Lost/duplicate messages
  are harmless because each slot polls PostgreSQL independently.

## Consequences

No schema expansion (`locked_at`, error text, or ownership token columns) is
needed. Only enum error codes are persisted; exception strings and payloads
are never logged. `PARTIAL` remains an explicitly resumable, unclaimed state;
automatic partial-result processing and public cancellation/resume APIs are
outside this infrastructure sprint. The production handler registry is empty,
so enabling the worker on existing syllabus jobs will fail those jobs safely
as unsupported rather than process PDFs.
