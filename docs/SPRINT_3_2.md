# Sprint 3.2: Student identity and transactional learning events

## Scope and status

Sprint 3.2 adds the internal identity registry, versioned learning-event
contracts, caller-owned event persistence and a caller-owned durable job
creation helper. It does not add graph publication, mastery, planner behavior,
student-state APIs or role management.

PostgreSQL remains authoritative. Redis wake-ups and the existing job-progress
event stream remain separate from domain learning events.

## Identity model

`student_identities` maps an external authenticated subject to a stable UUID:

| Field | Meaning |
|---|---|
| `id` | Internal UUID primary key; never used as an authentication credential |
| `provider_namespace` | JWT issuer/audience namespace |
| `external_subject` | Opaque JWT `sub`; never parsed as a UUID |
| `created_at`, `updated_at` | Server timestamps |

The `(provider_namespace, external_subject)` pair is unique. The UUID is
deterministically derived with UUID5 from the namespaced opaque subject, and the
database unique constraint remains authoritative for concurrency safety.
`resolve_student_identity()` uses `INSERT ... ON CONFLICT DO NOTHING` and then
reads the committed row in the caller's session. It never commits internally.

The API authentication layer provides `get_current_student_identity()`. It
first validates the JWT, derives the provider namespace from configured issuer
and audience, and only then resolves the subject. A client-provided student UUID
is not accepted by this dependency.

## Actor, learner and course

The v1 event input carries separate fields for:

- `actor_id`: internal identity of the authenticated actor;
- `actor_subject`: the external subject associated with that actor;
- `learner_id`: affected learner, when applicable;
- `course_id`: course scope, when applicable.

An actor may act for themself. `require_learner_access()` rejects another
learner unless a caller has already performed an explicitly authorized
delegation/role check. Course membership alone does not set that authorization.
This sprint does not introduce a role-management system or instructor routes.

The event repository verifies that `actor_id` and `actor_subject` resolve to the
same persisted identity. Future delegated operations must perform their
authorization check before constructing the event input.

## Event contracts and compatibility

`packages/domain/events.py` defines:

- `LearningEventPayload`, versioned as `learning-payload-v1`;
- `LearningEventInput`, versioned as `learning-event-v1`;
- `LearningEventV1`, which adds server-recorded time after persistence.

The contracts distinguish:

- `occurred_at`: domain occurrence time supplied by the trusted server-side
  caller and normalized to UTC;
- `recorded_at`: database-clock recording time assigned by the repository.

Events carry UUID identity, type, actor, optional learner/course, causation and
correlation IDs, typed payload, optional version stamps and an idempotency key.
Payload keys containing credential, password, secret, token, authorization or
private-key terms are rejected.

The existing Phase 2 `LearningEvent` Pydantic contract and
`LearningEventRecord` legacy columns remain available. Migration 0006 marks
pre-existing rows as `legacy-phase2-v1` without rewriting their payloads.
`event_from_record()` refuses to reinterpret non-v1 rows; legacy readers may
continue reading them through the existing record shape.

## Transaction ownership and idempotency

`insert_learning_event(session, event)` accepts an existing SQLAlchemy
`AsyncSession` and never calls `commit()`. The caller controls commit or
rollback, allowing a future answer transaction to combine domain changes,
evidence, mastery, event records and jobs.

The event repository:

- replays the same logical event for a repeated idempotency key;
- raises `LearningEventConflictError` when that key is reused with different
  event content;
- detects event-ID collisions separately;
- uses a nested savepoint to handle concurrent duplicate inserts without
  poisoning the caller's outer transaction;
- verifies actor identity/subject consistency before insertion.

`create_job_in_transaction()` provides the same transaction-owned behavior for
durable PostgreSQL jobs. It creates the initial `job.created` progress event in
the same session, replays identical requests by idempotency key, and raises
`JobIdempotencyConflictError` for conflicting reuse. It does not publish Redis
wake-ups; publication belongs after the caller commits.

## Migration 0006

`alembic/versions/0006_learning_identity_events.py` adds:

- `student_identities` with primary key, provider/subject uniqueness and index;
- nullable actor and learner identity foreign keys on `learning_events`;
- nullable v1 schema, occurrence time, idempotency key and version metadata;
- non-null server recording time populated from legacy `created_at`;
- nullable `course_id` to support course-less event types while preserving the
  existing course foreign key for course-scoped events;
- deterministic learner, actor, event-type/course and time indexes;
- a unique nullable idempotency key, allowing legacy rows with no key.

The upgrade is additive and preserves all existing event records. Downgrade
refuses to run while identity or learning-event data exists, rather than
silently discarding it. Empty-schema downgrade remains available for migration
test isolation.

## Tests

- `tests/unit/test_identity_events.py`: opaque-subject stability, provider
  namespace, authorization, timestamp separation, restricted payloads and
  causation validation. Includes Hypothesis subject-property coverage.
- `tests/integration/test_identity_events_runtime.py`: concurrent identity
  resolution, event idempotency/conflict handling, actor-subject validation,
  deterministic reads, legacy compatibility, transaction rollback and
  transaction-compatible job creation.
- Existing Phase 2 upload/event tests remain unchanged and continue using the
  legacy event shape.

## Limitations and future integration points

- There is no public learner-state API or role/delegation store in this sprint.
- Existing Phase 2 upload events are actor-subject/course/payload records and
  are not retroactively converted into v1 learner events.
- The event repository does not decide instructor delegation; a future
  authorization service must verify that policy before accepting an event with
  different actor and learner identities.
- Graph publication, mastery/evidence transactions, planner events and session
  orchestration will consume these caller-owned repositories in later sprints.
