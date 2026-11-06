# Sprint 3.7: deterministic adaptive runtime — Block A checkpoint

## Status and scope

**Stages 1 and 2 are accepted. Build Block A (Stages 3–5) is implemented and
verified below. The complete Sprint 3.7 runtime is not complete.** Stages 6–11
remain pending. The assessment remains the unchanged historical record at
`docs/SPRINT_3_7_ASSESSMENT.md`.

Sources: build spec v3.2, accepted Sprint 3.4/3.5 policy decisions, Sprint 3.6
implementation/ADRs, and the Sprint 3.7 implementation authorization. ADR 0027
records the baseline persistence mechanisms. No protected document, historical
migration, planner precedence or mastery/review/graph formula is changed.

## Stage 1 architecture and durable ownership

```text
caller-owned PostgreSQL transaction
  existing learner identity lock
  original immutable direct evidence + optional matching grading event
  validated source-linked diagnostic inferred evidence
  pure chronological mastery replay
  immutable projection revisions/heads and review schedules
  application markers
commit owned by caller

due processing in a caller-owned transaction
  learner identity lock -> schedule locks in concept UUID order
  pure selection from persisted state and explicit time
  existing cycle -> replay original notification envelope
  new cycle -> create first immutable v1 REVIEW_DUE envelope
```

There is no database access or execution logic added to the pure planner,
scheduler, diagnostic selector, graph algorithms or mastery engine. Pure replay
normalizes immutable evidence fields and preserves other concepts when applying
one concept's evidence.

## REVIEW_DUE retry behavior

- Approved cycle/key/event identity formulas are unchanged.
- The first committed notification preserves actor, occurrence time, correlation,
  payload, projection provenance, receipt times and other immutable fields.
- Exact and later-time retries reuse that envelope through the unchanged strict
  v1 event writer. A newer projection revision for the same evidence/cycle does
  not rewrite notification history.
- Candidate provenance must match the locked current schedule. Conflicting
  supporting source state, explicit correlation, actor, cycle or stored envelope
  is rejected rather than treated as successful replay.
- New events record canonical cycle material and the explicit anchor event in
  addition to existing provenance. Old valid events do not need rewriting.
- Current eligibility/reasons remain pure selector results. `REVIEW_DUE` remains
  non-impact and contributes no evidence or concept-impact association.
- A real new schedule cycle produces a different approved identity and retains
  the prior event. Concurrent first emissions converge under the schedule lock.

## Immutable evidence digest and projection timestamps

Replay hashes only the approved immutable `EvidenceInput` fields and existing
self-report contribution fields. The persisted evidence object's receipt and
application timestamps do not enter that digest. Repeating the same accepted
source at another projection time has the same digest while legitimately changing
decayed values.

Persisted projection values are interpreted at `MasteryProjectionRevision.as_of`.
Restored domain state uses that timestamp. Reads at equal time do not decay again;
later reads decay only from that time. Ledger `max_occurred_at` remains audit/replay
boundary metadata, including late-evidence replay.

Historical projections with older digests are retained. Stage 1 does not rewrite
existing revisions or development data; future authoritative freshness/rebuild
assembly must account for those historical revisions explicitly.

## Diagnostic inference persistence

The existing application seam now accepts:

```python
await apply_evidence(
    session,
    original_direct_evidence,
    actor_subject=authenticated_subject,
    concept_event=original_grading_event,
    diagnostic_inferences=confirmed_provenance,
)
```

Provenance must refer to that exact learner, original evidence, attempt, question
version and historical graph. The source must be a full-credit non-review direct
answer. The repository verifies the original metadata and confirmed transitive
closure using the same pure diagnostic algorithm as Sprint 3.5.

Derived ledger rows retain the original question/attempt/evidence source and
confirmed edge/run/target provenance. No source question roles, question versions,
attempts or learner answers are fabricated. The normal evidence acceptance path
does not accept a separately submitted derived diagnostic request.

The existing positive inferred formula applies once per source attempt/prerequisite.
Derived evidence adds no direct count, distinct direct question, review success,
review rung or MASTERED qualification. Chronological replay retains the source
concept's direct posterior alongside inferred prerequisite posteriors. A replay
can reconcile missing inferred contributions for a committed direct source without
doubling its direct mass/count.

## Additive migration 0010

`alembic/versions/0010_sprint37_stage1_alignment.py` extends `mastery_evidence`:

| Addition | Purpose |
| --- | --- |
| Nullable `inferred_source_evidence_id` FK to `mastery_evidence.id` | Original accepted direct evidence link; RESTRICT deletion |
| Nullable `inferred_source_attempt_id` FK to `mastery_attempts.id` | Original attempt link; RESTRICT deletion |
| Nullable `inferred_target_concept_id` | Stable prerequisite identity in the original graph |
| `ck_mastery_evidence_inference_source` | Linked derived rows require all linkage fields, INFERRED kind and provenance; existing unlinked rows remain valid |
| `uq_mastery_evidence_inferred_source_target` | Unique partial index on source attempt/target for INFERRED rows |

No new runtime tables are introduced in Stage 1. No historical migration or
existing ledger row is rewritten. Downgrade refuses populated derived linkage.

## Concurrency and recovery

Supported mastery/self-report application locks the existing learner identity
before reading accepted sources. This handles first insertions when no projection
head or schedule exists and prevents independently computed overlapping replays
from overwriting a newer source set. Critical locked rows are refreshed instead
of relying on a preloaded ORM cache.

Lock ordering is learner identity, source evidence, then concept-ordered projection
heads/schedules. Due processing follows learner then concept-ordered schedules.
Derived insertion has a nested-savepoint unique-conflict path and exact immutable
comparison. No worker attempt number is used as a learning/inference identity.

All evidence, optional grading event, inferred rows, projections, schedules and
markers are in the caller transaction. Failure before commit rolls everything
back. A lost response can replay durable source identities; a transport retry does
not create another inferred contribution or projection revision. Stage 1 neither
requires Redis nor publishes follow-up jobs.

## Runtime spine stages pending after Stage 1

The following were **not implemented at the accepted Stage 1 checkpoint**:

- Durable session FSM, plans/versions, remediation frames, execution receipts,
  diagnostic runs and reservation repositories.
- Once-only material-trigger accounting, topic windows, student-wide 60-second
  cooldown, directive exception and durable deferred-trigger recovery.
- Authoritative coherent planning snapshots, gate evaluation/current graph
  selection, existing pure planner invocation and immutable plan publication.
- Authorized deterministic action execution, stale dependency rejection,
  event-linked session transitions, bounded remediation attempts/progress/return.
- Diagnostic/review work reservation, completion and runtime reconciliation.
- Runtime worker/job publication fences, crash recovery and remaining concurrency
  scenarios, then complete Sprint 3.7 verification.

Planner first-match precedence remains unchanged, including an authorized untaught
topic taking `TEACH_CURRENT_TOPIC` before diagnostics. Numeric trigger, guard,
gate and cooldown policies remain the approved existing policies; Stage 1 introduces
no alternative runtime interpretation of them.

## Explicit exclusions

No public learner submission API, production grading/tutoring, LLM/Llama calls,
retrieval/RAG, frontend/dashboard, cloud fallback, Kubernetes, model training,
new broker or giant macro LangGraph. The later Phase 4/6/7/8 product work remains
deferred. Deterministic source fixtures are test adapters, not production tutoring.

## Verification record

Focused pure/component checkpoint: **114 passed**, one existing warning.
Focused live checkpoint: **30 passed**, one existing warning, using isolated
tmpfs-backed services; expanded rollback/schema checkpoint: **35 passed**, one
existing warning. The final full live suite includes the additional anchor-conflict
regression added during the final source review.

Ruff passed; strict mypy passed across **58 package source files**; all **seven
import contracts** passed. The warning is Starlette TestClient's deprecated
`anyio.abc.BlockingPortal` alias.

The initial broad smoke run skipped live cases; those skips were not counted as
live validation. An early projection-test assertion incorrectly expected beta at
the prior to decrease and failed (7 passed/1 failed); it was corrected to compare
both alpha and beta against the unchanged half-life formula. Subsequent focused
live checks passed. Final verification results below supersede intermediate runs.

Nothing is staged or committed. Protected-source and assessment hashes and
`__agent__/plan.json` are checked against the captured baseline. HEAD remains
`7f9391e0df52a02f851371a053fe6930adabb037`.

### Final executed Stage 1 verification

| Command/check | Actual final result |
| --- | --- |
| `make test` | 339 passed, 117 skipped, one warning, 4.78 seconds |
| `make check` | Ruff passed; strict mypy 58 files passed; seven import contracts kept; pytest 339 passed / 117 skipped / one warning, 4.40 seconds |
| `make integration` | 120 passed, zero skipped, one warning, 151.32 seconds |
| `docker compose --profile mock config --quiet` | Passed |
| `docker compose --env-file /dev/null -f infra/compose/test.yml config --quiet` | Passed |
| `git diff --check` and new/untracked-file whitespace checks | Passed |

The ordinary test/check skips are the opt-in live cases; all ran successfully in
the live integration command. There are **29 added test cases**: three pure
regressions and 26 live regressions. No real model or external paid/cloud service
was invoked. Migrations and database operations ran only against fixture-created
test databases; no development migration/reset was performed and no Docker volume
was deleted.

### Files added in this pass

- `alembic/versions/0010_sprint37_stage1_alignment.py`
- `tests/integration/test_sprint37_alignment.py`
- `docs/decisions/0027-stage1-adaptation-persistence-alignment.md`
- `docs/SPRINT_3_7.md`

### Existing files modified in this pass

Some implementation/test files were already untracked baseline work; they remain
preserved in place and are not reported as newly created by this pass.

- `packages/curriculum/diagnostics.py`
- `packages/mastery/engine.py`
- `packages/persistence/mastery.py`
- `packages/persistence/models.py`
- `packages/persistence/review_schedule.py`
- `tests/unit/test_mastery_engine.py`
- `tests/integration/conftest.py`
- `tests/integration/test_mastery_runtime.py`
- `tests/integration/test_sprint35_runtime.py`
- `tests/integration/test_migrations.py`

### Checkpoint limitations

The assessment's required freshness assembler, runtime receipts, session/frame
ownership, triggers, execution and remaining concurrency/recovery concerns are
for stages 2–11. Evidence duplicates still return current projection heads,
not an original immutable outcome/execution receipt. Historical unlinked inferred
rows and old digests are retained and require explicit future reconciliation;
Stage 1 does not silently backfill or reinterpret them.

The Stage 1 pass stopped at this verified checkpoint. Its results above remain
the historical Stage 1 verification record.

## Stage 2: durable contracts and storage

ADR 0028 documents the storage choices and derived legal transition table.
`packages/domain/runtime.py` adds detached frozen session/transition, plan/version,
frame/attempt, execution receipt and diagnostic run/reservation/inference-link
contracts. Source, trigger, plan, educational execution and worker attempt have
distinct deterministic namespace-qualified identities. Educational execution
does not depend on worker delivery count. Explicit aware timestamps, versions
and policy stamps are validated; no trigger/guard algorithm is implemented.

The macro FSM retains §12.3 states and adds `NEEDS_STATE`; remediation is owned
by separate frames. Pause/needs-state recover via planning. Every transition
increments its version by exactly one and links an event. Same-state nonterminal
transitions permit event-linked position/head changes; COMPLETE is terminal.

### Additive migration 0011 and table inventory

`0011_sprint37_runtime_contracts` follows `0010_sprint37_stage1_alignment`.
The ten models live in `packages/persistence/runtime_models.py`, registered through
the persistence package and Alembic metadata. Migration SQL is frozen and does
not import application models/enum values.

| Table | Durable ownership / principal constraints |
| --- | --- |
| `learning_sessions` | Learner/course/state/version, graph/topic, plan/frame heads, last event, lifecycle timestamps; `uq_sessions_scope`, `ck_sessions_state/version/times/completion/position`, scoped topic/head FKs |
| `learning_session_transitions` | Append-only event-linked legal from/to and one-step version history; PK session/event, `uq_session_transitions_version`, `ck_session_transitions_version/legal` |
| `learning_plans` | Immutable aggregate identity per session; `uq_plans_session/scope` |
| `learning_plan_versions` | Immutable version/source/trigger, canonical snapshot and decision bytes/hashes, session/frame fence, graph/revision, policies/schema, predecessor and creation; `uq_plan_versions_number/trigger/session/plan/execution_context`, scoped plan/frame/predecessor FKs; `ck_plan_versions_versions/predecessor/frame/graph/source/action/policy_outcome/digests/decision_context/policy_versions` |
| `learning_execution_receipts` | One educational execution per plan version, exact action/target/policy/session fence, versioned state, confirmation, child jobs/events and original result/time; `uq_execution_receipts_plan_version/session`, scoped plan-context FK; `ck_execution_receipts_state/version/completion/children/block/confirmation` |
| `remediation_frames` | Graph concept, saved topic return, stack parent/depth, push/return executions, rung/strategy, guard policy/config, attempts, baseline/latest progress, version/state/event/times; `uq_remediation_frames_session/execution/return_execution`, scoped execution/parent/target/return FKs; `ck_remediation_frames_state/bounds/progress/parent/return` |
| `remediation_frame_attempts` | Immutable actual learner attempt/rung/event/observed mastery; PK frame/attempt, `uq_frame_attempts_source/event`, `ck_frame_attempts_bounds` |
| `diagnostic_runs` | Learner/course/session/graph, policy, immutable budget, original source/event, version/state, completion event/time; `uq_diagnostic_runs_context/source`, scoped session FK; `ck_diagnostic_runs_state/source/bounds/completion` |
| `diagnostic_reservations` | Unique question and budget slot, run/graph/session/execution, versioned reserved/attempted/assessed state, actual original attempt/evidence, assessed concepts/event/times; `uq_diagnostic_reservations_slot/question/attempt/evidence`, scoped run/execution/target FKs; `ck_diagnostic_reservations_state/bounds/attempt/assessment` |
| `diagnostic_inference_links` | Existing inferred evidence identity linked to assessed reservation and original target/run/source; evidence PK, `uq_diagnostic_inference_links_target`, reservation/evidence FKs |

All tables have primary keys; all new FKs use RESTRICT. Existing evidence,
attempts, question versions, graph/revision and event rows are reused without
rewriting or fabricated questions/answers. Canonical snapshot bytes retain full
projection/evidence/freshness context; canonical decision bytes retain reasons
and existing provenance. New versions reference their immediate predecessor.
Original source/frame context in a receipt is retained through the immutable plan.

Indexes beyond primary/unique-constraint indexes:

- `ix_sessions_learner_course_state` (learner, course, state).
- `ix_plan_versions_session_created` (session, creation time).
- `ix_execution_receipts_session_state` (session, state).
- `uq_remediation_frames_active_depth` (session, depth), partial unique for ACTIVE
  and COMPLETE frames awaiting return.
- `ix_diagnostic_runs_learner_state` (learner, state).

Four schema-only PostgreSQL functions are installed:

- `sprint37_append_only`: rejects updates/deletes to plan aggregates/versions,
  transition history, learner frame attempts and inference links.
- `sprint37_runtime_identity`: rejects identity rewrites/deletes, changing terminal
  results, replacing a diagnostic original attempt and changing run budget/slot.
- `sprint37_plan_context`: checks snapshot/decision ownership and digest provenance,
  immediate predecessor, graph/revision lineage and snapshot dependency identities.
- `sprint37_diagnostic_source`: checks original non-review question/attempt/direct
  evidence context and source-linked inferred ledger identity.

They validate stored contracts; publication/acceptance/execution remain future
repository operations. Trigger constraints do not run educational trigger logic.

### Diagnostic reservation accounting

Reservations retain one distinct slot permanently. Slot range is bounded by a
copied budget, which is constrained by a composite FK to the immutable run budget
(0–12). No run can have more reservations than its budget. Question version and
source attempt/evidence uniqueness prevent duplicate ownership. Completion
changes the existing reservation, with original source linkage; it does not spend
a second slot. Remaining budget and attempted/assessed sets are to be assembled
from normalized rows. No operational reservation selector/locking is added.

### Reversibility and preservation

Upgrade creates only new tables/constraints/indexes/functions. Existing tables,
Stage 1 data and historical migrations are unchanged. Empty downgrade removes
the new objects and supports re-upgrade. Any populated runtime table causes an
explicit refusal **before any object is removed**, preserving history and revision.
All executed migrations use isolated fixture-owned databases.

### Stage 2 verification

Focused contracts/schema/migrations: **56 passed**, one existing warning (29
pure cases, 24 new live schema cases and three existing migration cases). Live
schema checks include all 144 macro FSM state pairs, actual concurrent unique-key
collision, distinct bounded reservation slots, successor immutability, original
diagnostic completion/inference linkage, cross-learner rejection, empty reverse /
re-upgrade and populated refusal. Intermediate failures were test reflection
aliases, expected validation ordering and a duplicate-subject fixture; subsequent
focused runs passed. Full final checks are recorded after execution below.

### Stage 2 scope and remaining ownership

No runtime repository, trigger evaluator, snapshot assembler, action executor or
worker handler is implemented. Stage 3+ must make session head/version changes
atomic with history/events, serialize learners, enforce cooldown/guard counters,
validate current dependencies/confirmation authority, and own reservations,
child publication and crash recovery. Tests of direct schema insertions establish
storage guarantees, not educational exactly-once execution. Planner precedence,
accepted numeric policies, Stage 1 fixes and pure component boundaries are retained.

New Stage 2 files:

- `packages/domain/runtime.py`
- `packages/persistence/runtime_models.py`
- `alembic/versions/0011_sprint37_runtime_contracts.py`
- `tests/unit/test_runtime_contracts.py`
- `tests/integration/test_runtime_schema.py`
- `docs/decisions/0028-stage2-durable-runtime-contracts.md`

Existing files extended for Stage 2: `packages/domain/__init__.py`,
`packages/persistence/__init__.py`, `alembic/env.py`,
`tests/integration/test_migrations.py`, and this checkpoint document.

### Final executed Stage 2 verification and workspace state

| Command/check | Actual final result |
| --- | --- |
| Focused contracts + live schema + migrations | 56 passed, zero skipped, one warning, 45.03 seconds |
| `make check` | Ruff passed; strict mypy 60 package files passed; seven import contracts kept; pytest 368 passed / 141 skipped / one warning, 4.07 seconds |
| `make integration` | 144 passed, zero skipped, one warning, 183.16 seconds |
| `git diff --check` and new/untracked-file whitespace checks | Passed |
| Protected documents, accepted Stage 1 implementation and bookkeeping hashes | Match the captured Stage 2 starting baseline |

The 141 ordinary-check skips are opt-in live tests; the full integration run
executed them successfully. Stage 2 adds **53 test cases** (29 pure and 24 live).
The sole warning remains Starlette TestClient's deprecated BlockingPortal alias.

The initial dirty workspace is preserved: 25 modified tracked files remain,
with existing untracked implementation/documents and six new Stage 2 files.
Nothing is staged or committed; HEAD remains
`7f9391e0df52a02f851371a053fe6930adabb037`. Source/policy documents, the historical
assessment, `__agent__/plan.json`, accepted Stage 1 implementation and migration
0010 are unchanged. Development databases/services were not migrated or reset;
tests used disposable tmpfs-backed services and no Docker volumes were deleted.

**Stop at the verified Block A checkpoint.** Stages 6–11 and complete Sprint 3.7
runtime acceptance remain pending.

## Build Block A: Stages 3–5

Block A establishes the boundary:

```text
durable runtime state -> material trigger evaluation -> coherent planning snapshot
```

The pure planner remains downstream and unchanged. Block A does not publish plan
heads, dispatch educational actions, mutate remediation ladders, execute diagnostic
or review work, or run worker handlers.

### Stage 3: explicit runtime repositories

`packages/persistence/runtime.py` provides caller-owned operations with no hidden
commit. Every entry point verifies an explicit transaction, locks the existing
learner identity first, then locks the session or operation-specific row. It uses
typed `RuntimeConflictError`, `RuntimeStaleError` and `RuntimeValidationError`
results rather than booleans.

Implemented boundaries include session creation and legal event-linked transitions,
immutable plan-version storage, frame create/update and actual-attempt recording,
execution receipt create/update, diagnostic run creation/reservation/acknowledgment,
inference linkage, worker-attempt-to-execution linking, topic-window facts,
directives and completed assessment batches. Read helpers return refreshed rows.

The caller owns transaction commit. Exact retries return the original operation
result from `runtime_operation_receipts`; changed requests conflict. Concurrent
first writes serialize on learner ownership. Expected session, frame, plan,
execution, run and reservation versions are checked before mutation. Terminal
execution results, immutable plan bytes, source facts and original trigger results
are never overwritten. Worker attempts are linked only after the job and child
execution identity already exist.

### Stage 4: material triggers, cooldown and recovery

`packages/domain/triggers.py` and pure `packages/planner/triggers.py` define the
typed trigger facts/evaluation boundary. The evaluator consumes only persisted or
assembled facts and explicit `as_of`; it has no database, clock, planner, HTTP,
Redis or execution dependency. `RuntimePolicy` records the approved runtime
thresholds: two distinct qualifying incorrect items at weight >= 0.5 in the same
topic window, WEAK entry confidence >= 0.3, completed check/quiz batch, strong quiz
>= 0.9 with at least three items and a satisfied gate, curriculum edit, nightly
review/decay, explicit directive and deadline change.

Single wrong answers are evidence-only. Read/replay facts and non-concept-impact
events do not count. Active remediation suppresses nightly review insertion;
assessment completion remains independent. Invalid, expired or duplicate directives
are typed rejection results. Missing/stale state, terminal session and active
remediation are explicit guard codes.

`runtime_triggers` stores the first evaluation, original request/result bytes,
source event, status and cooldown deadline. Trigger identity remains distinct from
the source event and future plan version. The learner-wide admitted-trigger lookup
enforces one plan-triggering event per 60 seconds across sessions/courses;
directives bypass it. Deferred records are not overwritten: `recover_deferred_trigger`
revalidates the current facts at/after the durable deadline and updates only the
recovery status, retaining the original evaluation result.

### Stage 5: authoritative planning snapshot

`packages/persistence/planning_snapshot.py` locks learner/session ownership and
reads refreshed authoritative rows for the current published graph, topic mappings,
projection heads/revisions, evidence digest/count, review candidates/unavailable
freshness, frame, directives, current plan version, latest assessment batch,
diagnostic run/candidates and trigger context. It does not infer missing state.

The snapshot explicitly preserves `FRESH`, `MISSING_PROJECTION`,
`MISSING_REVISION`, `EVIDENCE_SET_STALE` and `GRAPH_CONTEXT_STALE`, plus typed
runtime guards. Current evidence graph lineage is checked against the current
published graph. Invalid persisted graph facts remain unavailable rather than being
silently converted into a planning graph. The snapshot contains deterministic
canonical data and a SHA-256 fingerprint covering session, graph, freshness,
evidence, projection revisions, window/frame, assessment, diagnostics, directives,
trigger and plan context. `revalidate_planning_snapshot` rejects changed session
version/event fences before later planner use.

The returned `planning_state` is a detached adapter for the existing pure planner;
this stage does not call it, persist a decision, publish a version or execute an
action.

### Block A migration and files

Migration `0012_sprint37_block_a` follows immutable migration 0011 and adds seven
tables: `runtime_operation_receipts`, `runtime_topic_windows`,
`runtime_directives`, `runtime_assessment_batches`, `runtime_window_evidence`,
`runtime_worker_execution_links` and `runtime_triggers`. New facts have scoped
foreign keys, append-only/identity triggers, unique source/attempt/event keys and
the durable trigger status/cooldown index. Populated downgrade refuses before
destructive removal; empty downgrade/re-upgrade remains covered by the migration
suite. No historical migration or development database was changed.

New Block A files:

- `packages/domain/runtime_state.py`
- `packages/domain/runtime_policy.py`
- `packages/domain/triggers.py`
- `packages/domain/snapshot.py`
- `packages/planner/triggers.py`
- `packages/persistence/runtime.py`
- `packages/persistence/runtime_support_models.py`
- `packages/persistence/planning_snapshot.py`
- `alembic/versions/0012_sprint37_block_a.py`
- `tests/unit/test_runtime_triggers.py`
- `tests/integration/test_block_a_repositories.py`
- `tests/integration/test_block_a_triggers_snapshot.py`
- `docs/decisions/0029-block-a-runtime-ownership.md`

Extended files include domain/persistence exports, Alembic metadata wiring,
migration head expectations and this checkpoint document.

### Block A transaction and concurrency model

Authoritative writes use learner identity -> session -> operation row ordering.
Snapshot reads use learner identity -> session -> concept/projection reads. A
concurrent identical first operation returns one original receipt; a changed
request conflicts. A stale caller fails its expected-version fence. A lost
response reloads the operation receipt. A pre-commit crash rolls back the caller
transaction; no Redis notification is authoritative. Snapshot assembly rechecks
the session fence before returning, and detached snapshots can be revalidated
again immediately before future planner use.

### Block A verification

Focused Block A contracts, repository, snapshot, trigger and migration checks:
**74 passed**, one existing warning. This includes 61 pure contract/trigger cases
and 13 live repository/snapshot/migration cases. The final full verification is
recorded after the commands below.

Known limitations intentionally deferred to Stages 6–11: plan publication and
session-head mutation, authoritative trigger-to-plan transaction routing, full
gate assembly from curriculum policy, complete diagnostic state reconciliation,
execution dispatch/confirmation, remediation ladder orchestration, review/diagnostic
reservation execution, worker publication fences and crash recovery campaign.

### Final Block A verification record

| Command/check | Actual final result |
| --- | --- |
| `make test` | **400 passed, 151 skipped, one warning**, 4.12 seconds |
| `make check` | Ruff passed; strict mypy **68 package files** passed; **7 import contracts** kept; pytest **400 passed / 151 skipped / one warning**, 4.19 seconds |
| `make integration` | **154 passed, zero skipped, one warning**, 206.16 seconds |
| Focused Block A live repository/snapshot/migration tests | **13 passed**, one warning |
| Focused pure runtime contract/trigger tests | **61 passed**, one warning |
| Compose configuration checks | Passed for mock and isolated test Compose files |
| `git diff --check` and new/untracked-file whitespace checks | Passed |

The ordinary-check skips are opt-in live tests; the full integration command ran
all integration tests successfully. The only warning remains Starlette
TestClient's deprecated `anyio.abc.BlockingPortal` alias. No real LLM, paid API or
external cloud service was used.

**Stages 3–5 complete. Stages 6–11 remain pending.**

## Build Block B: Stages 6–7

Block B completes the first deterministic decision-to-action vertical slice:

```text
authoritative snapshot -> pure planner -> immutable plan -> authorized action
                         -> execution receipt -> event-linked session transition
```

### Stage 6: planner invocation and immutable publication

`packages/persistence/planning.py` is the orchestration boundary. It revalidates
the detached Stage 5 snapshot, invokes the existing `PlannerPolicy.decide()`
entry point exactly once, and constructs the existing frozen `PlannerDecision`
and `DurablePlanVersion` contracts. No planner logic was duplicated and the
Sprint 3.6 first-match precedence remains unchanged, including authorized
untaught topic plus pending diagnostic selecting `TEACH_CURRENT_TOPIC`.

Plan aggregate identity is deterministic per session. Plan-version identity is
derived from session, durable trigger identity and successor version. Published
versions retain immutable canonical planning-state bytes, decision bytes and
digests, the Stage 5 source snapshot fingerprint, planner/mastery policy
versions, graph/revision identity, frame/version fence, source event, trigger,
predecessor and creation timestamps. The current session plan head is updated
in the same caller-owned transaction as the version insert.

`publish_plan_version()` checks application-level immutable material before
returning an existing retry, validates the expected session head and predecessor,
and rejects stale different publications. A trigger plan link is inserted only
after its plan row exists. `runtime_trigger_plan_links` makes admitted trigger
consumption durable and unique; duplicate delivery reloads the original plan.
Triggerless invocations use a deterministic planner-invocation trigger identity
without fabricating a material trigger journal row.

Stage 5 snapshots now expose the next successor plan version. Exact plan retries
can still reload an already committed version from its immutable operation receipt
even when the session head has already advanced.

### Stage 7: authorized deterministic educational execution

`packages/domain/execution.py` provides `DeterministicEducationalExecutor` and a
typed `EducationalExecutionResult`. It returns stable canonical request/result
bytes only; it generates no lesson, question, retrieval result or model output.

`packages/persistence/execution.py` provides `execute_published_plan()` with an
explicit caller-owned transaction. It verifies the current plan head, session
fence, graph/topic/frame dependencies, reassembled planning dependencies,
directive state, diagnostic-run state and trigger-plan admission before action.
Changed dependencies produce a typed stale error rather than execution against
newer state.

Educational execution identity remains derived only from the immutable plan
version. Worker attempts remain separate infrastructure identities and are linked
after receipt creation. Multiple worker retries can point to the same educational
execution without producing another learner-facing action.

Execution receipts retain canonical request bytes/digest, result bytes/digest,
receipt fingerprint, plan/session/action/policy provenance, completion state and
timestamps. Terminal receipts cannot be overwritten. Exact retries return the
existing receipt. Changed immutable execution input conflicts. Deterministic
executor failures become durable `FAILED` receipts without a successful session
transition.

For successful actions, `execute_published_plan()` records the receipt and then
creates the legal event-linked FSM transition in the same transaction. The
transition retains both plan-version and educational-execution identities. The
existing FSM is unchanged; action-to-state mapping uses only already-approved
states such as `TEACHING`, `CHECKPOINT`, `ASSESSING`, `DIAGNOSING`, `ADVANCE` and
`COMPLETE`.

### Block B migration and files

Migration `0013_sprint37_block_b` follows `0012_sprint37_block_a` and adds:

- `learning_plan_versions.source_snapshot_fingerprint`
- execution request/result/receipt digest material
- optional plan/execution links on `learning_session_transitions`
- immutable `runtime_trigger_plan_links`

The migration is additive, has empty upgrade/downgrade/re-upgrade coverage, and
refuses populated downgrade before removing Block B history. Migrations 0010,
0011 and 0012 remain unchanged.

New Block B files:

- `packages/domain/execution.py`
- `packages/persistence/planning.py`
- `packages/persistence/execution.py`
- `alembic/versions/0013_sprint37_block_b.py`
- `tests/unit/test_block_b_contracts.py`
- `tests/integration/test_block_b_planning_execution.py`

Extended files include runtime domain/persistence models and exports, the Stage 5
successor-version calculation, migration head expectations, runtime schema
expectations and this checkpoint document.

### Block B concurrency and recovery coverage

Focused integration coverage verifies:

- identical concurrent plan publication converges to one immutable plan;
- different publication from the same stale snapshot is rejected;
- plan successor linkage points to the immediate predecessor;
- admitted trigger-to-plan routing consumes a trigger once;
- identical concurrent execution converges to one receipt and one session transition;
- worker retries link to the existing educational execution;
- stale session/graph/topic/frame/planning dependencies reject execution;
- changed execution input conflicts under one execution identity;
- executor failure is durably terminal and does not transition the session;
- successful receipt and session transition commit together;
- receipt/transition provenance retains plan and execution identities.

Logical exactly-once semantics are durable, not physical process exactly-once:
the process may retry after a crash, but a committed execution receipt is returned
and no second educational execution is created.

### Block B verification

The final executed verification record is:

| Command/check | Actual final result |
| --- | --- |
| `make test` | **403 passed, 159 skipped, one warning** |
| `make check` | Ruff passed; strict mypy **71 package files** passed; **7 import contracts** kept; pytest **403 passed / 159 skipped / one warning** |
| `make integration` | **162 passed, zero skipped, one warning**, 211.16 seconds |
| Focused Block B unit contracts | **3 passed**, one warning |
| Focused Block B live planning/execution tests | **8 passed**, one warning |
| Focused migration/runtime schema checks after the Block B migration | **4 passed**, one warning |
| Compose configuration checks | Passed for mock and isolated test Compose files |
| `git diff --check` and new/untracked-file whitespace checks | Passed |

The only warning remains Starlette TestClient's deprecated
`anyio.abc.BlockingPortal` alias. No real LLM, paid API or external cloud service
was used. All live tests used disposable fixture-owned services/databases.

**Stages 6–7 complete. Block C (Stages 8–10) is implemented and is being
verified; Stage 11 remains pending.**

## Block C: durable remediation, diagnostics, review and recovery hardening

### Stage 8: remediation lifecycle and escalation

`packages/domain/remediation.py` contains the pure one-rung-per-exhaustion
evaluator. A progress delta meeting the configured threshold completes the frame;
an unsuccessful attempt below the rung budget continues the current rung. The
third below-threshold attempt exhausts only that rung, advances one applicable
strategy, resets the attempt count to zero and establishes the latest observed
mastery as a new baseline. The approved ladder is
`RETEACH_WITH_NEW_STRATEGY`, `TEACH_PREREQUISITE`, `ASK_USER`, optional
`ESCALATE_MODEL`, then `BLOCKED_NEEDS_HUMAN`.

`packages/persistence/remediation.py` owns caller-transactional frame push,
source-linked attempt recording, progress transition, blocked-event emission and
complete-frame return. Every frame attempt remains an immutable history row and
the composite operation journal returns the original attempt/frame/evaluation on
retry. Terminal blocked events are deterministic and non-terminal rung
exhaustion emits no blocked event. Frame push and return also have immutable
operation results so a retry cannot reopen a closed frame or pop it twice.

Observed mastery is checked against the authoritative persisted projection and
the source attempt timestamp. Worker attempts are not used as remediation
identities. The owning course is taken from the locked session, preserving event
scope and learner-first lock ordering.

### Stage 9: diagnostic reservation/completion, inference and review

`packages/domain/diagnostic.py` provides a deterministic result adapter without
content generation. `packages/persistence/diagnostic.py` reserves the already
selected deterministic inventory, enforces the run budget and question identity,
and advances reservations through `RESERVED → ATTEMPTED → ASSESSED`. Completion
reuses the existing source-linked evidence/mastery repository and confirmed
transitive prerequisite inference. The run completion repository remains the
only operation that closes the diagnostic run.

Diagnostic candidates retain deterministic ordering, at most two question
versions per concept and the existing total budget. Full-credit answers may carry
deduplicated confirmed prerequisite provenance; partial and incorrect answers
carry no positive inferred contribution. No source question, attempt, evidence,
graph edge or answer is fabricated.

`packages/persistence/review_runtime.py` wraps the existing due-cycle repository
and normal evidence application. Candidate schedule-cycle identity and reason
ordering are retained in the durable due event. A retry can apply the original
review after the schedule has advanced, while changed candidate material
conflicts. `REVIEW_DUE` remains non-impact.

### Stage 10: adaptive-loop recovery and observability

Plan publication now recovers an existing immutable operation result before
freshness revalidation, while still comparing detached snapshot material so a
changed request conflicts. Terminal educational execution retries retain their
receipt and reject changed completion data. Worker lease/attempt identities stay
separate from domain receipts. `RuntimeObservation` and `observe_runtime()`
provide identifier-only structured observations for operation/outcome, learner,
course, session, source, execution, worker and error identifiers.

The recovery matrix covers rollback before commit, lost response after commit,
changed requests, stale session/graph/projection/frame dependencies, concurrent
first insertion, cooldown/trigger ownership, terminal retries and worker lease
recovery. Domain receipts and immutable operation journals are authoritative;
generic worker completion is not proof of educational execution.

### Block C files and migrations

Added implementation and coverage files:

- `packages/domain/diagnostic.py`
- `packages/domain/observability.py`
- `packages/domain/remediation.py`
- `packages/persistence/diagnostic.py`
- `packages/persistence/observability.py`
- `packages/persistence/remediation.py`
- `packages/persistence/review_runtime.py`
- `tests/unit/test_remediation_runtime.py`
- `tests/integration/test_block_c_runtime.py`
- `docs/decisions/0030-block-c-adaptive-loop-hardening.md`

Modified runtime/planner, exports, scheduling candidate provenance, worker-facing
observability and this document. No additive migration was necessary. Historical
migrations 0010–0013 remain byte-for-byte unchanged and the migration head
remains `0013_sprint37_block_b`.

### Block C verification record

Focused Block C remediation unit coverage includes the eight required per-rung
exhaustion regressions; focused disposable live coverage exercises frame
push/attempt retry and diagnostic reservation/assessment/run completion. The
worker retry repository also uses one PostgreSQL clock-derived deadline after
event append so its retry deadline remains after the final ORM update timestamp.

| Command/check | Actual final result |
| --- | --- |
| `make test` | **414 passed, 161 skipped, one warning** |
| `make check` | Ruff passed; strict mypy **78 package files** passed; **7 import contracts** kept; pytest **414 passed / 161 skipped / one warning** |
| `make integration` | **163 passed, 1 failed, zero skipped, one warning** on the final full attempt; the isolated worker file passed **26/26**, the extraction-plus-worker sequence passed **45/45**, and Block C live coverage passed **2/2** |
| `docker compose --profile mock config --quiet` | Passed |
| `docker compose --env-file /dev/null -f infra/compose/test.yml config --quiet` | Passed |
| `git diff --check` and Block C touched/new-file whitespace checks | Passed |
| migration head | `0013_sprint37_block_b` |

The full integration warning is an intermittent existing worker harness failure
in `test_handler_outcomes[error2-0-FAILED-PERMANENT_FAILURE]`: after the full
suite, `Worker.execute()` logged `worker_state_write_failed` and the disposable
job remained `RUNNING`; the same worker file and preceding extraction/worker
sequence pass independently. This is recorded as the remaining verification
warning rather than counted as a passing full integration run.

**Stages 8–10 complete. Stage 11 final acceptance is recorded below.**

## Stage 11: final acceptance, integration and audit

Stage 11 added no product features and did not change the approved Sprint
3.4/3.5/3.6 policies, runtime identities, migrations or architecture. A fresh
deterministic acceptance scenario in
`tests/integration/test_stage11_acceptance.py` proves:

```text
persisted outcome/mastery
  -> material trigger and durable admission
  -> authoritative snapshot
  -> pure planner and immutable plan publication
  -> authorized educational execution
  -> receipt and worker-attempt link
  -> event-linked session transition
```

The scenario audits source, trigger, plan, educational execution and worker
attempt identities and verifies their durable provenance links. Existing Block A,
Block B, Block C, Sprint 3.5, Sprint 3.7 alignment and worker suites provide the
retry/lost-response, concurrency, remediation ladder, diagnostic, review,
planner precedence, freshness, transaction, migration and worker/domain-boundary
acceptance coverage. Migration tests run only against fixture-created databases;
the development database and Docker volumes are not touched.

### Fresh Stage 11 verification

| Command/check | Actual result |
| --- | --- |
| `make integration` | **165 passed, zero failed, zero skipped, one warning** |
| `make test` | **414 passed, 162 skipped, one warning** |
| `make check` | Ruff passed; strict mypy **78 package files** passed; **7 import contracts** passed; pytest **414 passed / 162 skipped / one warning** |
| `docker compose --profile mock config --quiet` | Passed |
| `docker compose --env-file /dev/null -f infra/compose/test.yml config --quiet` | Passed |
| `uv run --locked alembic heads` | `0013_sprint37_block_b (head)` |
| `git diff --check` | Passed |

The only warning remains Starlette's existing deprecated
`anyio.abc.BlockingPortal` alias. Stage 11 did not add a migration, modify
protected source documents, stage files, create commits, access Windows paths,
reset a development database or delete Docker volumes. Phase 4+ work remains
deferred.

**Sprint 3.7 COMPLETE. Stages 1–11 verified. No commits or staging performed.**
