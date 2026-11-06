# Sprint 3.7 assessment: adaptive closed-loop runtime

## Status and assessment boundary

**READ-ONLY ASSESSMENT COMPLETE; IMPLEMENTATION NOT AUTHORIZED.** The owner
authorized continuation after the initial due-event conflict was reported. That
conflict remains an **UNRESOLVED BASELINE DEFECT**; continuing the assessment does
not resolve it or approve a fix. Sprint 3.7's runtime is not implemented.

**Conclusion:** the deterministic components exist, but the durable adaptive
closed loop does not. Authoritative outcome ingestion, material-trigger accounting,
coherent snapshot assembly, session/plan/frame persistence, bounded remediation
and recoverably idempotent execution need an explicitly approved runtime slice.

Sprint 3.6 remains the accepted, verified baseline. Its previously executed test,
check and 94-test integration results are not new results from this assessment.
No implementation, test, migration, schema or protected policy file was changed.
No tests, Docker commands or database operations were run for this assessment.

All project inspection and the sole documentation addition are in
`/home/smsav/projects/AAAv3`. `AAA_v3_COMPLETE_BUILD_PLAN.md` and `AGENTS.md` are
absent; `AAA_v3_BUILD_SPEC.md` v3.2 and `agents.md` are available.

### Evidence and source hierarchy

- Build spec v3.2 §§3.2, 6.4–6.5 and 12 supplies the runtime obligations.
- Finalized Sprint 3.4/3.5 policies and accepted ADRs govern existing components.
  ADR 0025 preserves build-spec planner precedence; ADR 0026 leaves authoritative
  assembly and execution outside the pure planner.
- **Source-confirmed** means the stated branch, field or missing wiring was
  inspected. **Conditional risk** means the source exposes a failure window, but
  its concurrent/database manifestation was not executed in this assessment.
- Proposed scope, transaction designs, identities and policy answers below are
  recommendations/questions for approval, not changes to approved semantics.

## BASELINE DEFECT — POLICY/IMPLEMENTATION ALIGNMENT REQUIRED

**Status: UNRESOLVED BASELINE DEFECT.** This is an implementation approval gate,
not a remaining blocker to the owner-authorized read-only assessment.

### Required contract

- Build spec §0 rule 8 requires every state-changing operation to be idempotent.
- Build spec §12.4 requires operations to be safe to retry and repeated events
  to preserve database state.
- Finalized Sprint 3.5 policy F,
  `docs/SPRINT_3_5_POLICY_DECISIONS.md:283–337`, defines an idempotent durable
  `REVIEW_DUE` event. Repeating a calculation with identical source state keeps
  the same schedule-cycle key. Different immutable content under an existing key
  is a conflict; unique identifiers prevent duplicate rows.

### Current implementation

1. `select_persisted_review_candidates()` reads active schedules and projection
   heads/revisions, checks some freshness facts, decays to supplied `as_of`, and
   returns at most three ranked candidates. Active remediation suppresses them
   (`review_schedule.py:382–472`; `mastery/scheduling.py:191–271`).
2. `process_due_reviews()` (`review_schedule.py:211–248`) reads schedules again,
   pairs each selected candidate with its schedule and calls `emit_review_due()`
   with `occurred_at=as_of`. It passes no correlation ID and exposes no parameter
   for one.
3. `emit_review_due()` (`153–208`) locks the schedule, checks its cycle, writes
   current reasons, flushes, builds the payload, and derives key K with
   `review_due_idempotency_key(state)`. Its event ID is
   `uuid5(NAMESPACE_URL, K)`, but line 206 supplies `correlation_id or uuid4()`.
4. `insert_learning_event()` validates actor identity, queries K, and on an
   existing row requires exact logical-envelope equality
   (`learning_events.py:26–49,59–81`). A new insertion uses a nested savepoint;
   a concurrent unique-key collision also reaches the equality check (`101–123`).
5. All these effects belong to the caller transaction. There is no helper commit,
   due-consumed marker or schedule advancement that removes the unchanged eligible
   cycle from the next calculation. Mutable schedule reasons are not an execution
   receipt (`models.py:539–603`).

**Reachability:** the failing producer path is directly reachable by calling
`process_due_reviews()` with an eligible schedule. Repository Python searches
found only its definition and exports, not a production API, nightly scheduler or
worker caller. The production registry contains `syllabus_ingestion`,
`curriculum_draft`, and `graph_build` (`apps/worker/syllabus.py:136–144`). Thus this
is a confirmed callable-helper defect, not an observed production incident.

### Static counterexample

Given an eligible active schedule, an authenticated actor, a fresh projection,
and a fixed captured `as_of = T`:

```text
first process_due_reviews(learner, course, as_of=T, same actor)
    -> stable event ID E and cycle key K
    -> generated correlation R1
    -> transaction commits

retry process_due_reviews(learner, course, as_of=T, same actor)
    -> same schedule inputs, event ID E and key K
    -> new generated correlation R2
    -> existing-event equality requires R2 == R1
    -> differing UUIDs cause LearningEventConflictError
```

Independent generated UUIDs normally differ: the producer has no stable-correlation
guarantee. For differing R1/R2, the exception follows even with equal occurrence
time and payload. A transaction rolled back before the first insertion committed
has no durable existing event and is a different retry case. Empty/suppressed
selection also does not enter this branch.

### Exact envelope comparison under an unchanged cycle

The table assumes the same learner/course/concept, schedule/projection/supporting
source state and actor, and that the same concept remains selected on retry.

| Field | Identical `as_of=T` | Later `as_of=T2` without a new cycle |
| --- | --- | --- |
| Idempotency key and event ID | Same K and deterministic E | Same K and E; calculation time is not cycle material |
| Type, learner/course, actor ID/subject | Same | Same under the stated actor assumption |
| `correlation_id` through the wrapper | Regenerated UUID; not stable | Regenerated UUID; not stable |
| `occurred_at` | Same normalized UTC T | Different normalized UTC T2: definite immutable-field mismatch |
| Payload `stable_concept_id`, `schedule_cycle`, `graph_version_id`, `evidence_set_digest`, `due_at` | Same | Same for unchanged cycle inputs |
| Payload `projection_revision_id`, `supporting_evidence_ids`, `supporting_event_ids` | Same under unchanged source metadata | Same if metadata is unchanged; these fields are not all included in cycle material and can also drift independently |
| Payload `reasons` | Same | Can change as due time passes or decay crosses the threshold |
| `causation_id`, `versions`, schema/payload kind | Defaults remain `None`, `None`, v1 / `review_due` | Same defaults |
| DB `recorded_at` / `created_at` | First insertion's receipt times retained on exact replay | Retained on exact replay; receipt time is not a logical-match input |

Candidate decayed mastery, confidence and status can change with T2, but are
**not themselves fields in this producer's payload**. They influence eligibility,
ranking and reasons; a later selection may contain different concepts or no
candidate. Where a concept remains selected, time/reason drift still conflicts
with the first immutable event. A direct call with a different actor adds an
actor mismatch under the same K; supplying stable correlation alone does not
make cross-actor replay valid.

Cycle material (`mastery/scheduling.py:33–72`) hashes learner, course, concept,
graph, policy, successful-review evidence anchor, successful-or-first event anchor,
rung, due time and evidence-set digest. It omits calculation time, correlation,
actor, reasons and projection revision ID. For example, replaying the same
evidence at another projection time can create another revision without changing
that digest/cycle. Additional supporting concept events can also change payload
metadata without necessarily changing an anchor or cycle. These are separate
envelope-preservation hazards; they must not be hidden by fixing only correlation.

### Intended retry semantics and possible alignment approaches

Policy F intends one durable notification identity for unchanged schedule source
state, including repeated nightly calculations. A new learning/review anchor,
evidence digest, rung, due date, graph or policy can define a new cycle. Merely
arriving later is not a new cycle. Strict immutable conflicts remain errors.

**A stable correlation UUID can be derived from the existing cycle/key/event
identity without changing the cycle key's meaning.** Existing E is already
deterministic; a namespaced deterministic derivation from K is also technically
possible. Whether correlation denotes a cycle, a larger run, or the original
causal operation is an envelope-ownership decision. No derivation or namespace is
selected here. This addresses only correlation, not occurrence time, actor or
payload drift.

Options requiring explicit approval include preserving/reusing the first durable
envelope when recalculating an existing cycle, or persisting a cycle-notification
envelope before retries regenerate it. Either approach must validate the same
semantic cycle, reject genuinely conflicting source content, retain audit
provenance, and handle concurrent creation. There is no approved complete mapping
from existing cycle fields to every immutable notification field. Adding retry
time to K, ignoring mismatch fields, or overwriting the original event is not an
alignment solution authorized by this assessment.

Unique constraints prevent a second event row, but preventing duplicate rows is
not a successful idempotent replay of the due-processing operation. The caller's
retry can abort rather than return the already-durable notification. Do not
interpret this as permission to weaken immutable event equality, change the
schedule-cycle formula, add an artificial learning event, or mark the conflict
resolved.

**Evidence level:** static source inspection. No counterexample was executed
against PostgreSQL, and no regression test was added or run. The expected
exception follows directly from the producer's generated field and the writer's
explicit equality check.

### Existing coverage inspected

- `tests/integration/test_sprint35_runtime.py:66–130` checks grading-event schedule
  seeding, selection and a single non-impact due-event insertion. It does not
  exercise repeated due emission or `process_due_reviews()` retry.
- `tests/integration/test_identity_events_runtime.py:80–140` checks exact-envelope
  event retry and concurrent identical insertions. Those tests preserve the
  original event object and its correlation ID; they do not cover regenerating
  the producer envelope.

The prior green baseline is compatible with this uncovered producer retry path.

## 1. Current implemented state

The inventory covers domain/pure packages, persistence models and migrations
0001–0009, API registration, production worker registry/handlers, checkpoint
adapters and relevant component/recovery tests. Absence statements refer to this
checkout's inspected implementation and wiring.

| Area | Current evidence |
| --- | --- |
| Learning outcome to evidence | Domain question/answer/evidence contracts exist. `create_question_version()` and `create_attempt()` persist immutable source metadata. `apply_evidence()` accepts a caller-supplied graded `EvidenceInput`; it does not grade a raw learner answer. Sprint 3.5/3.6 documentation records no complete production answer-grading workflow. |
| Evidence to mastery | `packages/persistence/mastery.py:562–737` validates source context, records evidence, invokes chronological pure replay, writes projection revisions/heads, synchronizes schedules and marks application in the caller-owned transaction. |
| Grading event | Optional `concept_event` is checked against learner/course/concepts. An `ANSWER_GRADED` event must match source evidence and attempt IDs (`mastery.py:692–712`). Event production is not inferred from the event name or from a planner decision. |
| Duplicate evidence | Existing immutable evidence is compared for exact content and returned with `duplicate=True` before new event/replay/schedule work (`mastery.py:591–610`). The returned projection IDs are current heads, not a durable original plan/execution result. |
| Mastery reads | `get_current_projection(..., as_of=...)` returns a transient decayed projection; immutable revision history can be listed (`mastery.py:417–458`). |
| Review | Pure scheduling/selection, durable schedules and due-event helpers exist. No successful retry guarantee can be attributed to `process_due_reviews()` without resolving the conflict above. |
| Diagnostics | Pure scoring, bounded question selection, confirmed prerequisite inference and provenance construction exist in `packages/curriculum/diagnostics.py`. Selection receives an already-valid question inventory and detached diagnostic state. |
| Planning | Sprint 3.6 establishes frozen `PlanningState -> PlannerDecision`, canonical provenance and build-spec precedence. ADR 0026 explicitly leaves authoritative input assembly and execution to callers. |
| Jobs/events | Caller-owned event/job insertion and a PostgreSQL claim/heartbeat/finish/reaper framework exist. Job lifecycle state is not learner-session lifecycle state. |
| Session/runtime | No learning-session FSM/repository, durable learning-plan/version/frame store, runtime trigger evaluator, action executor or execution receipt was found. Detached planner facts and event enums do not supply those stores. |

`apps/api/main.py:51–63` registers health, jobs, documents, curriculum and graph
routers. No learning answer-submission/session/plan/directive route invokes the
mastery/planner seam. `packages/agents` contains curriculum generation only;
`packages/evalkit` contains only `__init__.py`. `Makefile` has no `sim` or `e2e`
target yet. These are implementation gaps relative to the broader build plan,
not evidence that an existing closed loop failed a new test.

The current relational learning stores are identity/events, immutable mastery
question/attempt/evidence/contribution/revision/head records, self-report assertions
and review schedules (`models.py:197–642`). No durable diagnostic-run, topic
learning-position, session, plan stack/version, remediation guard or execution
receipt table appears in models/migrations.

## 2. Existing reusable components

Reuse the following within their existing contracts; runtime composition belongs
outside the pure engines:

- The pure mastery engine and weight policy; do not change their mathematics.
- The deterministic planner and immutable decision/state contracts.
- Pure review selection and diagnostic candidate generation using authoritative
  inputs and captured time outside the planner.
- Confirmed graph vocabulary, causal-path validation, topological/descendant
  algorithms and immutable graph queries. `latest_graph()` is scoped to an exact
  curriculum revision (`graphs.py:362–370`); runtime must choose that revision
  authoritatively.
- Frozen topic/gate/directive/frame/diagnostic inputs and canonical planner
  decision/provenance serialization. Extend runtime-owned records rather than
  using mutable state inside the planner.
- The learning-event writer's strict logical-match checks and savepoint handling.
- `create_job_in_transaction()` (`packages/persistence/job_creation.py:42–120`),
  which commits neither the caller transaction nor a Redis wake-up and converges
  concurrent identical insertions through a savepoint and unique key.
- `JobRepository` (`packages/persistence/jobs.py`) and `Worker`
  (`apps/worker/runner.py`) for leased at-least-once jobs.
- Durable progress/SSE and disposable post-commit Redis notification patterns.
- Graph publication's explicit job-row ownership lock and final lease check
  (`graphs.py:71–80,218–311`) as a publication-fencing example.
- Attempt-isolated, revalidated bounded curriculum checkpoints as a design
  example, not as a learning-session storage adapter.

**Conditional reuse:** evidence/source repositories expose useful caller-owned
transactions, but duplicate follow-up reconciliation, concurrent first insertion,
projection freshness/time restoration and diagnostic inference require the checks
below. Concept-event persistence does not share all v1 writer protections. The
due producer/wrapper cannot be certified retry-safe until its baseline defect is
resolved through a separately authorized change. None of these qualifications
authorizes changing baseline mathematics, precedence or source provenance.

## 3. Missing capabilities

| Missing runtime capability | Required owned facts/effects |
| --- | --- |
| Authoritative outcome ingestion | Authenticated learner access, immutable answer/assessment source, trusted grader output, exact outcome/attempt identity and original response receipt |
| Material-trigger evaluator | Current topic window, qualifying weights/counts, prior/current WEAK transition, batch completion, directives, deferred triggers and per-student cooldown |
| Planning snapshot assembler | One captured time and coherent evidence/projection/event, confirmed graph/revision, topic/core/gate, selected candidates, session/frame/directive versions |
| Learning-session FSM | Durable state, legal transition table, event-linked transitions, pause/complete/resume and terminal ownership |
| Plans and publication | Plan/version, reasons, source events, diff, canonical decision, policy/version stamps, concurrency fence and duplicate publication identity |
| Execution dispatcher/receipts | Policy-outcome gate, authorized target/action mapping, exactly-once durable transition/job effects and result acknowledgement |
| Remediation stack and guards | Push/pop history, saved return target, completed learner attempts, progress baseline/delta, strategy/escalation rung, exhaustion/blocked facts |
| Diagnostic runtime | Durable run/budget/reservations/attempted inventory/assessed concepts/completion and legitimate inferred-contribution acceptance |
| Review runtime | Retry-safe notification ownership, nightly invocation, session-start warm-up consumption/reservation and current-graph revalidation |
| Simulator/observability | Hidden-state scenarios, loop/advance/invalid-action metrics, traceable outcome-to-plan/action history and baseline comparison |

The diagnostic selector uses a local remaining-budget counter while selecting
candidates; it does not persist reservations, decrement a durable run or mark
assessment completion. `DiagnosticState` bounds total/remaining items to 12 and
holds selected/attempted/assessed identities (`adaptation.py:188–213`). Reusing the
same detached run cannot guarantee that two workers reserve disjoint inventory.

## 4. Exact architectural seams and transaction map

### A. Outcome -> authoritative evidence/event

The trusted caller supplies graded correctness and immutable question/attempt
context to `packages.persistence.mastery.apply_evidence()`. Question metadata
storage is not itself a grader or proof that a client's reported correctness is
authoritative. Outcome ingestion/authentication and grading ownership must be
established before exposing this seam to learner input. `apply_evidence()` checks
actor/subject and course membership (`mastery.py:575–589`), but neither membership
nor an identity mapping proves delegation. `require_learner_access()` explicitly
requires self-access or separately verified delegation (`identity.py:38–52`); no
production learning caller wires that authorization yet. Correctness, grader facts
and weighting metadata must come from trusted validated sources, not client claims.

### B. Evidence -> mastery -> trigger

The application boundary is useful as a caller-owned transactional seam. It
does not call the planner, evaluate replan triggers or create a replan job.
Successful application alone is therefore not a complete closed-loop trigger.
Any future caller must account for the early duplicate return and avoid applying
prior/evidence mass again while reconciling missing durable follow-up work.

Build spec §6.5 already specifies:

| Trigger | Existing required/default behavior |
| --- | --- |
| Single wrong answer | Evidence only; no unconditional replan |
| Repeated failure | At least two incorrect graded items of weight >= 0.5 for the same concept in the current topic window, or entry into WEAK with confidence >= 0.3; invalidate segment/run planner |
| Quiz/check completion | Run planner on the completed batch |
| Strong performance | Quiz >= 0.9 with at least three items and satisfied gate; advancement allowed, later `LIKELY_KNOWN` needs confirmation |
| Curriculum edit | Graph diff/rebuild and plan invalidation |
| Nightly decay | Review-due processing |
| Directive | Immediate, bypass cooldown |
| Deadline change | Recompute pacing |

At most one new plan version per **60 seconds per student**, directives excepted
(`AAA_v3_BUILD_SPEC.md:336–349`). These thresholds/requirements are not approval
questions to reopen. Missing decisions concern exact window ownership/reset,
which accepted weight/partial/uncertain facts qualify, batch identity, atomic
cooldown accounting, and deferred-trigger delivery. A course-only cooldown would
not satisfy the specified student-wide cap across courses/sessions.

Outcome retries, event redelivery, historical replay and a read-time decay must
not automatically increment failure counts, create a new batch, consume another
directive or count as new learner remediation attempts. Trigger evaluation needs
before/after facts at a consistent time and source identity, not only the latest
already-decayed projection.

### C. Mastery -> fresh planning state

Current projection reads, review selection and diagnostic selection can supply
parts of a snapshot. Topic/core/gate results, authenticated directives, current
session/frame facts and authorized next targets remain caller-owned under ADR
0026. The planner does not turn a supplied freshness flag into independently
verified database truth.

The review selector checks head/revision availability, schedule versus revision
digest, and some graph mismatch facts. It does **not** recompute accepted-ledger
digest/count, compare evidence counts, or universally validate membership for
null/equal graph contexts (`review_schedule.py:395–462`). Policy H requires
recomputed digest/count plus current graph membership, not just equality between
two materialized values (`SPRINT_3_5_POLICY_DECISIONS.md:362–389`). This is a
source-confirmed freshness-contract gap; no stale-state reproduction was run.

The selector queries the highest published `version_number` for the course for
each schedule, without an exact current curriculum revision (`396–399`). The
graph repository's `latest_graph()` instead scopes to a revision. A runtime
assembler must resolve the authoritative revision/current graph once and use
consistent graph identity; it cannot assume a course-wide version number alone
establishes current lineage. Cross-revision ordering/ties require verification.

Replay's digest serializes the supplied evidence model objects and self-report
contributions, but not the independently supplied concept-event set or `as_of`
(`mastery/engine.py:330–409`). The persistence path supplies `EvidenceRecord`
subclasses, exposing the receipt/application-marker concern in §5. Concept events
affect review qualification/anchors; time affects decay. Runtime snapshot
provenance needs those facts and versions as well as the approved immutable-source
digest contract, without silently selecting a new formula.

Topic authorization, core-concept membership, deepest-first weak prerequisite
ranking, gate evaluation and next-topic order are assembler responsibilities.
Default topic gate remains minimum core mastery >= 0.70, each core concept
`n_direct >= 3`, latest quiz >= 0.6 (§6.4). Mean topic mastery or a self-report
alone cannot replace the gate. Missing projections/gates are explicit missing
state, not fabricated successes or zero-valued evidence.

### D. Event/job -> replanning

Durable learning events and generic transactional job creation are available.
`apply_evidence()` and the job-creation helper contain no replan router. No learning
event-to-runtime handler is wired in the production registry. A job's worker lease
serializes that job, not every event/plan for a learner. `JobProgressEvent` is
delivery/progress history, not a substitute for domain learning events or session
transitions.

The static event-to-follow-up-job mapping must participate in the initiating
transaction (§12.2). For deterministic L0 outcomes, mastery, replan check and
applicable planner/next-action work belong inside the submission transaction
(§3.2). An async-only replan job after committing the answer is not an equivalent
implementation of that specified path. LLM-dependent work remains bounded async
work; a deferred cooldown trigger still needs durable reconciliation ownership.

### E. Decision -> execution

`TEACH_CURRENT_TOPIC`, `REVIEW_DUE`, `DIAGNOSE`, prerequisite/remediation actions,
and terminal actions are domain decisions. The spec's action name is
`REVIEW_DUE`, not a separate `REVIEW` enum. Sprint 3.6 deliberately supplies no
executor; a decision alone creates neither teaching content nor assessment
inventory, frame mutation, session transition or completed topic.

| Decision family | Required executor ownership; currently absent |
| --- | --- |
| `TEACH_CURRENT_TOPIC`, `RETEACH_WITH_NEW_STRATEGY`, `TEACH_PREREQUISITE` | Authorized topic/concept/strategy, one content request, completion acknowledgement; prerequisite push records saved target exactly once |
| `PRACTICE_CONCEPT`, `GENERATE_MICRO_CHECK`, `GENERATE_QUIZ` | Valid inventory/batch and immutable source context, one reservation/request, completion-driven taught/checked/quiz facts |
| `REVIEW_DUE` | Session-start warm-up reservation/consumption, maximum three, frame suppression, revalidation, review-marked assessment and result acknowledgement |
| `DIAGNOSE` | Run/question reservation, remaining budget, completed-attempt/assessed markers, legitimate source-linked inference and completion event |
| `ADVANCE_TOPIC`, `RETURN_TO_TARGET` | Authorized next-topic transition or one frame pop/return, original target preserved, no repeated advancement on retry |
| `ASK_USER`, `PAUSE`, `COMPLETE` and policy outcomes | Durable confirmation/needs-state/pause/terminal result; no inferred completion from an empty candidate list |
| `SEARCH_MORE_CONTEXT`, `ESCALATE_MODEL` | Explicit authorized bounded adapter and applicable budget/fallback consent; enum existence alone supplies no handler |

`BLOCK` and `REQUIRE_CONFIRMATION` must gate educational execution. A blocked
decision may still have a durable audit/needs-state result; it must not fall
through into the proposed educational mutation. A confirmation receipt must link
to the exact still-valid request rather than treating a later retry as consent.
Canonical decision bytes/state digest are audit provenance, not a persisted
execution receipt or permission to execute twice.

### F. Remediation

`RemediationFrame` holds identity, target, return topic, completion, continuation,
evidence and confidence (`adaptation.py:290–302`). Planning proposes continuation
or `RETURN_TO_TARGET`; it does not push/pop or increment attempts. Even a complete
active frame suppresses reviews until the runtime performs the return/pop
(`planner/policy.py:233–272`). An unchanged frame repeats the same proposal.

Spec §6.4 fixes defaults `max_remediation_attempts=3`,
`min_progress_delta=0.05`: attempts >= maximum with smaller mastery delta exhausts
the rung. The ladder is `RETEACH_WITH_NEW_STRATEGY` -> deeper
`TEACH_PREREQUISITE` -> `ASK_USER` -> `ESCALATE_MODEL` if allowed ->
`BLOCKED_NEEDS_HUMAN`, emit `REMEDIATION_LOOP_BLOCKED`, and continue an independent
topic. These are existing obligations, not permission to change precedence.

The durable frame/guard must own learner-attempt identity, progress measurement
baseline/time, exhausted targets, rung advancement/reset, saved return target,
blocked status and independent-topic eligibility. Transport retries/job attempts
must not count as learner attempts or independently exhaust more rungs. Exact
progress/window/reset and guard integration semantics require owner approval;
the planner must remain pure and must not gain DB/clock/ranking/executor behavior.

## 5. Risks and unresolved baseline seams

| Finding | Evidence level and consequence |
| --- | --- |
| Due notification retry | **Unresolved baseline defect**, source-confirmed above; wrapper regeneration conflicts with durable immutable envelope |
| Projection freshness | Source-confirmed minimum-policy gap in §4C; schedule/revision agreement cannot establish accepted-ledger freshness |
| Repeated proposals | Source-confirmed missing executor/receipt/guard; unchanged input never advances the durable loop by itself |
| Concurrent mastery replay | Conditional race: source ledger is read before head locks; two replay snapshots can omit each other's accepted outcome and later overwrite heads |
| Concurrent first insertion | Question/attempt source records, evidence, self-report, head and schedule insert paths use flush/uniqueness without the v1 writer's nested-savepoint convergence protocol; collision/retry behavior is unverified |
| Duplicate follow-up omission | Source-confirmed early duplicate evidence return skips optional grading event and replay/schedule work; adding follow-ups later does not happen automatically |
| v2 event equality/insertion | Source-confirmed narrower duplicate equality and no nested insert recovery; envelope consistency and concurrent identical insertion require verification |
| Diagnostic persistence | Source-confirmed role mismatch for differently tagged source questions; pure inference output is not a generally accepted persistence input |
| Mixed/stale snapshot | Conditional concurrency risk across separate reads and between selection, schedule reread/lock, planning and publication |
| Cooldown/guard accounting | Missing runtime ownership; simultaneous events or retries can multiply versions/counts if naively composed |
| Job/domain publication gap | Source-confirmed separate transactions in existing pipelines; generic finish fencing alone cannot authorize new learning mutations |
| Replay digest input shape | Source-confirmed inclusion of receipt/application fields from runtime EvidenceRecord inputs; immutable-source digest stability needs targeted verification |

### Replay digest and application-marker ordering

`_evidence_from_row()` returns `EvidenceRecord` including `recorded_at` and
`applied_at` (`mastery.py:163–199`; `domain/mastery.py:135–146`). The runtime passes
those records directly to pure replay (`mastery.py:686–714`). `_digest()` calls
each object's `model_dump(mode="json")` without excluding those additional
subclass fields (`engine.py:330–343`). Thus the persistence path's digest includes
receipt/application fields that pure `EvidenceInput` fixtures do not have.

For newly accepted evidence, the record is read/replayed while `applied_at` is
still null; projections/schedules receive that digest, and only afterward does
the caller set `row.applied_at` (`mastery.py:714–729`). Recomputing the same
accepted records after application can therefore produce a different digest
without any new immutable learning snapshot. This can undermine a future
authoritative freshness check and make cycle identities depend indirectly on
application metadata.

The input types, serialization and ordering are source-confirmed; no live digest
comparison was executed. Sprint 3.4 defines the digest over immutable evidence
IDs/snapshot identities (`SPRINT_3_4_POLICY_DECISIONS.md:719–745`), and Sprint 3.5
treats receipt/application times as audit metadata (policy F and consistency
table at `SPRINT_3_5_POLICY_DECISIONS.md:668–669`). Targeted verification/alignment
is required before reusing this digest as an authoritative runtime fingerprint.
No digest/key change or receipt-equality relaxation is selected here.

### Projection timestamp restoration

Pure replay decays each concept to `ReplayResult.as_of` and moves its state's
time to that instant (`engine.py:92–113,389–408`). `_persist_replay()` stores those
already-decayed alpha/beta values alongside `as_of` and course-ledger
`max_occurred_at` (`mastery.py:498–526`). `_projection_domain()` restores the state
time from **`max_occurred_at`, not `as_of`** (`386–401`), then current-projection
reads and review selection decay again.

This timestamp mismatch is source-confirmed. If the ledger maximum T precedes
projection time S, reading at S can apply another T-to-S decay to values already
projected to S. Larger late-replay/read delays make the issue material. Its live
numeric/gate impact was not tested here. It is an unresolved baseline integration
concern requiring targeted reproduction/alignment before certifying snapshot
assembly; changing the forgetting formula is not proposed.

### Diagnostic inference acceptance

`inferred_evidence_for_prerequisite()` (`diagnostics.py:145–170`) derives one
source-attempt/prerequisite identity, sets `INFERRED`, and replaces roles with one
prerequisite while retaining source question/attempt identities. Persistence
requires exact role equality with that source question version and matching
review markers (`mastery.py:621–636,652–653`). For a question with different roles,
that output is rejected; the unit helper test does not demonstrate successful
live acceptance of the inferred prerequisite ledger.

An approved solution must preserve original source attempt/question/evidence,
historical graph and confirmed edge provenance and one contribution per source
attempt/prerequisite. Potential seams include a separately validated inferred
contribution record attached to accepted source evidence, or an explicitly
validated inferred-snapshot acceptance path. Neither is selected. Fabricating a
new attempt/question version or mutating source roles to bypass validation is
not legitimate integration. Inferred evidence remains excluded from direct
counts and MASTERED qualification under the accepted policy.

### Additional event/idempotency hazards

- v1 logical match includes causation, correlation and versions. v2 duplicate
  match (`concept_events.py:117–127`) omits those three fields despite persisting
  them (`143–150`). A changed envelope can therefore return an existing v2 row
  without validating those changes. This is a source-confirmed difference, not
  permission to weaken v1 or to declare v2's full retry contract satisfied.
- v2 insertion flushes directly without a nested-savepoint/unique-conflict
  reconciliation branch (`152–167`). Concurrent identical writes need their own
  regression coverage and approved convergence treatment.
- `apply_evidence()` duplicate return supplies **current** projection heads, not
  the original outcome result; interleaved later evidence can change that result.
  It returns before checking a newly supplied `concept_event` or repairing missing
  follow-ups. Do not turn `duplicate=True` into a new trigger/learner attempt.
- The replay digest does not fingerprint concept events; direct event insertion
  can change qualification inputs without an automatic replay/plan invalidation.
  An accepted runtime must track event changes and reconcile projections.
- Due cycle validation alone does not validate every candidate/projection/support
  field against the currently locked row. Selection and schedule reread can mix
  versions; original envelope and current eligibility need separate validation.
- Policy F requests anchor-event provenance in the payload. The producer has
  supporting event IDs and a hashed cycle but no explicit anchor-event field
  (`review_schedule.py:176–194`); explicit payload alignment remains to be reviewed.

These findings remain recorded concerns, not fixes. None was reproduced with
new tests/database operations during this assessment.

## 6. Idempotency requirements

Retry safety is already required by §12.4. Runtime must distinguish exact replay,
conflicting immutable reuse and genuinely new accepted sources/operations.

| Boundary | Required retry invariant |
| --- | --- |
| Answer/outcome/attempt | Original accepted source and grading result reused; conflicting body/key rejected; learner authorization rechecked |
| Evidence/event/projection/schedule | No duplicate mass or qualifying occurrence; original event envelope preserved; current follow-up state reconciled without inventing a new outcome |
| Material trigger/window | Each accepted source counted once; batch completion/directive/transition-to-WEAK identity retained; cooldown replay does not publish another version |
| Plan publication | Same logical publication returns original immutable decision/version/diff; changed current state is a new validated publication, not a mutation of the old one |
| Action execution | One receipt owns transition, target, inventory reservation, frame mutation and child jobs; retry returns/reconciles that execution rather than dispatching again |
| Remediation | Push/pop/learner-attempt completion/rung exhaustion each consumed once; job claim attempts do not increment learner counters |
| Diagnostic | Run reservation/completion and source-attempt/prerequisite inference deduplicated; retries neither spend budget again nor increase direct counts |
| Due notification/review execution | Existing approved cycle notification identity retained; notification replay is distinct from a new session review reservation or completed review evidence |

A unique row constraint is the duplicate guard, not the complete application
retry protocol. Concurrent insertion needs conflict isolation and an exact
semantic match or retry/reload rule. Conflicting events must not be swallowed as
successful replay. A canonical state digest is not an execution identity; worker
attempt IDs are lease fences, not new educational-operation identities.

The proposed receipt links original outcome/source events, decision/plan version,
session/frame/directive version, execution identity, emitted events/jobs and
completion result. Its schema and key formulas require approval. If a legacy
accepted outcome has no receipt/follow-ups, recovery must explicitly reconcile
that state; bypassing the duplicate evidence check would reapply mass.

## 7. Concurrency requirements

`ownership()` in `packages/persistence/jobs.py:48–55` fences job ID, worker ID, attempt,
RUNNING status and lease expiry. Claims use `FOR UPDATE SKIP LOCKED`; separate
jobs can execute concurrently. Runtime publication must additionally account for
learner/session/plan/graph versions and coherent evidence snapshots.

Required invariants:

1. Serialize or validate authoritative learner/course replay across evidence,
   self-report and concept-event changes. Head locks taken after computing an
   incomplete replay cannot retroactively make its source set complete.
2. Handle absent projection/head/schedule/session/receipt rows explicitly; locking
   a missing row locks no row. Define deterministic lock ordering for overlapping
   concept sets and bounded retries for conflicts.
3. Capture one graph/revision, projection/evidence/event context, session/frame
   version, topic/batch position, directives and time for the decision. Revalidate
   all publication dependencies if work occurs outside the originating transaction.
4. Atomically enforce plan-version allocation, student-wide cooldown and directive
   exceptions across simultaneous sessions/courses. Coalesce/defer material sources
   durably instead of losing them while cooldown is active.
5. Atomically reserve diagnostic/review inventory, acknowledge results and apply
   frame pushes/pops/guard counters; two sessions must not both consume one source
   operation or return the same frame twice.
6. A worker publishing a result must prove current job ownership **and** current
   domain/session/plan/graph eligibility. A replaced attempt or stale decision
   cannot overwrite a newer plan, resume a paused session or reapply a directive.

Lock scope/ordering, absent-key initialization, isolation and snapshot fencing
remain design decisions. Row locks, advisory locks or optimistic revision checks
are possible mechanisms, not choices made here. `Database.session()` only yields
a session (`database.py:40–45`); it supplies neither automatic commit nor an
application serialization protocol.

## 8. Failure/retry behavior inspected

- Worker heartbeat/ownership loss cancels the handler, stops further claims and
  avoids another state write from the uncertain attempt (`runner.py:124–134`,
  `215–221`). ADR 0019 defines delivery as at least once.
- Graceful shutdown and explicit cancellation have different outcomes.
- Uncertain completion leaves work to lease recovery rather than making a
  contradictory completion/failure write (`runner.py:251–254`).
- The reaper reschedules or exhausts expired jobs (`jobs.py:233–281`).
- A generic fenced `finish()` cannot automatically protect arbitrary domain
  writes performed earlier by a handler; a future runtime publication boundary
  needs its own ownership/version checks.
- Resume from a bounded job checkpoint is not recovery of a learner's session,
  plan stack or previously executed decision.

### Existing publication/checkpoint boundaries

- `draft_checkpointer()` uses a **separate autocommit psycopg connection** in
  `curriculum_checkpoints` (`checkpoints.py:14–24`). It is not in the SQLAlchemy
  domain transaction.
- `generate_sections()` isolates threads as `draft:{draft_id}:{attempt}`, loads
  and validates an earlier prefix, and runs a bounded graph
  (`agents/curriculum.py:20–69`). A checkpoint proves validated pipeline progress,
  not a committed session transition, grading result, decision or execution receipt.
- `DraftHandler` writes a validated immutable object-store artifact before the
  runner's separate fenced `finish()` (`draft.py:81–124`; `runner.py:244–254`).
  An artifact can exist without a successful job result; replacement work must
  validate/reuse it. This pattern is not atomic learning-plan publication.
- `GraphHandler` writes its artifact, then commits graph rows and `GRAPH_BUILT`
  together under an explicit ownership fence (`graph.py:88–106`;
  `graphs.py:218–311`). Generic job success is later. A crash after domain commit
  must converge through existing graph identity rather than regenerate the event.
- **Conditional child-ordering risk:** syllabus execution commits its draft child
  via `enqueue_draft_for_source()` **before** returning for generic parent finish
  (`syllabus.py:119–133`; `drafts.py:48–69`). Another worker can claim the child
  while the parent is still RUNNING. `extraction_source()` requires SUCCEEDED
  (`drafts.py:20–28`), and `DraftHandler` maps that source error to a non-retryable
  `HandlerFailure` (`draft.py:106–107`; `handlers.py:44–48`). The ordering is
  source-confirmed; the concurrent failure window was not reproduced here. Do
  not copy this child-enqueue boundary as proof of §12.2-safe learning routing.

ADR 0009 keeps LangGraph inside bounded individual jobs; PostgreSQL Session FSM +
Planner owns the macro loop. New educational pipelines must preserve that boundary.

### Required runtime recovery matrix

| Failure window | Required durable recovery |
| --- | --- |
| Before outcome transaction commits | No partial evidence/plan/transition/follow-up jobs; same request can retry |
| Commit succeeds but response/wake-up is lost | Load original outcome/execution receipt; PG polling recovers jobs; no new version/mass |
| Trigger suppressed by cooldown | Preserve pending source identities and a recoverable deadline/eligibility record |
| Content/checkpoint saved before domain publication | Validate identity/context and current lease; orphan/partial content never implies action completion |
| Domain/action publication succeeds, generic job finish fails | Receipt/event/version reconciles completed effects; replacement delivery must not repeat frame mutation or dispatch |
| Lease expires/heartbeat fails or stale handler continues | Publication fails ownership/domain fences; replacement reads durable state/checkpoints |
| Session pauses, completes, or graph changes while work is pending | Revalidate target/context; record stale/superseded outcome without executing obsolete work |
| Retry budget exhausts | Durable failure/needs-state plus recoverable session result; no silent loop or invented success |

### Existing tests and coverage limits

Read, but not run for this assessment:

- `test_worker_runtime.py` covers claim contention, leases, reaping, cancellation,
  polling/duplicate wake-ups, graceful shutdown and process crash. Its completion
  DB-failure test aborts after the fenced update before commit and verifies later
  recovery (`247–286`). These tests establish job mechanics, not new domain effects.
- `test_curriculum_draft.py:132–193` covers artifact/checkpoint reuse, provider
  failure and stale-attempt completion rejection. It does not prove atomic macro
  session/frame/plan recovery or safe early child eligibility.
- `test_mastery_runtime.py:164–206` covers sequential exact evidence replay and
  conflict/future rejection, not overlapping full learner/course replay.
- `test_sprint35_runtime.py:66–130` inserts one due event; it does not retry the
  wrapper or exercise later-time envelope regeneration.
- `test_planner_boundary.py` consumes real selector outputs and verifies no planner
  writes. Its diagnostic boundary does not persist inferred prerequisite evidence.

No existing test path establishes the complete adaptive closed-loop guarantees.

## 9. Proposed Sprint 3.7 scope — not approved

**Proposed deliverable:** a deterministic, durable vertical runtime slice proving
accepted outcome -> mastery -> material trigger -> fresh planning state -> plan
publication -> one authorized execution/transition -> next accepted outcome,
including bounded remediation and return. Keep existing pure planner/mastery,
review formulas and confirmed graph semantics unchanged.

Proposed included work, subject to explicit approval:

1. Runtime contracts plus versioned trigger/guard configuration; durable session,
   topic/batch, plan/version, frame/guard, diagnostic, directive and receipt facts
   needed by the approved slice. Exact schema/migrations are not selected here.
2. A trusted deterministic outcome boundary with learner authorization, immutable
   source context and original result receipt. Decide whether the first slice is
   an internal service with controlled fixtures or includes a minimal production
   L0 grading/submission adapter; those are different admission scopes.
3. Pure material-trigger/guard evaluation outside the planner, durable accounting,
   cooldown/deferred-trigger reconciliation and authoritative snapshot assembly.
4. Transactional runtime orchestration/publication and an explicit action adapter
   registry. Fake deterministic content/assessment adapters can prove mechanics
   only if authorized; they do not constitute production tutoring or grading.
5. Frame push -> practice/reassessment -> return, plateau exhaustion, review
   warm-up suppression/consumption, bounded diagnostics and valid inference.
6. Fault/concurrency/idempotency tests, decision/transition traceability and a
   deterministic simulator subset with baseline comparison.

Baseline alignment is a prerequisite to integrating the affected helpers: due
retry, accepted-ledger freshness/digest stability, projection timestamp restoration,
inference acceptance and any relied-on event/child-publication path need targeted
verified treatment. The owner must authorize those changes separately or within an
explicitly revised Sprint 3.7 scope; this document applies none of them.

Build spec Phase 3 includes triggers, plan stack, guard and simulator; the full
Session FSM, APIs/frontend, production teaching/assessment and §16.5 flow span
later phases. Sprint 3.7's title cannot silently admit all Phase 6–8 product work.
Conversely, a fixture-backed internal slice must not be reported as satisfying
the complete mandatory upload-to-streamed-lesson-to-remediation UI regression.

## 10. Explicit out-of-scope items for this assessment

- All implementation changes, migrations/schema changes and new APIs/workers.
- Changes to planner precedence/behavior, mastery/review formulas or graph rules.
- New learning events/evidence, database operations, Docker lifecycle operations
  or external model calls.
- Resolving policy questions, silently weakening invariants or claiming Sprint
  3.7/the adaptive closed loop is implemented.

Proposed exclusions from the first runtime slice, requiring scope approval:
production LLM lesson/question/rubric pipelines, retrieval/model gateway expansion,
frontend/dashboard/session SSE product flows, broad public API families, cloud
fallback implementation, code sandbox, Kubernetes and model training. A guard can
record a bounded escalation/needs-state outcome without inventing a provider.
The spec's opt-in constraints still apply to any later real escalation.

No mastery/review formula replacement, planner precedence change, automatic graph
lineage transfer, giant macro LangGraph, new broker or paid dependency is proposed.

## 11. Proposed implementation sequence and acceptance evidence

No step below is approved or started:

1. **Approve scope/policy gates.** Select the first outcome/action boundary, durable
   ownership model, trigger/guard interpretations, snapshot/concurrency protocol,
   identities and baseline-alignment scope. Record approved decisions without
   rewriting protected baseline policies.
2. **Verify/align relied-on baseline seams.** Targeted regression/reproduction for
   due replay, freshness/time restoration, inference acceptance and event/publication
   concurrency. Resolve confirmed defects only within authorized fix scope.
3. **Add durable contracts/stores.** Legal event-linked FSM transitions, immutable
   plans/versions/diffs, frame/guard history, diagnostic reservations, directives,
   accepted outcome/execution receipts and publication fences; migrate/test safely.
4. **Add pure triggers and guards.** Versioned defaults, accepted-source counting,
   window/batch/WEAK facts, cooldown exceptions/deferred accounting and bounded
   rung exhaustion. Keep planner purity and precedence tests intact.
5. **Build authoritative snapshot assembly.** Capture time/current graph once,
   verify accepted-source freshness, evaluate gates/rank candidates outside the
   planner, and prove publication rejects stale dependencies.
6. **Close deterministic transaction path.** Outcome/evidence/event/replay/schedule,
   trigger/planner/plan, legal transition/receipt and follow-up jobs atomically;
   post-commit Redis notification only. Wire approved async adapters with explicit
   publication fencing and crash reconciliation.
7. **Exercise closed-loop scenarios and simulation.** Hidden weak prerequisite,
   successful return/advancement, plateau escalation, forgetter/review and noisy
   outcomes. Expose traceable decisions/results and compare steps-to-gate with
   fixed-order/threshold baselines.
8. **Run approved acceptance checks and report limits.** Appropriate focused
   unit/live integration tests, `make check`, `make integration`, approved simulator
   command and fault scenarios. Full §16.5/`make e2e` acceptance remains required
   when its teaching/assessment/UI dependencies are actually implemented.

### Proposed tests (not added or run)

| Layer | Meaningful required cases |
| --- | --- |
| Baseline seams | Same/later-time wrapper due replay, reason/metadata drift, concurrent first emission, strict conflicts, non-impact associations; replay/read at equal projection time; digest before/after applied marker; accepted-ledger freshness; real inferred persistence |
| Triggers | One wrong answer no replan; qualifying repeated failure/window reset; WEAK transition; check/quiz batch once; strong gate; student-wide 60-second boundary; directive bypass; deferred sources survive restart |
| Snapshot/planner boundary | Missing/stale projections, changed graph/revision, exact topic core gate, deterministic candidate ties, no I/O/math/ranking moved into planner |
| Sessions/plans/execution | Legal/illegal transitions, one plan/receipt/job set on replay, conflicting source rejection, mandatory skip confirmation, pause/complete, stale confirmation, no action from BLOCK |
| Remediation | Hidden prerequisite push, persisted attempt/progress, completion/pop/return exactly once, maximum-attempt exhaustion per rung, no retry-count inflation, blocked independent-topic handling |
| Diagnostics/reviews | Concurrent reservations, exhausted budget, immutable historical inference path, no fabricated source attempt, self-report does not clear pending/gate, session-start max-three and frame suppression |
| Concurrency/recovery | Same/different outcome races, absent heads, simultaneous plans/directives/sessions/courses, lease replacement, checkpoint-before-publication and publication-before-finish crashes, response loss and Redis loss |
| Simulator | Hidden weak prerequisite reaches TEACH_PREREQUISITE then RETURN_TO_TARGET; plateau terminates; forgetter reviews; loop/invalid-action rate zero; measure premature advance and steps-to-gate versus baselines |

Simulation needs a real hidden-state learning/guess/slip/forgetting model, bounded
runs and measured metrics (§16.3), not a hard-coded list of expected planner
actions. No performance/learning-value claims follow from the current component
suite alone.

## 12. Policy questions requiring approval before implementation

The owner must approve answers before implementation:

1. **Admission:** internal accepted-outcome service/fixtures or minimal production
   deterministic grader/submission adapter? Which action families/adapters and
   simulator/API artifacts define completion of this sprint?
2. **Durable ownership:** session/topic/batch, plan/version, frame/guard, diagnostic,
   directive and receipt records; how are completion acknowledgements, mandatory
   skip confirmation, consumption, saved returns and blocked topics represented?
3. **Trigger interpretation:** exact topic-window boundaries/reset, qualifying
   weight definition and partial/uncertain/inferred eligibility, batch identity,
   late outcomes/WEAK transitions, cooldown coalescing and deferred delivery.
   Numeric defaults and the per-student/directive rules remain specified.
4. **Remediation interpretation:** what completed learner work counts as an
   attempt, which baseline/time defines progress, resets on progress/rung/topic,
   target exhaustion, permitted deeper prerequisite choice, guard integration
   without planner changes, confirmation waits and independent-topic fallback?
5. **Snapshot/concurrency:** authoritative current revision/graph, captured time,
   accepted evidence/prior/event freshness, serialization across sessions/courses,
   publication revalidation, absent-row races and stale-result disposition.
6. **Baseline fix scope:** authorization and acceptance criteria for due-event
   envelope preservation and other relied-on freshness/time/event/publication
   concerns. The due key and strict immutable-event semantics remain unchanged.
7. **Envelope ownership:** scheduled actor authorization, occurrence/causal time,
   cycle versus run correlation, original payload/anchor provenance and exact
   retry behavior when invocation metadata changes. Deterministic correlation is
   feasible but not a complete selected fix.
8. **Diagnostic acceptance:** legitimate inferred snapshot/contribution seam with
   original source/graph/edge provenance; reservation, budget, assessed/completed
   state and inference uniqueness ownership.
9. **Execution identity/recovery:** exact outcome/publication/transition/receipt/job
   identities and durable result reconciliation when domain effects commit but
   response or generic job completion is lost.

Atomic domain/event/follow-up-job creation, synchronous deterministic L0 work,
legal resumable transitions, retry safety, bounded remediation and pure planner
ownership are already requirements. These questions select their implementation
and unresolved interpretations; they are not votes to relax those requirements.
No policy amendment, key formula, ADR or implementation fix is selected here.

## Transaction map

| Boundary | Current ownership / gap |
| --- | --- |
| Raw outcome -> accepted grading/attempt | Source metadata persistence exists; trusted production ingestion/grading/learner authorization and original result receipt are missing. |
| Evidence + optional grading event + replay/projection + schedule + applied marker | Caller-owned transaction in `apply_evidence()`; function flushes and does not commit. |
| Mastery -> material replan trigger | No runtime evaluator/accounting operation; deterministic check belongs to L0 submission transaction. |
| Trigger -> route/deferred request | Caller-owned job creation available; static route, deferred-source/cooldown and key/version ownership missing. |
| Coherent state -> pure planner | Frozen seam exists; assembler captures authoritative time/versions in transaction or revalidates before publication. |
| Decision -> plan/session/frame/action-job writes | No runtime executor/receipt; approved publication transaction must gate policy outcomes and commit domain/event/jobs together. |
| Job claim/heartbeat/finish/reaper | Existing short independent PostgreSQL transactions and lease fences. |
| Due calculation -> durable event | Caller-owned helper; unchanged-cycle retry conflict blocks certifying this path. |
| Bounded pipeline checkpoint | Separate autocommit connection; recoverable pipeline progress, not atomic macro learning state. |
| Graph artifact -> graph/event publication -> job finish | Artifact precedes fenced graph/event transaction; generic job finish is separate. Reusable explicit-fence example, not a runtime receipt. |
| Post-commit wake-up | Existing architecture treats Redis as disposable; it must not become a substitute for durable event/job state. |

Proposed deterministic transaction, subject to approved contracts/fences:

```text
BEGIN (authoritative learner/session ownership and concurrency protocol)
  authenticate/authorize; load or establish immutable outcome identity
  trusted deterministic grade + attempt/source snapshot
  evidence + matching learning event + mastery replay/projections/schedules
  once-only material-trigger/window/cooldown accounting
  if eligible: capture coherent state -> pure planner -> validate policy outcome
               persist plan/version/diff + legal session/frame transition
               persist execution receipt + routed follow-up jobs/events
  else: retain unchanged plan and durable deferred/needs-state facts as applicable
  persist original outcome response/receipt
COMMIT
  optional disposable wake-up / response delivery
```

Async workers do bounded external work without holding that transaction, then
publish validated results in a short transaction with job and domain fences,
receipt/event/transition/follow-up jobs. Checkpoint/object writes and generic job
finish may be separate; the approved receipt/reconciliation protocol must cover
those gaps. No concrete transaction/locking implementation is selected here.

## Workspace and verification record

- Baseline/final HEAD unchanged on `main`:
  `7f9391e0df52a02f851371a053fe6930adabb037`.
- The baseline includes 24 modified tracked files and extensive untracked work.
  None of those files was edited for this assessment.
- Sole file added/updated by this assessment: `docs/SPRINT_3_7_ASSESSMENT.md`.
- Implementation files changed by this assessment: **NONE**. Protected source
  documents and `__agent__/plan.json` remain preserved. The index is empty.
- Tracked baseline/final diff unchanged: 24 files, 1,827 insertions and 22 deletions;
  baseline and final `git diff --binary | sha256sum` fingerprints match:
  `e092199ca3ae5d072f311a30e0ce0795384efbeb5089d9b92eb5bddf336cb618`.
- No staging, commits, Git history operations, file deletion, tests, Docker
  operations or database actions were performed.
- `git diff --check` and
  `git diff --no-index --check /dev/null docs/SPRINT_3_7_ASSESSMENT.md` passed.
  All twelve numbered assessment sections are present; obsolete halted status is
  removed. Final status/index/HEAD checks confirm the preserved dirty baseline,
  empty index and unchanged HEAD. These are documentation/Git checks, not tests.
- Historical Sprint 3.6 baseline: `make test` 336 passed/91 skipped;
  `make check` passed (strict mypy 58 files, seven import contracts);
  `make integration` 94 passed. These were prior sprint results, not a new run.
- The source assessment is complete under owner continuation. The baseline
  defect and implementation/policy approval gates remain unresolved; no Sprint
  3.7 implementation or end-to-end acceptance is claimed.
