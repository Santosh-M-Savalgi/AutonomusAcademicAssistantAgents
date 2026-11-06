# Sprint 3.5 Readiness Assessment

**Assessment date:** 2026-10-04
**Scope:** assessment only; no Sprint 3.5 implementation is included
**Target deliverable:** `docs/SPRINT_3_5_ASSESSMENT.md`

## 1. Executive assessment

Sprint 3.5 is **partially ready after additive contract and policy work**, but it
is not ready to implement as one unqualified feature batch.

The Sprint 3.4 foundation is usable:

- The pure Beta mastery engine already owns chronological replay, lazy forgetting,
  direct and inferred evidence behavior, review-success qualification, and the
  approved review-rung transitions.
- Immutable question-version, attempt, evidence, projection, and concept-impact
  event contracts now preserve the source context needed by later scheduling.
- The graph contracts and pure graph algorithms provide stable concept identity,
  confirmed-edge filtering, topological depth, descendant counts, and deterministic
  traversal.
- The domain package already exposes `REVIEW_DUE` and the approved planner action
  and reason-code vocabulary.

The Sprint 3.5 behavior itself is not present:

- `packages/planner/__init__.py` is still only a scaffold.
- There is no review schedule table, due-date field, nightly selector, or
  idempotent `REVIEW_DUE` producer.
- There is no diagnostic selector, self-report prior contract, or diagnostic
  inferred-evidence producer.
- No production event producer currently emits a qualifying
  `learning-event-v2` concept-impact event, so the 24-hour review clock is not
  operational in the current application flow.
- The smallest planner input contract and the deterministic ordering of review
  candidates are not yet defined.

The recommended status is therefore **foundation reusable; Sprint 3.5 behavior
blocked pending explicit decisions and additive contracts**. The existing
Sprint 3.4 replay and evidence semantics must be consumed as-is rather than
reinterpreted by scheduling or planning code.

## 2. Authoritative source map

| Area | Authoritative requirement | Current support |
|---|---|---|
| Mastery state | `AAA_v3_BUILD_SPEC.md` §6.1 and §5.5; `docs/SPRINT_3_4_POLICY_DECISIONS.md` §§3.1–3.5 | Implemented in `packages/mastery/engine.py` and `packages/domain/mastery.py`. |
| Review ladder | Build spec §6.2; finalized Sprint 3.4 policy §§3.4 and 4.2 | Ladder, 24-hour qualification, pass advancement, and failure reset are implemented. |
| Review scheduling | Build spec §6.2: decayed mastery threshold or passed due date, nightly `REVIEW_DUE`, maximum three warm-up items, no active remediation | Deferred; no schedule or selector exists. |
| Diagnostic selection | Build spec §6.3: budget of 12, descendant/confidence score, weak self-report prior, inferred prerequisite evidence | No diagnostic implementation exists. Graph primitives are reusable. |
| Planner | Build spec §§5.1 and 6.4; D-05; `agents.md` pure-core rule | `PlannerAction`, `ReasonCode`, and `PlannerDecision` exist; `packages/planner` has no policy or state input. |
| Graph eligibility | Build spec §9; ADR 0023; ADR 0024 | Immutable graph snapshots and confirmed-edge algorithms exist. |
| Persistence | Build spec §§11, 12.2, and 12.4; Sprint 3.4 migration 0008 | Evidence/projection/event persistence exists. `review_schedule` and plan persistence do not. |
| End-to-end behavior | Build spec §16.5 and Phase 3 acceptance in §17 | The full diagnostic → planner → remediation flow is not implemented. |

The available repository source is `AAA_v3_BUILD_SPEC.md` / `agents.md`, version
3.2. The referenced `AAA_v3_COMPLETE_BUILD_PLAN.md` is not present in this
checkout and was not substituted. `CLAUDE.md` refers to `AGENTS.md`, while the
checkout contains the lower-case `agents.md`; the available file is the source
used for this assessment.

## 3. Sprint 3.4 reuse assessment

### 3.1 Directly reusable

1. **Mastery transitions.**
   `packages/mastery/engine.py` already applies the finalized review rules:
   direct, full-credit, `is_review=true` evidence can qualify only when the
   previous concept-impact event is at least 24 hours earlier; success increments
   `review_successes` and advances `review_rung`; a failed direct review applies
   ordinary negative evidence and resets the rung.

2. **Review configuration.**
   `REVIEW_LADDER_DAYS = (1, 3, 7, 14, 30, 60)` and the 24-hour delay are already
   explicit in the pure engine. Sprint 3.5 must not create a second ladder or
   alter the state transition semantics.

3. **Immutable evidence source context.**
   `QuestionVersionSnapshot`, `AttemptSnapshot`, and `EvidenceInput` preserve
   graph version, concept roles, timestamps, review marker, grading metadata,
   and idempotency identity. Persistence validates those snapshots before
   replay.

4. **Deterministic replay and projections.**
   Evidence is replayed by `(occurred_at, evidence UUID)`, with one explicit
   projection `as_of`. Projection revisions and heads are immutable/history-aware
   and can be read with transient lazy forgetting.

5. **Concept-impact event boundary.**
   `ConceptLearningEventInput` and the normalized association table provide the
   required learner/concept/occurrence-time boundary and optional source
   evidence/attempt IDs. Legacy and generic v1 events remain non-qualifying.

6. **Graph identity and traversal.**
   `GraphSnapshot` is course- and revision-scoped. Stable concept UUIDs,
   confirmed-edge filtering, cycle validation, topological depth, and unique
   descendant counts are available through `packages/domain/graph.py` and
   `packages/curriculum/graph.py`.

7. **Planner output vocabulary.**
   `packages/domain/enums.py` and `packages/domain/models.py` already constrain
   planner actions, reason codes, target IDs, evidence IDs, policy outcomes, and
   planner policy version.

### 3.2 Reuse conditions and gaps

- Scheduling must be a read/selection layer over immutable mastery and evidence;
  it must not mutate historical evidence or recompute mastery with new rules.
- The current projection revision stores `review_successes` and `review_rung`,
  but it does not store `last_successful_review_at` or `due_at`. Its
  `max_occurred_at` is the latest evidence occurrence, not necessarily the last
  successful review occurrence.
- `_projection_domain()` reconstructs `has_qualifying_review` from
  `status == "MASTERED"`. A scheduler should not use that reconstruction as a
  durable review-history substitute; whether an independent persisted flag is
  required is an owner decision listed below.
- `_concept_events()` reads only `learning-event-v2` associations for one
  learner/course pair. It is suitable for the current replay boundary, but it is
  not yet a general review-clock query service and it does not provide a producer.
- `apply_evidence()` accepts an optional concept event in the same transaction.
  That path is deterministic and transactionally sound, but current application
  flows do not supply qualifying events automatically.
- Sprint 3.5 must preserve graph-version snapshots in any review candidate or
  diagnostic evidence it creates. Historical evidence must never be reinterpreted
  with a newer graph's roles or edges.

## 4. Spaced-review requirements

### 4.1 Requirements fixed by the source

The implementation must preserve all of the following:

- Per-concept interval ladder `[1, 3, 7, 14, 30, 60]` days.
- A qualifying pass advances the finalized zero-based `review_rung`, capped at
  the final rung.
- A failed direct review resets the rung to zero and applies ordinary negative
  evidence.
- A successful review is direct, full-credit, immutable `is_review=true`, unique,
  and at least 24 hours after the previous persisted concept-affecting event.
- Nightly processing identifies a concept when either its decayed mastery is below
  the configured `review_threshold` (default `0.6`) or its due date has passed.
- A session-start warm-up contains at most three review items.
- Review items are not inserted while an active remediation frame exists.
- The emitted `REVIEW_DUE` event must be idempotent and auditable. It must carry
  enough source identity for the planner decision and later `/plan/why` behavior.

### 4.2 Required schedule data

The current projection data is insufficient by itself to answer all scheduling
questions. An additive schedule contract should be evaluated with at least:

- learner identity, course identity, and stable concept ID;
- review policy version and graph version/context;
- current rung and cumulative successful-review count, or a reference to the
  authoritative projection;
- the occurrence time of the last qualifying success;
- the computed due time and the `as_of`/calculation metadata used to compute it;
- schedule status/idempotency identity for due-event emission;
- immutable provenance back to the projection/evidence/event set used.

The exact table and field names are implementation choices. The contract must
make it impossible to confuse the latest evidence time with the last successful
review time.

### 4.3 Clock and mutation boundary

The pure scheduler should receive an explicit timezone-aware `as_of` value. A
worker or caller-owned transaction should obtain the database time, calculate or
refresh due state, and emit the event atomically. Scheduler reads may apply lazy
forgetting transiently; they must not create a mastery revision merely because
wall-clock time advanced.

Late evidence remains governed by Sprint 3.4 chronological replay. If a late
evidence insert changes review success or rung state, the schedule must be
recomputed from the resulting immutable replay rather than patched by arrival
order.

## 5. Review-due selection requirements

### 5.1 Candidate eligibility

The selector needs a deterministic input containing the learner, course/session,
explicit `as_of`, active remediation state, available graph version, and the
authoritative mastery/schedule rows. It should then:

1. consider only concepts that are valid for the current learner/course and graph
   context;
2. evaluate decayed mastery and due time against the source rules;
3. exclude candidates when an active remediation frame is present;
4. preserve stable concept IDs and source evidence/event IDs;
5. return no more than three candidates for the warm-up; and
6. return a stable result for the same immutable input and `as_of`.

The build specification does not define a candidate ranking formula, tie-breaker,
or whether low mastery and overdue status have different priority. Those values
must not be invented in implementation. They are owner decisions below.

### 5.2 Missing and stale state

The following cases need explicit behavior before implementation:

- no projection head exists for a graph concept;
- a schedule row exists but its projection head is missing or stale;
- a projection is transiently below the threshold only because of lazy decay;
- the graph version used to create the candidate is no longer the current course
  graph;
- a due event was already emitted but no warm-up consumed it;
- multiple nightly runs observe the same due concept.

The safe boundary is to make these cases deterministic and idempotent, retain the
source state for audit, and never silently convert a missing projection into a
successful review or a new mastery fact.

### 5.3 Event and planner handoff

The selector should return a typed candidate/recommendation collection rather than
write a planner decision directly. A candidate should expose at least the stable
concept ID, due reason, due time if any, projected mastery/confidence/status,
review rung, policy version, graph version, and supporting evidence/event IDs.

The planner can then select `REVIEW_DUE` only when the candidate collection is
non-empty and no higher-precedence rule applies. The selector must not choose
arbitrary content or bypass the planner's active-remediation rule.

## 6. Diagnostic identification requirements

### 6.1 Source algorithm

Build-spec §6.3 defines a budget of at most 12 diagnostic items. The next concept
is selected by maximizing:

```text
(descendant_count + 1) * (1 - confidence)
```

among unassessed concepts, with one or two items per concept. A correct answer on
a deep concept produces `INFERRED` evidence on its confirmed prerequisites.

The existing `unique_descendant_counts()` helper is reusable and correctly counts
each reachable descendant once, including diamond-shaped graphs. The existing
stable topological and confirmed-edge helpers are also reusable.

### 6.2 Missing diagnostic contracts

- There is no diagnostic selector or diagnostic session state tracking the 12-item
  budget, selected concepts, attempted questions, or completion event.
- There is no typed representation for the weak self-report prior
  (`alpha=2, beta=1`, flagged self-reported). `EvidenceInput.kind` supports only
  `DIRECT` and `INFERRED`; it has no self-report provenance field.
- There is no producer that turns a deep-concept correct answer into one or more
  inferred prerequisite evidence records. The mastery engine can apply a positive
  inferred record, but it does not discover prerequisite edges or create records.
- Evidence supports graph-version and concept-role snapshots, but diagnostic
  inferred evidence needs an explicit causal/provenance contract linking it to the
  diagnostic attempt and the confirmed prerequisite edge(s).
- Tie behavior, question availability/fallback, repeated concepts, and the exact
  budget behavior when fewer than 12 valid questions exist are not specified.

Diagnostic traversal must use confirmed prerequisite relationships for the
inferred-evidence rule in §6.3. Proposed or rejected edges must not create
diagnostic mastery credit. Planner remediation may use the separate §6.4 rule for
confirmed or qualifying high-confidence edges; those two usages should not be
collapsed into one undocumented graph policy.

## 7. Planner integration boundary

### 7.1 Existing boundary

D-05 and the build specification require a deterministic, pure planner. It may
not access the database, HTTP, clock, queue, or randomness. The planner returns
the existing constrained `PlannerDecision`; an LLM may only polish an explanation
or tie-break among already enumerated candidates.

### 7.2 Smallest proposed interface

The smallest useful Sprint 3.5 boundary is two pure inputs/outputs:

1. **Review selector output:** an immutable ordered tuple of review candidates,
   each containing concept ID, due reason, due time, projected mastery/confidence/
   status, review rung, policy/graph versions, and supporting evidence/event IDs.
2. **Planner input:** a `PlanningState` containing the current session/target
   context, active remediation-frame state, diagnostic-pending state, and the
   review-candidate tuple. It is passed to:

   ```python
   PlannerPolicy.decide(state: PlanningState) -> PlannerDecision
   ```

The planner should evaluate the existing first-match rule order: hard stops and
directives first, `REVIEW_DUE` only when no active remediation frame exists,
remediation continuation next, then diagnostic/topic/gate rules. The planner
should return `PlannerAction.REVIEW_DUE`, a stable target ID, `ReasonCode.REVIEW_DUE`,
supporting evidence IDs, policy outcome, and policy version. It should not query
schedule rows, calculate forgetting, select questions, or update mastery.

This is a boundary recommendation, not a new policy decision. The final field
shape and candidate ordering require owner approval before implementation.

## 8. Ambiguities and required owner decisions

The following are genuine Sprint 3.5 decisions rather than Sprint 3.4 replay
questions:

1. **Due-date anchor:** Is the interval measured from the qualifying review's
   `occurred_at`, its database receipt, or another explicit timestamp? The
   mathematical mastery clock remains `occurred_at`; scheduling should be
   consistent unless explicitly separated.
2. **Schedule creation:** Does a schedule row begin for every eligible concept,
   only after the first successful review, or after another mastery condition?
3. **Threshold precedence:** When both decayed mastery is below `0.6` and a due
   date has passed, is the candidate one reason with a fixed precedence or a
   combined reason set?
4. **Candidate ordering:** What is the deterministic ordering when more than three
   concepts are eligible, and what is the final UUID tie-breaker?
5. **Outstanding due state:** Does a failed review remain due immediately, and does
   a successful review clear/recompute the due row in the same transaction?
6. **Repeated due events:** What idempotency key and event boundary prevent a
   nightly job from emitting duplicate `REVIEW_DUE` facts?
7. **Graph-version changes:** Are scheduled candidates retained by stable concept
   ID across graph versions, remapped to the current graph, or invalidated and
   regenerated?
8. **Projection absence/staleness:** Should an unprojected concept be ignored,
   initialized, or rebuilt before it can enter a review queue?
9. **Self-report representation:** Should the weak prior be a separate immutable
   student assertion/evidence kind, a diagnostic event, or an additive field on
   evidence?
10. **Diagnostic ties and question scarcity:** How are equal diagnostic scores,
    unavailable questions, and the one-to-two-items-per-concept rule resolved?
11. **Inferred provenance:** Must every inferred prerequisite record reference the
    source attempt, source question, edge ID, and diagnostic run ID? This is the
    recommended audit shape, but it is not currently a locked contract.
12. **Qualifying event producers:** Which assessment/learning operations will emit
    `learning-event-v2` with explicit concept associations, and are course-less
    learner/concept events allowed for the review clock?
13. **Review qualification persistence:** Should `has_qualifying_review` and the
    last qualifying review timestamp be stored independently from derived status?

Until these are answered, implementation should stop at contracts and tests
rather than silently selecting policy values.

## 9. Recommended implementation sequence

1. **Lock decisions and configuration.** Record the answers above in an ADR or
   Sprint 3.5 policy note; define versioned review and diagnostic policy names.
2. **Add pure contracts and algorithms.** Define schedule/candidate state,
   deterministic due evaluation, diagnostic selection, self-report handling, and
   `PlanningState`; add unit and property tests without I/O.
3. **Add additive persistence.** Add the minimum schedule/provenance fields and
   migration, preserving Sprint 3.4 projection/evidence history and transaction
   ownership.
4. **Add qualifying event producers.** Emit explicit v2 concept-impact events
   from the approved learning operations, with idempotency, causation, and
   learner/concept associations.
5. **Add nightly due processing.** Rebuild or refresh schedules from immutable
   projections, emit idempotent `REVIEW_DUE`, and enforce the active-remediation
   exclusion at session-start selection.
6. **Add diagnostic selection and inferred evidence.** Enforce graph-version and
   confirmed-edge provenance, the 12-item budget, self-report flagging, and causal
   links to source attempts.
7. **Implement the pure planner policy.** Consume only typed planning state and
   return the existing `PlannerDecision`; do not give the planner persistence or
   question-selection responsibilities.
8. **Integrate and verify.** Exercise due selection, review pass/fail, late replay,
   graph changes, diagnostic propagation, planner precedence, idempotent events,
   and the applicable Phase 3 simulation/e2e scenarios.

## 10. Acceptance and test requirements

### Pure unit/property coverage

- Review ladder advancement, cap, failure reset, cumulative success count, and
  24-hour concept-event qualification.
- Due evaluation at exact threshold and exact due time, explicit `as_of`, UTC
  normalization, lazy decay, and late-evidence recomputation.
- Stable candidate ordering, maximum-three truncation, duplicate suppression, and
  active-remediation exclusion.
- Diagnostic descendant counts on chains and diamonds, deterministic score ties,
  12-item budget, one/two-item concept limits, self-report weak prior, and
  confirmed-edge-only inference.
- Inferred evidence provenance, no direct-count increment, no review qualification,
  and idempotent source-attempt linkage.
- Planner first-match precedence: hard stop/directive, review due, active
  remediation, diagnostic, and normal topic/gate paths.

### Persistence/integration coverage

- Schedule creation/recompute and due-event idempotency in a caller-owned
  transaction.
- Exact retry and conflicting idempotency-key behavior for schedules/events.
- Projection head and schedule consistency after late evidence replay.
- No duplicate warm-up items across repeated session-start reads.
- Graph-version provenance and behavior when a candidate's graph is stale or
  unavailable.
- Diagnostic source attempt → inferred evidence → mastery contribution trace.
- Event ordering uses `occurred_at`; `recorded_at` and application receipts do
  not change mathematical replay.

### End-to-end acceptance

The existing build-spec §16.5 flow remains the broad regression target. Sprint 3.5
must additionally demonstrate a review-due warm-up and a bounded diagnostic path
without violating active remediation, deterministic planner decisions, or the
immutable evidence/replay contract.

## 11. Explicit exclusions from this assessment

- No Sprint 3.5 source implementation, migration, scheduler, planner, diagnostic
  service, API, worker, or frontend work.
- No modification to `AAA_v3_BUILD_SPEC.md`, `agents.md`,
  `docs/SPRINT_3_4_POLICY_DECISIONS.md`, ADRs, or existing Sprint 3.4 code.
- No replacement of the approved Beta policy with FSRS, BKT, IRT, or another
  scheduling/mastery model. The build specification explicitly defers those
  experiments.
- No LLM-based planner decisions, arbitrary action generation, or question-content
  generation design.
- No assumption that a generic v1 event or assessment evidence is a qualifying
  concept-impact event without the explicit v2 association block.
- No claim that the full Phase 3 or §16.5 acceptance flow is currently green.

## 12. Repository and verification report

- Branch: `main`.
- HEAD at assessment: `7f9391e0df52a02f851371a053fe6930adabb037`.
- The workspace was already broadly dirty, with Sprint 3.4 additions and other
  user work untracked or modified. Those changes were preserved.
- No files were staged, committed, reset, reverted, cleaned, migrated, or deleted.
- The referenced `AAA_v3_COMPLETE_BUILD_PLAN.md` is unavailable in this checkout.
- The only file created for this task is this assessment document.
- Prior Sprint 3.4 checks recorded before this assessment were `make check`,
  `make test`, and `make integration`; they verified the existing Sprint 3.4
  foundation but did not verify Sprint 3.5 behavior. No test suite or database
  migration was run for this assessment.
