# ADR 0028: Stage 2 durable runtime contracts and immutable history

## Status

Implemented under the owner's Sprint 3.7 **Stage 2 only** authorization. Stage 1
and ADR 0027 are accepted. Runtime repositories and orchestration remain later
checkpoints. This ADR adds storage mechanisms without changing accepted learning
policies or the Sprint 3.6 planner.

## Context

The existing pure planner consumes detached `PlanningState` and emits a canonical
`PlannerDecision`. Neither value owns a committed session transition, a plan
publication, an educational execution or a diagnostic reservation. Job delivery
attempts and bounded pipeline checkpoints are separate transport state.

Build-spec §§12.3–12.5 require a durable event-linked FSM, safe plan versions and
recoverable actions. The assessment identifies missing ownership of sessions,
frames, plans, execution receipts and diagnostic inventory. Stage 2 establishes
their contracts and schema, before implementing their transaction protocol.

## Decision

### Detached contracts and identities

`packages/domain/runtime.py` contains frozen, extra-forbidding values. Timestamps
must be aware and are normalized to UTC. Caller-provided times and policy versions
are required; this module has no clock, random identity generation, I/O or policy
evaluation. Identity UUIDs are UUIDv5 over canonical, namespace-qualified JSON:

- Source: source kind and original source UUID.
- Trigger: learner, source, trigger kind and optional window UUID.
- Plan version: session, trigger and positive version number.
- Educational execution: immutable plan-version UUID, **without** delivery attempt.
- Worker attempt: job UUID and positive attempt number.

These describe separate equivalence classes. A source event may justify multiple
different trigger kinds; neither a trigger nor a worker attempt is an execution.
Trigger evaluation, window allocation and cooldown ownership are deferred.

### Macro FSM and remediation

Retain all §12.3 macro states and add explicit `NEEDS_STATE`. The immutable
transition table permits the documented progression, replanning back to teaching
or retrieval/diagnosis, and advancement back to planning. All nonterminal states
can pause or need state. Pause and needs-state recover through planning, where
dependencies can be revalidated. Event-linked same-state transitions support
position/head changes during a macro phase; they still increment the version.
`COMPLETE` has no outgoing transition, including a self-transition.

Remediation is a separate frame stack, not a second macro FSM. Teaching a
prerequisite and returning to the saved topic use the existing macro states.
Frames retain parent/depth, graph and target/return identities, rung/strategy,
versioned guard configuration, baseline/latest mastery, attempt count and state.
Progress delta is latest minus baseline, without evaluating exhaustion here.
Push and return each have a unique educational execution identity; immutable
attempt rows refer to actual learner `mastery_attempts`, never worker attempts.

### Plan history and execution receipts

One immutable plan aggregate belongs to a session. Each immutable version stores
the **exact canonical snapshot and decision bytes**, SHA-256 fingerprints,
source/trigger, session/frame versions, graph/revision, policy versions, schema
version, creation time and predecessor. Full snapshot bytes retain projection,
evidence, freshness, graph, directive and diagnostic context; decision bytes
retain existing reasons, confidence and provenance. Successor versions reference
the immediately preceding version within the same plan. Supersession is a new
row and a mutable session head, not an edit to historical decisions.

One receipt belongs to an immutable plan version. Its educational identity is
unique across transport deliveries. The receipt stores action/target/policy and
the session fence, versioned execution status, confirmation event, emitted
event/child job identities, and the original completion-result bytes/timestamp.
Frame version and original source context are available through the immutable
plan FK. `STALE` and `SUPERSEDED` are durable terminal results. BLOCK cannot
dispatch, and REQUIRE_CONFIRMATION cannot dispatch without a linked event.
Terminal results cannot be changed or deleted. Repository code must eventually
validate confirmation authority and current dependencies; the schema is not
an operational executor or a concurrency protocol.

### Diagnostic budget and provenance

A run belongs to learner/course/session/graph and records its original source,
policy, bounded item budget and terminal completion event/time. Reservations are
normalized rows, unique by `(run, question_version)` and `(run, slot)`.

Slots start at one and must be at most the run's immutable budget. A composite FK
binds a reservation's copied budget/session/graph to the run. Thus at most the
budget number of reservation rows can exist for that run. A reservation keeps its
slot for its lifetime: retries/completion do not delete or recycle it, and the
budget cannot be expanded by updating the run. Remaining budget and attempted /
assessed inventories can later be assembled from these rows, without redundant
mutable counters. The run can retain a zero budget; it cannot have a reservation.
Future repositories must reserve atomically and choose disjoint eligible items.

Attempted/assessed states bind actual original question/attempt/direct evidence
identities and completion events. Inference links bind existing Stage 1 inferred
ledger identities to an assessed reservation and its original source/run/target.
Original question/graph/confirmed edge provenance stays in `mastery_evidence`.
No existing inference row is backfilled or newly subjected to a run FK. Existing
accepted inference identity/formula and direct-evidence semantics are unchanged.

### Storage and migration boundary

`packages/persistence/runtime_models.py` defines ten tables; no repository methods
are added. Migration `0011_sprint37_runtime_contracts` follows accepted `0010`.
Its SQL/enum values are frozen in the migration, independent of future application
imports. Existing tables/rows and historical migrations are untouched.

All new FKs restrict deletion. PostgreSQL constraints validate enumerated states,
positive revisions, budgets, source completion shape, hashes, canonical decision
columns and scoped dependencies. Schema triggers enforce append-only history,
immutable aggregate identities/terminal receipts, matching snapshot provenance,
predecessor/graph lineage and diagnostic original-source linkage. These triggers
validate storage only: they do not call the planner, accept outcomes, apply mastery,
count triggers, reserve questions, publish jobs or mutate session/frame heads.

Empty downgrade removes all ten tables, indexes, constraints and four functions;
populated downgrade refuses before removing anything. This follows the existing
data-preserving migration precedent. Tests upgrade/downgrade/re-upgrade only
fixture-created databases, including preservation of existing Stage 1 evidence.

## Consequences and verification

The durable schema now has explicit separate ownership and immutable history.
Contracts and live tests cover legal/illegal FSM pairs, identity equivalence,
canonical provenance, successor history, terminal receipts, actual unique-key
races, bounded/disjoint reservations, original-source inference linkage and
safe migration reversibility. Full results are recorded in `docs/SPRINT_3_7.md`.

The next stages still own authoritative assembly, learner serialization, head and
version compare-and-swap, event/head atomicity, once-only counters, transaction
rollback, child-job publication, confirmations and stale-result execution fences.
Constraints alone do not establish those operational guarantees.
