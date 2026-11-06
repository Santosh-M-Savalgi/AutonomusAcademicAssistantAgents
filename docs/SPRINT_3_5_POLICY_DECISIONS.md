# Sprint 3.5 Policy Decisions

**Status:** Finalized for owner review; implementation is not authorized by this document
**Scope:** Spaced Review and Diagnostics only
**Policy version:** `review_diagnostic_v1`
**Date:** 2026-10-04

This document records the decisions required before Sprint 3.5 implementation.
It is documentation-only. It does not add source code, schemas, migrations,
workers, APIs, tests, or configuration.

## 1. Provenance labels

Every policy statement in this document uses one of these labels:

- **SPECIFIED** — stated directly in the authoritative build specification.
- **FINALIZED** — already approved in `docs/SPRINT_3_4_POLICY_DECISIONS.md`.
- **DERIVED** — required by existing contracts or by preserving a specified or
  finalized invariant.
- **OWNER-APPROVED INTERPRETATION** — selected here where the source is silent.
- **UNRESOLVED** — cannot safely be decided from the available evidence.

No contradiction was found between decisions A–M and an explicit source
requirement. The owner-approved interpretations are therefore recorded as
policy, while the implementation dependencies remain blockers to coding.

## 2. Authority and inspected state

### 2.1 Authoritative sources

The authoritative source is `AAA_v3_BUILD_SPEC.md`, also present in this
checkout as the lower-case repository instruction file `agents.md` (version
3.2). The referenced `AAA_v3_COMPLETE_BUILD_PLAN.md` is absent from the
checkout and was not substituted.

Relevant requirements inspected:

- §5.1: constrained `PlannerAction` and `PlannerDecision` contracts.
- §5.2: append-only event types and event envelope.
- §5.4–§5.5: closed-vocabulary questions and direct/inferred evidence.
- §6.1: Beta posterior, forgetting, status, direct counts, inferred evidence,
  and idempotency.
- §6.2: interval ladder, threshold/due triggers, nightly `REVIEW_DUE`, maximum
  three warm-up items, and active-remediation exclusion.
- §6.3: diagnostic score, budget, weak self-report prior, and confirmed
  prerequisite inference.
- §6.4: planner precedence and pure `PlanningState -> PlannerDecision` boundary.
- §6.5: nightly mastery-decay trigger and planner/replan context.
- §9: graph versioning, stable concepts, confirmed/high-confidence edge use, and
  graph diff behavior.
- §11: `review_schedule`, idempotency constraints, and PostgreSQL ownership.
- §12: caller-owned transaction, event/job creation, session FSM, and retry
  behavior.
- §16.3, §16.5, and §17: simulator, mandatory end-to-end regression, and Phase 3
  acceptance.

Related accepted decisions inspected:

- `docs/decisions/0005-deterministic-planner.md` (D-05).
- `docs/decisions/0007-beta-mastery.md` (D-07).
- `docs/decisions/0023-graph-contracts-and-revision-provenance.md`.
- `docs/decisions/0024-durable-graph-publication.md`.

### 2.2 Existing implementation state

The following existing work was inspected and is reusable but incomplete for
Sprint 3.5:

- `packages/domain/mastery.py` has immutable evidence, state, projection, and
  replay contracts. It has no self-report assertion or diagnostic provenance
  contract, and no last-successful-review field.
- `packages/mastery/engine.py` owns Beta weighting, forgetting, chronological
  replay, review qualification, and rung transitions. It uses
  `REVIEW_LADDER_DAYS = (1, 3, 7, 14, 30, 60)` and a 24-hour delay.
- `packages/mastery/weights.py` implements the finalized correct/incorrect
  weight components and inferred-positive formula.
- `packages/domain/events.py` has `learning-event-v2` with explicit
  `AFFECTS_CONCEPT`, learner/concept associations, and optional source evidence
  and attempt IDs.
- `packages/persistence/mastery.py` replays evidence and v2 concept events in a
  caller-owned transaction. Its concept-event query is internal and currently
  course-scoped.
- `packages/persistence/concept_events.py` provides idempotent v2 event
  insertion, but no current production operation supplies qualifying events.
- `packages/domain/graph.py` and `packages/curriculum/graph.py` provide stable
  graph contracts, confirmed-edge filtering, topological ordering, depth, and
  unique descendant counts.
- `packages/domain/enums.py` already contains `REVIEW_DUE`, but it does not
  contain the two detailed candidate-reason values selected below.
- `packages/domain/models.py` has the final `PlannerDecision` output contract.
- `packages/planner/__init__.py` is still only a pure-package scaffold.
- `MasteryProjectionRevision` stores `review_successes` and `review_rung`, but
  not `last_successful_review_at`, `last_successful_review_evidence_id`,
  `last_successful_review_event_id`, or `due_at`. Its current adapter reconstructs `has_qualifying_review` from
  `status == "MASTERED"`; Sprint 3.5 must not use that as review-history truth.

`docs/SPRINT_3_5_ASSESSMENT.md` identified the same readiness boundary: the
Sprint 3.4 foundation is reusable, while scheduling, diagnostics, planner
behavior, and qualifying event producers remain absent.

## 3. Finalized review policy

### A. Review due-date anchor

**Status:** OWNER-APPROVED INTERPRETATION, preserving FINALIZED replay semantics

The next due date is calculated from the successful review's domain occurrence
time:

```text
anchor_at = successful_review.occurred_at, normalized to UTC
next_due_at = anchor_at + interval_days[review_rung_after_transition]
interval_days = [1, 3, 7, 14, 30, 60]
```

The initial schedule uses the first qualifying concept-impact event as its
one-day anchor:

```text
initial_due_at = first_concept_event.occurred_at + interval_days[0]
```

The post-transition rung is used for the next interval. Thus a successful review
at the initial due point advances from rung 0 to rung 1 and schedules the next
interval at three days. Rung 0 therefore represents an actual initial one-day
interval, not a sentinel.

The following timestamps are excluded from mathematical scheduling:

- `recorded_at`;
- `applied_at`; and
- `replayed_at`.

All timestamps are timezone-aware UTC values using the existing PostgreSQL
timezone-aware microsecond precision policy. A late evidence record causes the
schedule to be recomputed from chronological replay at the new projection
revision. Its arrival, recording, or replay time never becomes the schedule
anchor.

This does not change Sprint 3.4 review-rung transitions. The mastery engine
remains the sole authority for rung state.

### B. Schedule creation and eligibility

**Status:** OWNER-APPROVED INTERPRETATION derived from SPECIFIED §6.2 and the
FINALIZED Sprint 3.4 rung semantics

A schedule lifecycle has two creation paths:

1. When the first qualifying concept-impact event for a learner/course/concept
   is persisted, initialize rung 0 and set `due_at` to that event's occurrence
   time plus one day. This seeds the specified initial interval; it does not
   make an arbitrary graph concept a review candidate.
2. If no qualifying concept-impact event exists but an authoritative projection
   satisfies a source eligibility condition, create a low-mastery schedule with
   no successful-review anchor and no due date.

After initialization, a concept is a review candidate when one of the source
eligibility conditions holds:

1. its decayed mastery is below `review_threshold`, whose specified default is
   `0.6`; or
2. its existing due date has passed.

No additional mastery threshold is introduced. In particular:

- a graph concept with no mastery projection is not scheduled merely because it
  exists in the graph;
- a missing projection is not silently initialized for scheduling;
- an unassessed concept with no authoritative projection is not treated as a
  zero-mastery candidate; and
- `MASTERED`, `PROFICIENT`, or any other status is not added as an eligibility
  gate beyond the source conditions.

An eligible low-mastery concept may have no prior successful review. In that
case, the schedule either has the initial one-day due date seeded by the first
qualifying concept event or, when no such event exists, stores a null anchor and
an absent due date. It is eligible through the low-mastery reason until a
successful review creates or recomputes the next due date.

A successful review recomputes its schedule in the same caller-owned transaction
as evidence application, replay, projection advancement, and the relevant event
write. A failed direct review retains the current schedule cycle and immediately
re-evaluates it for the next selection pass. It does not create a due date from
the failed attempt. The normal selection conditions still apply, and the
failure does not clear an already-passed due date or the low-mastery condition.

This preserves the source's two eligibility triggers while honoring the
Sprint 3.4 failure reset. It does not add a third mastery threshold or a
failure-based mathematical anchor.

### C. Review candidate reasons

**Status:** OWNER-APPROVED INTERPRETATION; typed additive domain contract required

The review selector uses a typed reason set:

```text
ReviewDueReason:
    MASTERY_BELOW_THRESHOLD
    REVIEW_OVERDUE
```

Reasons are retained in deterministic enum order. If both conditions apply, the
candidate carries both reasons; neither is discarded through precedence.

The existing planner `ReasonCode` remains `REVIEW_DUE` for the planner decision.
The detailed `ReviewDueReason` set belongs to the review candidate, schedule
record, event payload, and `/plan/why` provenance. This avoids changing the
existing planner vocabulary during policy finalization while preserving both
facts for audit.

Every candidate also retains:

- learner, course, and stable concept identity;
- graph-version identity used for the schedule;
- projection revision ID and evidence-set digest;
- due date, if one exists;
- decayed mastery, confidence, status, rung, and cumulative success count;
- supporting evidence/event IDs; and
- review-policy version.

### D. Candidate ranking and maximum-three limit

**Status:** OWNER-APPROVED INTERPRETATION; no source ranking formula exists

The source specifies the final warm-up maximum of three but does not define a
ranking formula. The following deterministic ranking is therefore selected:

1. Candidates containing `REVIEW_OVERDUE` rank before candidates containing only
   `MASTERY_BELOW_THRESHOLD`.
2. Within the overdue group, sort by earliest `due_at` ascending.
3. Within equal due times, sort by lower decayed mastery ascending.
4. For low-mastery-only candidates, sort by lower decayed mastery ascending.
5. Resolve every remaining tie by stable concept UUID ascending, comparing the
   UUID's 128-bit value.

The equivalent key is:

```text
(
    0 if REVIEW_OVERDUE in reasons else 1,
    due_at if overdue else +infinity,
    decayed_mastery,
    stable_concept_id.bytes,
)
```

The due-time component is ignored for low-mastery-only candidates. Both reasons
remain attached to a candidate even when the overdue group determines its rank.

The selector removes duplicate stable concept IDs before ranking and returns at
most three candidates for the final session-start warm-up collection. The
maximum applies after eligibility, provenance validation, duplicate suppression,
and sorting. An active remediation frame returns no review insertion, regardless
of candidate count.

Identical immutable inputs, graph context, question state, policy version, and
`as_of` must produce identical candidate order.

### E. Failed and successful review scheduling

**Status:** OWNER-APPROVED INTERPRETATION consistent with FINALIZED Sprint 3.4
review transitions

- The mastery engine alone advances a successful review rung and resets a failed
  direct review to rung zero.
- The scheduler never independently increments, decrements, or resets a rung.
- A failed direct review applies the normal negative evidence through the engine
  and leaves the current schedule cycle immediately eligible for the next normal
  selection pass. A prior due date remains overdue; a low-mastery condition is
  re-evaluated from the resulting projection.
- A successful review recomputes `last_successful_review_at`, the next due date,
  and the schedule cycle in the same caller-owned transaction as evidence
  application and projection-head advancement.
- The schedule consumes the engine's post-replay state. It never reconstructs a
  rung from `review_successes` or from wall-clock time.

The phrase “immediately eligible” means immediately available for normal
eligibility evaluation, not an unconditional bypass of the source triggers or
the active-remediation exclusion.

### F. Idempotent `REVIEW_DUE` events

**Status:** OWNER-APPROVED INTERPRETATION derived from existing event idempotency
contracts

`REVIEW_DUE` is a durable event, not a Redis notification. The event is written
in the caller-owned transaction that creates or advances the corresponding
schedule state. Redis may publish a wake-up after commit but is never the source
of truth.

The schedule cycle is a deterministic SHA-256 digest over this canonical ASCII
material, with no display labels and no receipt/arrival timestamp:

```text
review-schedule-cycle:v1|
learner={learner_uuid.hex}|
course={course_uuid.hex}|
concept={stable_concept_uuid.hex}|
graph={graph_version_id.hex}|
policy={review_policy_version}|
anchor_evidence={last_successful_review_evidence_uuid.hex or 32 zeroes}|
anchor_event={initial_or_last_successful_concept_event_uuid.hex or 32 zeroes}|
rung={post_transition_review_rung}|
due_at={UTC ISO-8601 with six fractional digits or -}|
evidence_set={projection_evidence_set_digest}
```

The material is concatenated without whitespace or line breaks and hashed as
UTF-8. The event idempotency key is:

```text
review-due:v1:{learner_uuid.hex}:{course_uuid.hex}:{stable_concept_uuid.hex}:{schedule_cycle_sha256}:{review_policy_version}
```

The key is lowercase ASCII and uses canonical UUID hex values. The schedule
cycle changes when a late replay changes the evidence-set digest, initial or
successful-review event anchor, successful-review evidence anchor, rung, due
date, graph context, or policy version. Re-running the same nightly calculation
with identical source state produces the same key.

The event payload records the schedule cycle, both detailed reasons, projection
revision ID, evidence-set digest, graph version, due date, anchor event ID, and
supporting evidence/event IDs.

`REVIEW_DUE` itself is an operational notification and does **not** represent a
learning occurrence. It must not be inserted into `learning_event_concepts` as
`AFFECTS_CONCEPT`, because doing so would incorrectly become the previous
concept-impact event for a future review. Until a non-impact event contract is
added, the producer should use the existing append-only event envelope with
stable concept IDs and schedule provenance in its payload, while leaving the
v2 concept-impact association absent.

Existing unique event-id and idempotency-key constraints provide the durable
duplicate guard. Conflicting reuse of a key with different immutable content is
an error, matching `insert_concept_learning_event()` behavior.

### G. Graph-version changes

**Status:** OWNER-APPROVED INTERPRETATION derived from ADRs 0023/0024 and §9

- Stable concept UUIDs remain the identity within their valid lineage.
- A pending candidate is revalidated against the current published, confirmed
  graph before session-start insertion.
- Historical schedule rows and events retain the graph version that produced
  them. They are never rewritten to the current graph.
- A concept that still exists in the current graph may be selected only after
  current graph membership and confirmed-edge context are revalidated. Any
  refreshed schedule context is a new schedule calculation, not historical
  reinterpretation.
- If a concept no longer exists in the current graph, its pending candidate is
  marked ineligible/superseded with an auditable reason. It is not silently
  remapped.
- Split, merge, replacement, and successor-curriculum lineage do not transfer
  mastery or review state automatically. Explicit stable concept lineage and a
  future owner decision would be required for transfer.
- New diagnostic propagation uses only the current confirmed graph and its edge
  IDs. Historical inferred evidence retains the graph version and edge
  provenance that produced it.

### H. Missing or stale mastery projections

**Status:** OWNER-APPROVED INTERPRETATION; minimum freshness contract required

A missing projection is never interpreted as zero mastery, successful mastery,
or an implicit initial state by the selector. The selector returns a typed
`MISSING_PROJECTION` result and does not create evidence, schedule success, or a
projection revision.

The minimum future freshness contract is:

```text
ProjectionFreshness:
    FRESH
    MISSING_PROJECTION
    MISSING_REVISION
    EVIDENCE_SET_STALE
    GRAPH_CONTEXT_STALE
```

For a projection to be `FRESH`:

1. `MasteryProjectionHead` must exist for learner/course/concept.
2. Its `current_projection_id` must resolve to a revision.
3. A deterministic digest/count recomputed from the accepted immutable evidence
   set must equal the revision's `evidence_set_digest`/`evidence_count`.
4. The schedule's graph context must be revalidated against the current published
   graph, with the stable concept still present.

Failure of (1) or (2) is missing state. Failure of (3) is stale evidence state.
Failure of (4) requires graph revalidation; absent concept identity makes the
candidate ineligible, while a surviving concept may receive a new schedule
calculation under the current graph.

The current repository has no standalone freshness helper and projection
revisions do not store a graph-version ID. This is an implementation dependency:
the future repository boundary must expose the typed result above or an
equivalent authoritative predicate. The selector must not repair stale state or
create an immutable projection revision merely because `as_of` advanced.

### I. Self-report prior

**Status:** OWNER-APPROVED INTERPRETATION of SPECIFIED §6.3

The weak self-report prior is represented by a separate immutable assertion and
prior-contribution record, not by a fake answer or `EvidenceInput` row.

Minimum contract:

```text
SelfReportAssertion:
    assertion_id
    learner_id
    course_id
    stable_concept_id
    graph_version_id
    occurred_at
    idempotency_key
    policy_version
    provenance = SELF_REPORTED
```

The assertion is applied once per learner/course/stable-concept identity. A
repeated submission for that same identity is an idempotent no-op or an immutable
logical-match response; it cannot add another prior mass. A distinct diagnostic
run does not apply the same prior again.

Replay starts from the existing Beta prior `(alpha, beta) = (1, 1)` and applies
the self-report contribution exactly once:

```text
alpha += 1
beta  += 0
```

This yields the specified weak prior `(alpha, beta) = (2, 1)` without overwriting
the prior or inserting a synthetic question/attempt. The contribution:

- does not increment `n_direct`;
- does not add a distinct direct question ID;
- cannot satisfy `MASTERED`;
- remains distinguishable from direct and inferred assessment evidence;
- is included in the deterministic replay input/fingerprint; and
- is auditable and idempotent.

Because a self-report changes the posterior without representing an assessment,
diagnostic eligibility uses a separate `diagnostic_assessed` predicate. A
self-report alone does not clear diagnostic pending state or exclude the concept
from placement selection. This prevents the prior from satisfying a gate while
honoring the source's “unassessed concepts” diagnostic rule.

### J. Diagnostic selection and deterministic ties

**Status:** OWNER-APPROVED INTERPRETATION preserving all SPECIFIED formulas

The diagnostic score is exactly:

```text
score = (descendant_count + 1) * (1 - confidence)
```

No confidence threshold, multiplier, or additional score term is introduced.
`confidence` is the existing derived evidence confidence, not LLM confidence.
Diagnostic eligibility and diagnostic pending state are independent from the
posterior's confidence. A concept with no assessment evidence remains
diagnostically unassessed, including when it has a self-report prior. The score
nevertheless uses the actual specified Beta confidence for the current state;
there is no second diagnostic confidence formula:

```text
No prior contribution:  (alpha,beta) = (1,1), n_eff = 0, confidence = 0
Self-report prior:      (alpha,beta) = (2,1), n_eff = 1, confidence = 1/5 = 0.2
Self-report score:      (descendant_count + 1) * (1 - 0.2)
```

The self-report therefore changes the diagnostic score while leaving diagnostic
eligibility pending. This follows the specified formulas and the separate
`diagnostic_assessed` predicate from decision I.

Selection rules:

1. Use only unassessed-for-diagnostic concepts in the current confirmed graph.
2. Use `unique_descendant_counts()` over confirmed prerequisite relationships.
3. Rank score descending.
4. Resolve equal scores by stable topological order over the confirmed graph.
5. Resolve any remaining tie by stable concept UUID ascending.
6. For each selected concept, choose up to two valid, active question versions,
   never exceeding the remaining total budget of 12.
7. Within a concept, order otherwise-valid question versions by stable question
   version UUID ascending. This is an owner-approved deterministic inventory
   tie-breaker, not a question-generation rule.
8. Do not repeat a concept or question version within one diagnostic run.
9. If fewer than 12 valid questions are available, return the valid smaller set.
10. If a selected concept has no valid question, skip it and continue with the
    next ranked concept; do not invent a question or relax graph constraints.

The one-or-two source constraint is implemented as “up to two”: one valid item
produces one item, two or more valid items produce two, and no valid item
produces none. The total output never exceeds 12.

The selector is pure and deterministic for the same graph snapshot, learner
state, question inventory, diagnostic state, and policy version.

### K. Diagnostic inferred prerequisite evidence

**Status:** OWNER-APPROVED INTERPRETATION; transitive reading of SPECIFIED §6.3

A correct, full-credit diagnostic answer may produce inferred positive evidence
for the **transitive closure** of all confirmed prerequisite concepts of the
answered deep concept. “Confirmed prerequisites” is interpreted transitively
because the diagnostic purpose is to use a demonstrated deep concept to support
all confirmed prerequisite concepts, while retaining exact edge provenance.

The propagation algorithm:

1. Start with the source diagnostic concept(s) answered correctly.
2. Traverse prerequisite edges in reverse dependency direction: for an edge
   `source -> target`, `source` is the prerequisite and `target` is the dependent.
3. Include only `status == CONFIRMED` prerequisite edges from the source graph
   version. Proposed, rejected, and unrelated edge types are excluded.
4. Deduplicate prerequisite concept IDs globally for the source attempt. A
   diamond-shaped graph produces one inferred contribution for a shared ancestor,
   regardless of the number of paths.
5. Emit at most one logical inferred contribution for each
   `(source_attempt_id, prerequisite_concept_id)` pair.

The deterministic idempotency key for one inferred contribution is:

```text
diagnostic-inferred:v1:{source_attempt_uuid.hex}:{prerequisite_concept_uuid.hex}
```

The provenance contract retains:

- learner identity;
- diagnostic run ID;
- source attempt ID;
- source question-version ID;
- source direct evidence ID;
- source graph-version ID;
- confirmed prerequisite edge IDs used by the transitive closure; and
- target prerequisite concept ID.

The inferred contribution uses the existing Sprint 3.4 positive formula:

```text
alpha_delta = 0.3 * w_correct * role_weight
beta_delta = 0
```

For a prerequisite concept, `role_weight = 0.5` under the existing role policy.
It does not increment `n_direct`, add a distinct direct question, qualify
`MASTERED`, or advance a review rung. Partial or incorrect diagnostic answers
produce no inferred prerequisite mastery contribution. They remain governed by
the existing direct evidence behavior for the source answer only.

The current `EvidenceInput` and persistence rows do not carry all of this
diagnostic provenance. That is an additive contract dependency, not a reason to
weaken the existing evidence schema or to infer provenance from labels.

### L. Qualifying concept-impact events

**Status:** OWNER-APPROVED INTERPRETATION; current production operation is absent

Only an explicit `learning-event-v2` record with:

- `concept_impact = AFFECTS_CONCEPT`;
- learner identity;
- one or more stable concept UUIDs;
- timezone-aware `occurred_at`; and
- the normalized association row

qualifies for the 24-hour review clock. Generic v1 payloads, event names,
assessment evidence alone, graph events, operational events, and Redis messages
do not qualify.

The smallest future producer set is one real answer-grading operation for all
accepted direct assessment answers, including checkpoint, quiz, diagnostic, and
review answers. It should emit an `ANSWER_GRADED` concept-impact event using the
concept roles from the immutable question/evidence snapshot, with
`source_evidence_id`, `source_attempt_id`, `causation_id`, and the same
caller-owned transaction as evidence application. Both source IDs are required
for a qualifying answer event; `causation_id` remains audit/correlation metadata
and is not the current-attempt exclusion key. The repository currently has no
production answer-grading operation, so this is an implementation dependency for
the future assessment/closed-loop work.

For the evidence currently being replayed, the event produced by that same
attempt is excluded from the set of previous concept-impact events when either
of these exact immutable identities matches:

```text
event.source_evidence_id == current_evidence.evidence_id
or event.source_attempt_id == current_evidence.attempt_id
```

The exclusion is applied per current evidence item, before selecting its prior
concept-event timestamp. It is not a global time-window exclusion. An unrelated
event with an earlier `occurred_at` remains eligible to establish the 24-hour
boundary. The current event is still persisted atomically and becomes eligible
to affect later attempts. The existing strict chronological comparison and
`(occurred_at, evidence UUID)` evidence replay order remain unchanged; identity
exclusion is required even when equal timestamps would already prevent a
same-time event from qualifying.

The following are not qualifying producers unless a future domain operation
explicitly establishes concept impact:

- `CURRICULUM_CONFIRMED`;
- `GRAPH_BUILT`;
- prerequisite-edge confirmation/rejection;
- successor-curriculum creation;
- `SESSION_STARTED`;
- `ANSWER_SUBMITTED` before grading;
- aggregate `DIAGNOSTIC_COMPLETED`;
- derived `MASTERY_UPDATED`; and
- `REVIEW_DUE`.

`REVIEW_DUE` is an operational notification and therefore must not be inserted
as an `AFFECTS_CONCEPT` event. Its target concept and source provenance belong
in its non-impact event payload as specified in decision F.

All qualifying events use the existing idempotent event contract, are written in
the transaction of the real operation they describe, and preserve causation and
correlation IDs. No artificial event is created solely to make a review pass
qualify.

### M. Review qualification history

**Status:** OWNER-APPROVED INTERPRETATION derived from replay correctness

The authoritative source of review qualification is deterministic replay over
immutable evidence and explicit concept-impact events. Materialized projection
fields are derived outputs, not independent authority.

The authoritative meaning of each field is:

| Field | Authority |
|---|---|
| `review_successes` | Count of qualifying direct full-credit reviews produced by chronological replay. The existing projection column is a materialized value for a matching evidence-set digest. |
| `has_qualifying_review` | Derived as `review_successes >= 1` from replay; never inferred from `status == "MASTERED"`. |
| `review_rung` | The replayed state transition owned exclusively by the Sprint 3.4 mastery engine. |
| `last_successful_review_at` | The occurrence time of the latest qualifying review transition from the same replay. |
| `last_successful_review_evidence_id` | The evidence UUID of that transition, used as immutable schedule provenance. |
| `last_successful_review_event_id` | The v2 concept-impact event linked by `source_evidence_id`/`source_attempt_id` to that transition, used as event-clock and schedule provenance. |

The current replay result and projection revision do not expose the last three
values. The minimum future contract is to add replay-derived review-history
metadata to the pure replay output and materialize
`last_successful_review_at`, `last_successful_review_evidence_id`, and
`last_successful_review_event_id` on each projection revision, or expose an
equivalent immutable review-transition record. The transition metadata must be
computed after excluding the current attempt's own event under decision L.
The schedule may cache those fields, but its authoritative input remains the
matching projection/evidence-set digest.

Late evidence creates a new replay/projection revision. If it changes which
review qualifies, the new revision's review history replaces the old materialized
schedule inputs and creates a new schedule cycle. Historical evidence and old
projection revisions remain unchanged.

## 4. Cross-policy consistency audit

| Invariant | Result | Finding |
|---|---|---|
| Review-rung transitions | CONSISTENT | The scheduler consumes the engine's post-transition rung and never mutates it. The ladder remains `[1, 3, 7, 14, 30, 60]`; the initial rung 0 creates the first one-day schedule. |
| Due-date calculation | CONSISTENT | The initial due date uses the first qualifying concept event; later due dates use successful-review `occurred_at` and the post-transition rung. `recorded_at`, `applied_at`, and `replayed_at` remain audit/replay metadata only. |
| Late evidence replay | CONSISTENT | Schedule cycle changes from replay-derived anchor/digest; arrival order cannot patch or preserve stale schedule state. |
| Projection revisions/heads | DEPENDENCY | Existing heads and digests support freshness checks, but last successful review metadata and a public freshness helper are absent. |
| Concept-impact events | CONSISTENT | Only explicit v2 associations qualify. Current event producers do not qualify; a real grading producer is required. |
| `REVIEW_DUE` events | CONSISTENT | Due notifications are non-impact events and cannot become the previous learning event. |
| Current-attempt event exclusion | CONSISTENT | The current v2 event is excluded by matching `source_evidence_id` or `source_attempt_id`; unrelated earlier events remain eligible and the current event remains persisted for later attempts. |
| Graph versioning | CONSISTENT | Historical graph context is retained; current confirmed graph is required for new selection/inference. No automatic split/merge/successor transfer. |
| Self-report prior | CONSISTENT | It is a separate prior contribution, not direct evidence; actual Beta confidence is `0.2` for `(2,1)`, while diagnostic eligibility remains pending. It gives no direct count, distinct question, gate, or review credit. |
| Diagnostic score | CONSISTENT | Diagnostic eligibility is independent from posterior confidence; the score uses the specified confidence, including `0.2` after a self-report prior. |
| Diagnostic inference | CONSISTENT | Confirmed transitive ancestors are deduplicated by concept and source attempt; proposed/rejected edges are excluded. |
| `n_direct` and distinct questions | CONSISTENT | Only `DIRECT` evidence changes those counters. Self-report and inferred evidence do not. |
| `MASTERED` qualification | CONSISTENT | Requires the existing proficiency gates plus replay-derived qualifying review; neither self-report nor inferred evidence qualifies. |
| Active remediation | CONSISTENT | Planner precedence and session-start selection both block review insertion during an active remediation frame. |
| Event idempotency | CONSISTENT | Stable schedule-cycle key and existing unique event/idempotency constraints prevent duplicate logical due events. |
| Planner determinism | CONSISTENT | Selector and diagnostic inputs are explicit; the pure planner receives typed state and no clock, database, queue, HTTP, or randomness. |
| Successor curricula | CONSISTENT | ADR 0024's immutable lineage is preserved; no implicit mastery or review transfer is introduced. |

### 4.1 Current implementation dependencies

The policy is closed, but the following must exist before implementation can be
considered complete:

1. A schedule/candidate domain contract and additive `review_schedule`
   persistence consistent with §11.
2. Replay-derived last-success metadata, including event identity, and a freshness
   predicate or equivalent repository contract.
3. A self-report assertion/prior-contribution contract and replay integration,
   including the specified confidence calculation.
4. Diagnostic run/candidate/provenance contracts and transitive confirmed-edge
   traversal.
5. A typed detailed reason set; the existing planner `ReasonCode` remains the
   coarse `REVIEW_DUE` output.
6. A real answer-grading operation that emits qualifying v2 events with both
   source IDs, plus replay filtering for the current-attempt event.
7. A pure `PlanningState` and planner policy; the current planner package is a
   scaffold only.

These are implementation blockers, not unresolved policy choices.

## 5. Minimum planner boundary

The review selector and diagnostic selector remain outside the pure planner.
They produce immutable, deterministic typed data. The planner consumes that data
and returns the existing `PlannerDecision`.

### 5.1 Review candidate output

The minimum future `ReviewCandidate` shape is:

```text
ReviewCandidate:
    learner_id
    course_id
    stable_concept_id
    reasons: ordered tuple[ReviewDueReason, ...]
    due_at: datetime | None
    decayed_mastery
    confidence
    mastery_status
    review_successes
    review_rung
    projection_revision_id
    evidence_set_digest
    graph_version_id
    review_policy_version
    supporting_evidence_ids: ordered tuple[UUID, ...]
    supporting_event_ids: ordered tuple[UUID, ...]
```

The tuple is already ranked by decision D and contains no duplicate concept.

### 5.2 Diagnostic state output

The minimum future diagnostic state is:

```text
DiagnosticState:
    diagnostic_run_id
    learner_id
    course_id
    graph_version_id
    diagnostic_policy_version
    item_budget = 12
    selected_concept_ids
    attempted_question_version_ids
    diagnostic_assessed_concept_ids
    remaining_item_budget
```

`DiagnosticCandidate` contains the concept UUID, exact score, descendant count,
confidence, stable topological rank, and up to two ordered question-version IDs.

### 5.3 Sprint 3.5 planner input

The minimum Sprint 3.5 `PlanningState` extension is:

```text
PlanningState:
    learner_id
    course_id
    session_id
    plan_version
    planner_policy_version
    hard_stop: PlannerAction | None
    pending_user_directive: typed directive | None
    active_remediation_frame: typed frame | None
    review_candidates: ordered tuple[ReviewCandidate, ...]
    diagnostic_state: DiagnosticState | None
    target_topic_id: UUID | None
```

The existing build-spec planner rules require hard stops, directives, active
frames, topic/gate context, and diagnostic state. The exact directive, frame,
topic, and gate submodels are not mandated by this Sprint 3.5 policy and should
be reused from later planner work when available rather than duplicated.

`PlannerPolicy.decide(state: PlanningState) -> PlannerDecision` remains pure.
The first-match order remains source-specified:

1. hard stops;
2. pending user directives;
3. `REVIEW_DUE` when candidates exist and no active remediation frame exists;
4. active remediation continuation or return;
5. later diagnostic/topic/gate rules.

The planner does not query PostgreSQL, Redis, HTTP, wall-clock time, or random
state. It does not calculate forgetting, rank raw graph edges, select arbitrary
questions, update mastery, or create events. It reuses `PlannerAction.REVIEW_DUE`,
`ReasonCode.REVIEW_DUE`, and the existing `PlannerDecision` output.

This is the smallest Sprint 3.5 boundary. It does not implement the complete
Sprint 3.6/3.7 planning or replanning system.

## 6. Proposed implementation sequence

The following sequence is safe only after owner review of this document. Each
stage remains within the existing pure/domain, persistence, worker, and API
boundaries.

### 1. Sprint 3.5 policy and contracts

- **Scope:** Add approved domain contracts for due reasons, candidates,
  schedule state, self-report assertions, diagnostic state, inferred provenance,
  and the minimum planning input.
- **Domain contracts:** Frozen, strict, versioned Pydantic models; no database or
  clock access.
- **Pure logic:** None beyond validation and canonical serialization.
- **Persistence/migration:** No migration until the contract shape is reviewed;
  existing Sprint 3.4 policy and source documents remain unchanged.
- **Worker/API:** None.
- **Transaction/idempotency:** Define keys and canonical forms before persistence.
- **Acceptance:** JSON round-trip, extra-field rejection, timezone normalization,
  canonical ordering, and import-linter purity.

### 2. Pure due-date calculation and candidate selection

- **Scope:** Implement `next_due_at`, eligibility, reason-set formation, ranking,
  duplicate suppression, maximum-three truncation, and active-frame exclusion.
- **Domain contracts:** `ReviewScheduleState`, `ReviewCandidate`,
  `ReviewDueReason`, and `ProjectionFreshness`.
- **Pure logic:** Explicit UTC `as_of`; no database or application clock; use the
  engine's post-transition rung and specified threshold only.
- **Persistence/migration:** None in the pure stage.
- **Worker/API:** Callers later provide database-derived snapshots.
- **Transaction/idempotency:** No mutation; schedule updates occur later.
- **Acceptance:** First qualifying concept event creates `rung=0` with a one-day
  due date; a successful review advances to rung 1 and a three-day next due
  date. Also test exact threshold boundaries, both reasons retained, ranking
  keys, UUID ties, duplicate concepts, no more than three, active-remediation
  exclusion, and late-replay input differences.

### 3. Self-report prior and diagnostic state

- **Scope:** Model the immutable self-report assertion and bounded diagnostic run
  state without treating self-report as assessment evidence.
- **Domain contracts:** `SelfReportAssertion`, `SelfReportPriorContribution`,
  `DiagnosticState`, and diagnostic eligibility predicate.
- **Pure logic:** Apply `(alpha, beta) = (2, 1)` once from `(1, 1)` by a prior
  contribution; leave direct counters and review state unchanged.
- **Persistence/migration:** Future additive assertion/prior ledger; no current
  table is modified by this policy document.
- **Worker/API:** A future directive/diagnostic entry point may submit the
  immutable assertion; no new endpoint is authorized here.
- **Transaction/idempotency:** Unique learner/course/concept assertion identity;
  identical retry is a no-op, conflicting content fails.
- **Acceptance:** One application only, replay stability, actual confidence
  `0.2` for `(2,1)`, diagnostic pending remains true, no gate/review credit,
  and no fake question/attempt row.

### 4. Diagnostic selection and prerequisite inference

- **Scope:** Implement score ranking, deterministic question selection, budget,
  confirmed transitive prerequisite closure, and deduplicated inferred outputs.
- **Domain contracts:** `DiagnosticCandidate`, `DiagnosticInferenceProvenance`,
  and a typed inferred-contribution request.
- **Pure logic:** Use exact score, confirmed graph only, stable topological/UUID
  ties, up to two questions per concept, and at most 12 total items.
- **Persistence/migration:** The selector itself is pure; inferred requests are
  later persisted through the existing evidence transaction boundary.
- **Worker/API:** Diagnostic worker/session orchestration may call the pure
  selector; no LLM is required for deterministic selection.
- **Transaction/idempotency:** One logical inferred contribution per source
  attempt/prerequisite pair; no propagation for partial/incorrect answers.
- **Acceptance:** Chain and diamond graphs, proposed/rejected edge exclusion,
  repeated-run identity, scarce inventory, exact budget, full provenance, and
  no direct-count/mastery-review contamination.

### 5. Schedule/event persistence and nightly processing

- **Scope:** Add the durable schedule state, projection freshness boundary,
  replay-derived last-success fields, nightly selection, and non-impact
  `REVIEW_DUE` event emission.
- **Domain contracts:** Consume the contracts from stages 1–4; do not duplicate
  engine rung transitions.
- **Pure logic:** Scheduler calls stage-2 pure functions with an explicit
  database-captured `as_of`.
- **Persistence/migration:** Additive `review_schedule` and any minimum
  projection/replay metadata. Use timezone-aware microsecond timestamps and
  indexes for learner/course/concept/due status.
- **Worker/API:** Existing Postgres jobs/CronJob infrastructure; Redis only wakes
  workers. Session-start selection consumes the final three candidates.
- **Transaction/idempotency:** Evidence, replay, schedule recomputation, and
  relevant event writes share the caller-owned transaction. Use the exact
  schedule-cycle idempotency key from F. Lock schedule/projection heads in a
  deterministic order to serialize concurrent rebuilds.
- **Acceptance:** Repeated nightly runs, late evidence, concurrent schedule
  refresh, failed transaction rollback, duplicate/conflicting event keys,
  initial one-day schedule seeding, missing/stale projection result, and no
  read-time projection revision.

### 6. Qualifying learning-event producers

- **Scope:** Connect the real answer-grading operation to v2 concept-impact event
  insertion.
- **Domain contracts:** Reuse `ConceptLearningEventInput`, source evidence/attempt
  IDs, and question concept-role snapshots. No new event type is required for the
  recommended `ANSWER_GRADED` operation.
- **Pure logic:** No event classification from display names or generic payloads.
- **Persistence/migration:** Use existing learning-event and association tables;
  any missing producer-side fields require an additive contract review.
- **Worker/API:** The actual grading/attempt operation owns the event; the current
  repository has no production implementation of that operation.
- **Transaction/idempotency:** Insert evidence, concept-impact event, projection,
  and application marker in one caller-owned transaction. Event and evidence
  retries are exact-match idempotent and conflicts fail. Require both source
  IDs and exclude the current event by those IDs during replay.
- **Acceptance:** Review clock sees real graded answers, the current attempt's
  event cannot qualify itself, unrelated earlier events remain eligible, generic
  events do not qualify, course/learner associations are correct, causation is
  preserved, and `REVIEW_DUE` remains non-impact.

### 7. Deterministic planner input/output integration

- **Scope:** Implement the pure Sprint 3.5 planner policy slice that consumes
  candidates and returns the existing decision contract.
- **Domain contracts:** Reuse `PlannerDecision`, `PlannerAction`, and
  `ReasonCode`; add only the minimum `PlanningState` and candidate contracts.
- **Pure logic:** Source first-match precedence; `REVIEW_DUE` never overrides an
  active remediation frame; no I/O, clock, or randomness.
- **Persistence/migration:** Plan version/event persistence belongs to later
  closed-loop work; this stage should consume caller-provided plan/session data.
- **Worker/API:** Caller/session orchestration invokes the pure planner; no API
  endpoint is added solely by this policy document.
- **Transaction/idempotency:** A later caller-owned plan transaction must use the
  decision's plan version and source IDs; the pure planner itself has no side
  effects.
- **Acceptance:** Hard stop/directive/remediation/review precedence, stable
  output, invalid-action rate zero, and explanation/provenance source IDs.

### 8. Integration and end-to-end acceptance

- **Scope:** Combine schedule, diagnostics, evidence, concept events, graph
  revalidation, and planner boundary in the mock profile.
- **Domain contracts:** Validate all policy versions and immutable provenance.
- **Pure logic:** Replay/order/ranking/property tests remain independent of the
  database and model provider.
- **Persistence/migration:** Upgrade from the existing schema, exercise additive
  migration and rollback guards, and verify concurrent head/schedule behavior.
- **Worker/API:** Exercise nightly due processing, session-start warm-up,
  diagnostic session state, real grading event insertion, and planner calls.
- **Transaction/idempotency:** Kill/retry at evidence, schedule, and event
  boundaries; no duplicate evidence, schedule cycle, due event, or inferred
  contribution.
- **Acceptance:** Build-spec §16.5 mandatory flow, bounded diagnostic, hidden
  weak prerequisite behavior, review warm-up, late replay, initial one-day
  review, current-attempt event exclusion, graph-version schedule provenance,
  `/plan/why` provenance, and the Phase 3 simulator scenarios.

## 7. Test and acceptance requirements

### 7.1 Pure unit/property tests

- Exact review due-date arithmetic at UTC boundary and interval transition.
- Initial one-day schedule from the first qualifying concept event, then
  post-success rung use (`1 day` followed by `3 days`), failure reset, and no
  scheduler-owned rung mutation.
- Low-mastery, overdue, and both-reason eligibility.
- Ranking groups, due-time order, mastery order, UUID tie order, duplicate
  suppression, and final maximum of three.
- Active-remediation exclusion and identical-input determinism.
- Self-report `(1, 1) -> (2, 1)` once-only replay, exact confidence `0.2`, no
  direct counters, no gate, and diagnostic pending preservation.
- Diagnostic score, stable topological/UUID ties, up-to-two question selection,
  budget 12, scarce inventories, and no repeats.
- Confirmed transitive ancestor closure on chains and diamonds, one contribution
  per source attempt/prerequisite, and proposed/rejected edge exclusion.
- Existing Beta weight, inferred-positive formula, no inferred partial/incorrect
  mutation, status precedence, and replay ordering.
- Planner precedence and pure-state determinism.

### 7.2 Persistence and integration tests

- Schedule creation, due recomputation, and failed-review re-evaluation.
- Projection freshness states for missing head, missing revision, digest mismatch,
  and graph-context mismatch.
- Same-transaction successful evidence → replay → schedule → event behavior.
- Stable due-event key on repeated nightly runs and changed key after late replay.
- Conflicting idempotency keys fail without partial state.
- `REVIEW_DUE` payload provenance and absence from concept-impact associations.
- Real graded answer → v2 concept event association and 24-hour clock behavior,
  including exclusion of the current event by source evidence/attempt ID and
  inclusion of unrelated earlier events.
- Self-report duplicate submission and conflicting assertion behavior.
- Graph version revalidation, absent concept supersession, and no split/merge/
  successor state transfer.
- Inferred evidence source-attempt/evidence/question/graph/edge provenance.
- Concurrent projection/schedule rebuild serialization and rollback.

### 7.3 End-to-end acceptance

The mandatory build-spec §16.5 sequence remains the broad regression target:

```text
register -> upload syllabus -> parse -> confirm -> graph built
-> diagnostic -> plan v1 -> lesson -> checkpoint -> quiz
-> weak prerequisite evidence -> plan v2 TEACH_PREREQUISITE
-> practice -> reassess -> RETURN_TO_TARGET -> ADVANCE_TOPIC -> /plan/why
```

Sprint 3.5 additionally requires:

- deterministic review candidate selection and maximum-three warm-up;
- active-remediation suppression;
- successful-review due recomputation from `occurred_at`;
- failed-review rung reset with immediate normal re-evaluation;
- explicit v2 concept-impact clock behavior;
- self-report prior without gate credit;
- bounded diagnostic selection and deduplicated confirmed transitive inference;
- graph-version revalidation; and
- no duplicate logical due events or inferred contributions.

## 8. Explicit Sprint 3.5 exclusions

- No replacement of Beta mastery or the approved review ladder with FSRS, BKT,
  IRT, or another model.
- No modification of Sprint 3.4 review-rung transitions, replay ordering, weight
  formulas, direct counters, or inferred-positive behavior.
- No generic event-name inference of concept impact.
- No artificial learning events created only to make reviews qualify.
- No automatic mastery/review transfer across concept split, merge, replacement,
  or successor curricula.
- No LLM-selected planner actions, arbitrary question selection, or question
  generation in the deterministic core.
- No implementation of the full later remediation, plan stack, loop guard,
  replan, dashboard, or Phase 3.6/3.7 systems beyond the minimum typed planner
  boundary needed for Sprint 3.5.
- No frontend, API, worker, migration, configuration, dependency, or source-code
  change is authorized by this document.

## 9. Remaining blockers and owner decisions

### 9.1 Policy decisions

Decisions A–M are finalized in this document as either source-preserving
interpretations or consequences of existing contracts. No explicit source
contradiction remains.

### 9.2 Implementation blockers requiring owner acknowledgment

These are not open policy choices, but implementation cannot safely begin until
the owner accepts that they require additive work:

1. **Projection review history:** the current projection lacks
   `last_successful_review_at`, `last_successful_review_evidence_id`, and
   `last_successful_review_event_id`, and the current adapter derives
   `has_qualifying_review` from status. The future replay contract must
   expose/materialize the fields defined in M.
2. **Freshness predicate:** the current repository has no public evidence-digest
   freshness result or graph-context freshness result. The minimum contract in H
   must be implemented before candidate selection can classify stale state.
3. **Schedule persistence:** `review_schedule` is named by the source but does
   not exist in the current migration set. It requires an additive schema and
   caller-owned transaction rules.
4. **Detailed candidate reasons:** current `ReasonCode` has only coarse
   `REVIEW_DUE`; the typed two-reason candidate contract is not yet present.
5. **Self-report provenance:** current mastery evidence cannot represent a
   self-report prior without incorrectly making it assessment evidence.
6. **Diagnostic provenance:** current evidence/event contracts do not contain all
   source attempt, diagnostic run, and confirmed-edge IDs required by K.
7. **Qualifying event producer:** the current repository has no production answer
   grading operation and no current producer that emits a qualifying v2 event
   with the source IDs required to exclude the current attempt during replay.
8. **Planner implementation:** `packages/planner` is a scaffold; the pure
   `PlanningState` and policy do not exist.

These blockers must be resolved through the implementation sequence after owner
review. They must not be worked around by weakening policy boundaries.

## 10. Repository and Git safety statement

- Work was performed exclusively under `/home/smsav/projects/AAAv3`.
- No `/mnt/c`, `/mnt/d`, or Windows project copy was accessed.
- Existing tracked and untracked work, including `__agent__/`, was preserved.
- `docs/SPRINT_3_5_ASSESSMENT.md` was read but not modified.
- `AAA_v3_BUILD_SPEC.md`, `agents.md`, existing ADRs,
  `docs/SPRINT_3_4_POLICY_DECISIONS.md`, `docs/SPRINT_3_4.md`, source code,
  tests, migrations, and configuration were not modified.
- No dependency, migration, Docker volume, data, staging operation, commit,
  reset, clean, stash, revert, or history rewrite was performed.
- The referenced `AAA_v3_COMPLETE_BUILD_PLAN.md` remains absent and was not
  substituted.
- The only intended file created by this task is
  `docs/SPRINT_3_5_POLICY_DECISIONS.md`.

## 11. Final status

Sprint 3.5 policy decisions A–M are finalized for owner review. The source-
specified rules remain distinct from Sprint 3.4 finalized policy and the
owner-approved interpretations selected here. The proposed implementation
sequence is safe as a future sequence, provided the listed additive contracts,
projection-history fields, schedule persistence, qualifying event producer, and
pure planner are implemented without changing the existing replay and graph
provenance rules.

Sprint 3.5 is **not implementation-ready in the current checkout** because the
implementation blockers in §9.2 remain. No source implementation, migration,
staging, or commit was performed. Owner review is required before any
implementation begins.
