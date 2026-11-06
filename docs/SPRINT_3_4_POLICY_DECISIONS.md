# Sprint 3.4 policy decisions: Beta mastery and atomic evidence

## Decision status

This document retains the previously finalized Sprint 3.4 decisions and records
the final owner-approved consistency audit. The revised replay tie-breaker,
two-component weighting, zero-based review-rung rules and 24-hour event-clock
boundary are **FINALIZED INTERPRETATIONS** for Sprint 3.4. Implementation may
begin after the remaining confirmations in Section 5. This is documentation
only; all previously finalized policies remain in force, Sprint 3.4
implementation has not started, and Sprint 3.5 remains deferred.

The labels below distinguish source provenance from the finalized decisions:

- **SPECIFIED** — directly stated by an authoritative source.
- **FINALIZED INTERPRETATION** — a policy decision finalized for Sprint 3.4 by
  the clarification instruction, but not claimed to be stated by the source.
- **DERIVED** — follows mechanically from specified rules or a finalized
  interpretation.
- **IMPLEMENTATION CONTRACT REQUIRED** — the policy is closed, but an additive
  domain/persistence contract absent from the current repository must be added
  before the behavior can be implemented.
- **UNRESOLVED** — still requires source-level confirmation before it can be
  implemented safely.

No **FINALIZED INTERPRETATION** is attributed to the build specification.

---

## 1. Purpose and scope

Sprint 3.4 will implement the v1 Beta mastery model and a transactionally
reliable evidence-application pipeline. This document distinguishes settled
policy from the remaining choices needed for an implementation-ready contract:

- immutable evidence and immutable question/weight metadata;
- chronological replay for late evidence;
- deterministic Beta updates, partial credit and weakest-link attribution;
- mastery status classification;
- direct-attempt and distinct-question counting;
- review-success state transitions without implementing a scheduler;
- inferred-evidence boundaries;
- graph-version and stable-concept identity;
- caller-owned atomic transactions, idempotency and replay.

The following remain outside Sprint 3.4:

- nightly review selection and due-item jobs;
- review scheduling and planner insertion;
- diagnostic item selection;
- planner rules, remediation frames and replanning;
- assessment generation or grading;
- frontend mastery dashboards;
- real LLM integrations;
- Sprint 3.5 or later work.

Sprint 3.4 may persist review-success and interval-rung metadata and apply the
mastery-side transitions defined here. Scheduling, nightly selection and
planner insertion remain Sprint 3.5 scope.

---

## 2. Source-defined behavior

### 2.1 Source hierarchy and availability

The source hierarchy for this document is:

1. Explicitly approved project-owner clarification decisions, including the
   replay, weighting, rung, review-clock, timestamp and source-context
   interpretations in Sections 3–5.
2. `AAA_v3_BUILD_SPEC.md`, the checked-out build specification.
3. `agents.md`, the agent-executable copy of the same specification referenced
   by `CLAUDE.md`.
4. Accepted ADRs, especially `docs/decisions/0007-beta-mastery.md`.
5. Sprint 3.1–3.3 reports, contracts, persistence code and tests, used to
   preserve established boundaries and terminology.

`AAA_v3_COMPLETE_BUILD_PLAN.md` was not available in the WSL checkout. It is
not substituted silently; this absence remains recorded as a source limitation.

The existing `packages/mastery` directory is a scaffold only. It contains no
mastery engine, persistence model or implementation behavior to preserve.

### 2.2 Beta model: `mastery_v1`

`AAA_v3_BUILD_SPEC.md`, Section 6.1 “Mastery engine,” explicitly defines:

- policy version `mastery_v1`;
- per-student/per-concept state fields `alpha`, `beta`, `updated_at`,
  `n_direct` and `review_successes`;
- prior `alpha0=1`, `beta0=1`;
- `n_eff = alpha + beta - 2`;
- `mastery = alpha / (alpha + beta)`;
- `confidence = n_eff / (n_eff + 4)`, where confidence is evidence mass and
  not LLM self-reporting.

The same section defines the following weights:

| Factor | Explicit source rule |
|---|---|
| Correct difficulty | 0.7 for difficulty 1–2; 1.0 for 3; 1.3 for 4–5 |
| Incorrect difficulty | 1.3 for difficulty 1–2; 1.0 for 3; 0.7 for 4–5 |
| MCQ correct type | `0.6 * (1 - 1/n_options)` |
| TRUE/FALSE | 0.4 |
| NUMERIC | 1.0 |
| SHORT_TEXT | 0.9 |
| CODE/tests | 1.2 |
| L2 rubric | Type factor multiplied by `grader_confidence`; numeric base was not stated by the source and is finalized below |
| Correct hints | 1.0 for zero hints; 0.5 for one; 0.25 for two or more |
| Tag confidence | `tag_confidence` clipped to `[0.5, 1.0]` |
| Primary concept role | 1.0 |
| Prerequisite concept role | 0.5 |

**SPECIFIED:** the hint factor applies to correct evidence only. **DERIVED:**
the incorrect component has the multiplicative identity `1` for hints. The
finalized interpretation in Section 4.1 does not reuse the correct-only hint
penalty on negative mass.

### 2.3 Attribution and partial credit

The source explicitly defines:

- correct attribution: `alpha += w * role` for each tagged concept;
- incorrect attribution: split total negative mass `w` proportionally to
  `role * (1 - mastery_i)`, then add each share to `beta`;
- partial credit `c` in `(0,1)`: apply `c` as correct and `1-c` as incorrect;
- negative shares must conserve total negative mass;
- inferred positive evidence: `alpha += 0.3 * w * role`, flagged and excluded
  from `n_direct` and `MASTERED`.

The source's generic base-weight notation is:

`w = w_diff * w_type * w_hint * w_tag`

The source does not explicitly require the same numerical `w` for both sides of
a partial-credit answer. It supplies different correct/incorrect difficulty
weights and a correct-only hint factor. The earlier statement `c*w*role` and
`(1-c)*w` with one shared numerical weight was therefore ambiguous, not an
explicit source requirement. The owner-approved resolution is the separate
`w_correct` and `w_incorrect` calculation in Section 4.1.

The source's MCQ wording qualifies its formula with “on correct” and therefore
does not explicitly define the incorrect MCQ type factor. The owner-approved v1
interpretation in Section 4.1 uses the same source-defined MCQ factor for both
positive and negative components; this is not attributed to the source.

### 2.4 Lazy forgetting

The source explicitly defines:

`H = min(180 days, 21 days * 1.6^review_successes)`

and applies the following transformation lazily on read/update to both
posterior parameters:

`parameter := prior + (parameter - prior) * 2^(-dt / H)`

The source defines the formula but did not define the timestamp ordering for
late evidence. Chronological replay, the approved UUID tie-breaker and the
fixed-time replay comparison are finalized in Section 3.1.

### 2.5 Explicit status thresholds

The source-defined thresholds are:

- `UNASSESSED` when `n_eff < 1`;
- `WEAK` when `mastery < 0.5` and `confidence >= 0.3`;
- `PROFICIENT` when `mastery >= 0.75`, `n_direct >= 3`, at least two distinct
  question UUIDs contributed direct evidence, and `confidence >= 0.5`;
- `MASTERED` when `PROFICIENT` and at least one qualifying successful review
  answered at least 24 hours after the last learning event.

The source names `DEVELOPING` but does not state its predicate. The final
catch-all interpretation appears in Section 3 and is not attributed to the
source.

### 2.6 Spaced-review state rules

Section 6.2 of the build specification explicitly defines the interval ladder
`[1, 3, 7, 14, 30, 60]` days, says a pass advances at `review_successes`, and
says a failure resets to rung zero and applies ordinary negative evidence.
Nightly review selection and planner insertion are later behavior and remain
deferred to Sprint 3.5.

The exact wording is “Pass at `review_successes` -> next rung; fail -> reset to
rung 0 and apply normal negative evidence.” It does not define the initial rung,
zero-based array indexing, a pre-first-review sentinel, the capped index or
whether the selected interval is read before or after a transition. ADR 0007
adds no indexing rule. Section 4.2 records the owner-approved details; no
explicit source conflict was found.

The source does not define the review marker, pass threshold, partial-credit
review behavior, repeated-review identity or the exact event used as the
24-hour anchor. The final Sprint 3.4 interpretations are explicit in Section
3 and the remaining timestamp, audit and contract questions are in Section 5.

### 2.7 Identity, event and transaction boundaries

Sprint 3.2 contracts and `docs/SPRINT_3_2.md` explicitly define:

- `actor_id` as the authenticated actor and `learner_id` as the affected
  learner;
- explicit authorization for actor-to-other-learner operations;
- `occurred_at` as a trusted, timezone-aware domain occurrence timestamp,
  normalized to UTC;
- `recorded_at` as a database-clock recording timestamp;
- caller-owned event insertion with no internal commit;
- idempotent identical event replay and explicit conflict for different event
  content;
- deterministic event reads ordered by occurrence time, recording time and
  event ID.

**SPECIFIED implementation context:** `LearningEventInput` accepts an aware
`occurred_at`; `LearningEventV1` adds an aware `recorded_at`.
`insert_learning_event()` assigns the latter from PostgreSQL
`clock_timestamp()`. `list_learning_events()` orders reads by occurrence time
(recording time for legacy rows without occurrence time), recording time and
event ID. This is a generic event-read contract, not a mastery replay algorithm.
Neither it nor ADR 0007 assigns `recorded_at` mathematical learning-order
semantics. Changing the approved mastery ordering does not require changing
this existing audit read contract.

**SPECIFIED:** build-spec Section 5.5 “Evidence” describes `applied_at` as
“set when mastery update committed.” It is not the occurrence timestamp or
the generic event recording timestamp. The source does not define a database
commit-timestamp mechanism, precision, or what happens to this marker on a
later historical rebuild; Section 5, item 5 retains those questions.

Sprint 3.2 explicitly anticipates one future transaction combining evidence,
mastery updates and learning-event persistence. Sprint 3.4 adopts that
caller-owned boundary.

### 2.8 Graph and concept identity

Sprint 3.1 and Sprint 3.3 explicitly define immutable graph versions bound to
course and curriculum revision identities, stable concept UUIDs, preserved
history and confirmed-edge provenance. They do not define mastery reset or
transfer behavior across graph versions. The finalized stable-concept policy
is recorded in Section 3.

---

## 3. Finalized v1 policy decisions

This section retains previously finalized decisions and records the owner-approved
replay, weighting, rung and review-clock interpretations. Section 4 records
those interpretations with their source distinctions; Section 5 retains the
remaining implementation blockers rather than treating them as source text.

### 3.1 Chronological evidence replay

**FINALIZED INTERPRETATION:** retain immutable evidence, deduplicate it, rebuild
affected mastery from the prior chronologically, apply forgetting between
evidence times, and project to current PostgreSQL time. Arrival-time mutation
is not the selected policy.

**Consistency finding:** the previous finalized tuple
`(occurred_at, recorded_at, evidence UUID)` can order simultaneous occurrences
differently when arrival order changes. Sequential weakest-link attribution and
review transitions need not commute, even when the time gap is zero. Therefore
that tuple and unconditional arrival-order independence cannot both stand.

**FINALIZED INTERPRETATION:** use `(occurred_at, evidence UUID)` for mathematical
mastery replay. Keep `recorded_at` exclusively for audit, ingestion chronology
and diagnostics. No inspected source explicitly requires mastery to use the
generic learning-event listing order. This owner decision changes mastery replay
only; it does not change Sprint 3.2's existing event-read contract.

The reconciled replay algorithm is:

1. Retain the immutable evidence record, including original occurrence and
   recording timestamps, question metadata, graph version, concept-role
   snapshot and exact weight snapshot.
2. Deduplicate evidence before replay.
3. Rebuild the affected learner/concept mastery state from the Beta prior.
4. Order mastery-applicable evidence by:
   1. `occurred_at` ascending;
   2. evidence UUID ascending as the deterministic tie-breaker, comparing the
      UUID's 128-bit value (equivalently its canonical fixed-width hexadecimal
      representation). Preserve UUIDs across retries and replay.
5. Apply lazy forgetting between chronological evidence timestamps.
6. Apply each evidence contribution using its immutable original metadata.
7. Project the resulting state forward to a single captured current PostgreSQL
   database time `as_of` for this rebuild, supplied to the pure engine.
8. Persist the rebuilt state and audit metadata in the same caller-owned
   transaction as evidence/contribution/event changes.

**Desired invariant:** the same immutable evidence set must produce the same
mathematical mastery state regardless of evidence arrival order. **DERIVED
qualification:** compare at the same `as_of` instant and with the same policy
and immutable learning metadata/UUIDs. Projections at different database times
can legitimately differ because of forgetting; audit timestamps and original
application receipts can also differ. Arrival-independent posterior, counts,
status and review state do not imply identical ingestion metadata.

For equal occurrence times, the approved UUID order is a reproducible tie-break,
not evidence of real causal order. The decay interval between tied records is
zero. `recorded_at`, `applied_at`, SQL insertion order and query-plan order must
not break mathematical ties. Inferred partial/incorrect records remain in the
audit ledger but are excluded from contribution replay under Section 3.5.

Implementation implications:

- replay must be deterministic; capture the projection time outside the pure
  engine using PostgreSQL, not an application-clock read inside the engine;
- duplicate filtering must occur before decay or contribution calculation;
- weakest-link allocation couples all concepts tagged by an evidence item.
  **DERIVED:** rebuilding one concept independently with current neighbor
  masteries is not equivalent to chronological replay. Reconstruct all co-tagged
  concept states needed at every affected historical event, including downstream
  coupled events, or replay the relevant learner history together;
- review-success and interval-rung transitions must be replayed in the same
  chronological order as evidence;
- current-state reads must project from the latest replay point to the current
  PostgreSQL time without deleting historical evidence;
- concurrent applications must serialize or retry so one replay cannot lose
  another accepted evidence item.

Historical contribution shares and review qualification can change after a late
insert, although raw evidence and weight/role snapshots stay immutable. Section
5, item 3 retains the audit-versioning question for these recomputed results.
Replay must never reinterpret old evidence using a newer graph's roles or edges.

Arrival-time update was an alternative in the original assessment, not the
selected recommendation. Chronological replay and the UUID tie-breaker are now
owner-approved interpretations.

### 3.2 Mastery status classification

**FINALIZED INTERPRETATION:** evaluate statuses in this order:

1. `UNASSESSED` if `n_eff < 1`.
2. `WEAK` if `mastery < 0.5` and `confidence >= 0.3`.
3. `MASTERED` if all `PROFICIENT` conditions hold and a qualifying successful
   review exists.
4. `PROFICIENT` if `mastery >= 0.75`, `n_direct >= 3`, at least two distinct
   question UUIDs contributed direct evidence and `confidence >= 0.5`.
5. `DEVELOPING` for every remaining valid mastery state.

The first four threshold values are **SPECIFIED** by the source. The
catch-all `DEVELOPING` rule and the precedence that checks `MASTERED` before
`PROFICIENT` are finalized interpretations. No additional thresholds are
introduced.

| First matching condition for a valid state | Result | Provenance |
|---|---|---|
| `n_eff < 1` | UNASSESSED | SPECIFIED threshold |
| Otherwise, `mastery < 0.5` and `confidence >= 0.3` | WEAK | SPECIFIED thresholds |
| Otherwise, all proficiency gates and qualifying successful review | MASTERED | SPECIFIED gates; finalized review interpretation |
| Otherwise, all proficiency gates | PROFICIENT | SPECIFIED thresholds |
| Otherwise | DEVELOPING | FINALIZED INTERPRETATION |

Absence of a qualifying review leaves an otherwise proficient state
`PROFICIENT`, not `DEVELOPING`. Low confidence may prevent `WEAK` or
`PROFICIENT`; no extra low-confidence threshold is introduced. Derived
confidence must agree with `n_eff`, rather than being supplied independently.

### 3.3 Direct counts and distinct questions

**FINALIZED INTERPRETATION:**

- Every accepted, unique `DIRECT` evidence attempt increments `n_direct`.
- Distinct direct question UUIDs are tracked independently for the proficiency
  requirement.
- Repeated attempts with the same question UUID count as separate direct
  attempts when their evidence IDs are distinct and accepted.
- Duplicate evidence replay does not increment `n_direct` or the distinct
  question set.
- `INFERRED` evidence never increments `n_direct` and never contributes to the
  distinct-direct-question count.

This preserves independent meaning for the source's `n_direct >= 3` and
“at least two distinct questions” conditions.

### 3.4 Review metadata and success

**FINALIZED INTERPRETATION:** the relevant immutable question/attempt metadata
must include `is_review`. The value must be copied into the immutable evidence
snapshot used for replay; later question edits cannot change historical review
classification.

A qualifying successful review requires all of the following:

- immutable `is_review=true`;
- `kind=DIRECT`;
- `correct == 1.0`;
- occurrence time at least 24 hours after the previous persisted learning event
  that is explicitly classified as affecting the relevant concept for the
  relevant learner, using chronological `occurred_at` timestamps;
- a unique accepted evidence occurrence.

**FINALIZED INTERPRETATION — 24-hour event boundary:** the comparison includes
all persisted learning events explicitly classified as affecting the relevant
learner and stable concept, not merely assessment evidence. It excludes
operational events, job lifecycle events, authentication events, administrative
actions and unrelated course events. An inferred event may affect the timeline
only when its event type and payload explicitly establish that concept impact;
the inferred evidence record itself still cannot qualify as a successful review.

The repository audit found no currently qualifying event type. The authoritative
enum in `packages/domain/enums.py:41-67` names assessment/learning candidates
(`DIAGNOSTIC_COMPLETED`, `CHECKPOINT_ANSWERED`, `ANSWER_SUBMITTED`,
`ANSWER_GRADED`, `MASTERY_UPDATED` and `MISCONCEPTION_DETECTED`), but it does
not classify any as concept-affecting. The v1 envelope in
`packages/domain/events.py:42-71` has optional learner/course IDs and a generic
payload, but no concept ID or concept-impact field. The legacy envelope in
`packages/domain/models.py:146-158` likewise has no concept-association
contract. `list_learning_events()` filters only learner/course and orders by
occurrence, recording time and event UUID (`packages/persistence/learning_events.py:161-184`).

The current v1 producers emit only course/graph/review events:
`CURRICULUM_CONFIRMED` (`packages/persistence/review.py:367-384`),
`GRAPH_BUILT` (`packages/persistence/graphs.py:289-308`),
`PREREQUISITE_EDGE_CONFIRMED` or `PREREQUISITE_EDGE_REJECTED`
(`packages/persistence/graphs.py:444-456`), and
`CURRICULUM_SUCCESSOR_CREATED` (`packages/persistence/successors.py:110-123`).
The legacy document-upload producer also inserts `SYLLABUS_UPLOADED`
(`apps/api/documents/service.py:121-129`). Their payloads contain course,
document, graph, revision, edge or successor identifiers, not a learner/concept
association, so none qualifies for the review clock.
`ANSWER_GRADED` appears in event fixtures (`tests/integration/test_identity_events_runtime.py:34-52`)
but has no current production producer or concept-association contract.

Therefore the owner-approved boundary is precise, but its implementation is
blocked until the event taxonomy provides an explicit concept-affecting
classification and a reliable learner/concept association. Sprint 3.4 must not
approximate this boundary with assessment evidence alone.

An inferred evidence record cannot qualify as a successful review. A direct
review attempt below full credit is unsuccessful: apply its ordinary evidence
contribution and reset that concept's review interval rung to zero. A direct
full-credit successful review increments `review_successes` exactly once and
advances the interval rung once, capped at the final ladder rung.

The interval ladder is `[1, 3, 7, 14, 30, 60]` days. `review_successes` and
the interval rung remain separate state variables. **FINALIZED INTERPRETATION:**
represent `review_rung` as a zero-based index into this ladder:

- initial rung is `0`;
- a qualifying success advances to `min(current_rung + 1, 5)`;
- a failed direct review resets the rung to `0`;
- the selected interval is `ladder[review_rung]`;
- rung `5` is the capped 60-day interval.

Initial rung `0` represents the first one-day interval, not a pre-first-review
sentinel. A successful first review therefore advances from the one-day rung to
rung `1` (three days), and no first interval is skipped. `review_successes`
remains cumulative and independent of the rung; failed reviews do not decrement
it. The source defines the ladder and reset/advance terms but not index
semantics; the zero-based interpretation is owner-finalized here.

For the boundary case of an inferred record with `is_review=true`, the record
is not a qualifying review and does not advance the rung. The explicit positive
inferred alpha rule still applies to an inferred positive record. Inferred
partial or incorrect records follow Section 3.5 and do not mutate mastery.
This is a finalized interpretation needed to keep “DIRECT required” and
“inferred cannot qualify” consistent; it is not claimed as source text.

Sprint 3.4 owns these mastery-side state transitions. Review scheduling,
nightly due-item selection and planner insertion remain Sprint 3.5.

### 3.5 Inferred evidence

**SPECIFIED:** apply the positive inferred contribution
`0.3 * w * role` to alpha. Inferred evidence remains flagged, never increments
direct counts and cannot satisfy `MASTERED` eligibility. Under the finalized
two-component weighting, the positive inferred weight uses `w_correct`.

**FINALIZED INTERPRETATION:**

- inferred positive evidence mutates alpha and therefore the derived mastery,
  effective sample size and confidence when it uses the shared posterior;
- inferred evidence remains fully auditable and replayable;
- no beta update or partial-credit rule is invented for inferred evidence;
- inferred partial or incorrect evidence is retained with an auditable
  unapplied state/reason and does not mutate mastery under this Sprint 3.4
  policy;
- such unapplied inferred evidence does not affect status, confidence,
  `n_direct`, distinct-direct-question count, review success or interval rung.

For a full-credit inferred positive under the finalized weighting, the
contribution is therefore
`0.3 * w_correct * role`. There is no `w_incorrect` inferred contribution.

The audit-only treatment of inferred partial/incorrect evidence is a finalized
Sprint 3.4 boundary, not a claim that the build specification defines it.

### 3.6 Zero negative-mass denominator

The ordinary weakest-link formula remains:

`share_i = negative_mass * role_i * (1 - mastery_i) / sum(role_j * (1 - mastery_j))`

where `negative_mass` is `w_incorrect` for fully incorrect evidence or
`(1-c)*w_incorrect` for partial credit under the finalized two-component
weighting.

**FINALIZED INTERPRETATION:** if the denominator is zero, use normalized
concept role weights as the fallback:

`share_i = negative_mass * role_i / sum(role_j)`

The fallback is used only for the zero-denominator case. The ordinary
weakest-link allocation is unchanged. The fallback preserves total negative
mass exactly and is deterministic. If the role-weight denominator is also zero
or the concept set is empty, the evidence is invalid and the caller-owned
transaction must roll back; no partial mutation is allowed.

This replaces the earlier assessment's reject-as-invalid recommendation for the
weakest-link denominator.

### 3.7 L2 rubric weight

**FINALIZED INTERPRETATION:** use an L2 rubric base of `1.0`, so:

`w_type(L2 rubric) = 1.0 * grader_confidence`

All other source-defined type weights remain unchanged. This is a finalized
numeric interpretation of the source phrase “L2 rubric × grader_confidence,”
not a claim that the source printed the numeric base.

### 3.8 Graph version and stable concept identity

**FINALIZED INTERPRETATION:**

- key mastery by learner identity and stable concept UUID, not by graph version;
- preserve the graph version and concept-role snapshot used when evidence was
  generated;
- continue mastery for unchanged stable concept UUIDs across graph versions;
- do not automatically transfer mastery when concepts are split, merged or
  replaced;
- initialize new concepts from the specified Beta prior;
- retain historical evidence and mastery for concepts absent from the current
  graph.

Historical replay uses the immutable evidence snapshot and its original graph
version/concept-role context. A current learner query must be explicit about
whether it requests current-graph concepts or historical concepts.

### 3.9 Idempotency and transaction behavior

**FINALIZED INTERPRETATION:**

- apply each evidence ID at most once;
- exact replay with identical immutable evidence metadata returns the existing
  logical result without changing alpha, beta, counts, review state, rung,
  contributions or events;
- reuse of an evidence ID or idempotency key with conflicting immutable
  metadata fails explicitly;
- evidence persistence, contribution rows, mastery updates, review-state
  changes, applied markers and the corresponding learning event are one
  caller-owned transaction;
- a failure rolls back all of those changes together;
- actor identity and affected learner identity remain distinct and authorization
  is checked before applying evidence;
- duplicate filtering happens before chronological replay.

The immutable conflict comparison must include learner, course, question,
attempt, correctness, grader metadata, hint count, evidence kind, occurrence
time, graph version, concept-role snapshot, review marker and exact question/
weight metadata. `recorded_at` and `applied_at` are server-side timestamps and
are not conflated with evidence occurrence identity.

---

## 4. Owner-approved interpretations for underspecified behavior

The following interpretations are finalized for Sprint 3.4. Their source
distinctions remain explicit: an owner-approved interpretation is not silently
recast as a source-defined rule.

### 4.1 Finalized two-component partial-credit weighting

**FINALIZED INTERPRETATION:** because the source gives different
difficulty weights for correct and incorrect evidence and says the hint factor
applies only to correct evidence, calculate separate component weights:

```text
w_correct = correct_difficulty_weight
             * type_weight
             * correct_hint_factor
             * tag_confidence

w_incorrect = incorrect_difficulty_weight
               * type_weight
               * tag_confidence

positive_mass = c * w_correct
negative_mass = (1-c) * w_incorrect
```

For MCQ evidence, use `0.6 * (1 - 1/n_options)` as `type_weight` for both
components. This same-factor treatment for incorrect MCQ evidence is an
owner-approved v1 interpretation; the source labels its MCQ formula “on
correct” and does not explicitly define the incorrect case. TRUE/FALSE, NUMERIC,
SHORT_TEXT and CODE/tests retain their source-defined type weights.

Then apply positive mass using primary/prerequisite role weights and allocate
negative mass using:

```text
share_i = negative_mass
          * role_i * (1 - mastery_i)
          / sum(role_j * (1 - mastery_j))
```

Use the finalized normalized-role fallback from Section 3.6 when that
weakest-link denominator is zero. The correct-only hint multiplier is never
applied to `w_incorrect`. For fully correct evidence, `c=1` leaves no negative
component; for fully incorrect evidence, `c=0` leaves no positive component.

The source does not explicitly print these two formulas as separate partial
components. It does explicitly print separate correct/incorrect difficulty
weights and a correct-only hint rule. This is therefore an owner-approved
policy interpretation, not a source-defined formula. The same MCQ factor for
negative mass is likewise owner-approved and is not claimed as source text.

### 4.2 Finalized zero-based review-rung indexing

**FINALIZED INTERPRETATION:** use `review_rung` as a zero-based array
index into `[1,3,7,14,30,60]`:

| State/transition | Finalized result |
|---|---|
| Initial | `review_rung=0`, selecting 1 day |
| Qualifying success | `min(review_rung + 1, 5)` |
| Failed direct review | `review_rung=0` |
| Maximum | `review_rung=5`, selecting 60 days |

The initial state is the first one-day interval, not a state before the first
interval. The first successful review therefore advances from index 0 to index
1; it does not skip the one-day interval. `review_successes` is cumulative and
independent of `review_rung`.

C is consistent with the ladder and “reset to rung 0” wording but is not
explicitly defined by the source. It is owner-finalized here. Scheduling and
nightly selection remain deferred.

### 4.3 Replay, partial-credit and rung decision register

| Decision | Current document treatment | Status |
|---|---|---|
| Mathematical replay order | `occurred_at`, evidence UUID; `recorded_at` audit-only | FINALIZED INTERPRETATION — owner-approved A |
| Partial correct/incorrect weights | `w_correct` and `w_incorrect` as in Section 4.1 | FINALIZED INTERPRETATION — owner-approved B |
| Zero-denominator fallback | Normalized role weights | FINALIZED INTERPRETATION from prior owner clarification |
| Review rung index | Zero-based ladder index as in Section 4.2 | FINALIZED INTERPRETATION — owner-approved C |
| `review_successes` | Cumulative and independent of rung | FINALIZED INTERPRETATION from prior owner clarification |

Acceptance requirements depending on A, B and C are now unconditional. The
stable source-defined formulas and all previously finalized decisions remain
unchanged.

| Topic | Finalized interpretation | Source distinction |
|---|---|---|
| Late evidence | Chronological replay from prior, then projection to current DB time | The source defines decay but not late-event ordering |
| Replay order | `occurred_at`, evidence UUID; `recorded_at` audit-only | FINALIZED INTERPRETATION — Sprint 3.2's recorded-time event read order remains unchanged |
| `DEVELOPING` | Catch-all valid state | The source names the status but gives no predicate |
| Status precedence | `MASTERED` before `PROFICIENT` | `MASTERED` includes `PROFICIENT`; explicit precedence is interpreted |
| Direct count | Every unique direct evidence attempt | The source gives `n_direct` and a distinct-question gate but not counting mechanics |
| Review marker | Immutable `is_review` metadata copied into evidence | Existing `Question`/`AnswerEvidence` contracts do not contain it |
| Review pass | Direct, full-credit, delayed by 24h occurrence time | The source gives 24h and successful review, not the full predicate |
| Review failure | Direct review below full credit applies ordinary evidence and resets rung | The source says fail resets but does not define fail |
| Review counter identity | One increment per qualifying unique evidence occurrence | The source does not define the review-episode key |
| Inferred partial/incorrect | Audit-only, no mastery mutation | The source defines inferred positive alpha only |
| Zero denominator | Normalize by role weights | The source assumes a positive weakest-link denominator |
| L2 base | `1.0 * grader_confidence` | The source omits the numeric base |
| Partial weights | `w_correct`/`w_incorrect` and separate positive/negative masses, including the same MCQ factor on both components | FINALIZED INTERPRETATION — source gives component factors but not this combined formula or incorrect-MCQ application |
| Review rung | Zero-based index; initial index 0 means 1 day; cap 5 | FINALIZED INTERPRETATION — source gives ladder and reset/advance but not indexing |
| Graph continuity | Stable UUID continuity; no automatic split/merge/replace transfer | Graph sources do not define mastery transfer |

These entries record the policy decisions supplied by the project owner while
preserving explicit source distinctions for behavior not present or not fully
specified in the source.

---

## 5. Implementation contracts required before implementation

A, B and C and the review-clock boundary are owner-approved. The following
contract additions are required before implementation because the current
repository does not yet contain the necessary authoritative fields or tables.

1. **Future occurrence timestamps — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** Sprint 3.2 defines `occurred_at` as a
   trusted, timezone-aware timestamp normalized to UTC, while `recorded_at` is
   assigned by the database (`packages/domain/events.py:56-91`). Sprint 3.4
   evidence acceptance must capture a validation timestamp with PostgreSQL
   `clock_timestamp()` in the caller-owned session and reject
   `occurred_at > validation_db_at`. Equality is accepted. No clock-skew
   allowance is introduced. The pure replay engine receives only already
   validated evidence. The evidence occurrence and immutable event metadata are
   part of the idempotency comparison, so an exact retry preserves the original
   `occurred_at`; a retry with a different occurrence conflicts.

   This future-date rejection applies to the new mastery-evidence and
   concept-affecting-event contracts. Existing generic Sprint 3.2 event
   insertion does not currently perform this validation and must not be silently
   changed; legacy/generic events cannot become qualifying concept events
   without the explicit contract in item 8.

2. **Late-evidence age — FINALIZED INTERPRETATION plus DERIVED behavior:** no
   maximum evidence age is imposed. Evidence is accepted when it passes the
   future-date, source-context, authorization, idempotency and other validation
   rules, regardless of age. Late evidence triggers deterministic replay from
   immutable evidence and original metadata using `(occurred_at, evidence UUID)`
   and a captured PostgreSQL `as_of`. Operational replay cost is separate from
   evidence acceptance. Optimization, replay checkpoints and projection
   acceleration are implementation work, not hidden age rejection rules.

3. **Historical projection versioning — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** the current repository has no mastery or
   projection tables; existing migrations use additive PostgreSQL source-of-truth
   tables (`alembic/versions/0006_learning_identity_events.py` and
   `0007_learning_graph_versions.py`). Sprint 3.4 may add the following minimal
   immutable projection revision row, without introducing event sourcing or a
   second source of truth:

   | Projection field | v1 contract |
   |---|---|
   | `projection_id` | Immutable UUID primary key |
   | `learner_id` | Internal learner identity UUID; required |
   | `course_id` | Course UUID; required because v1 evidence/question/graph context is course-scoped |
   | `stable_concept_id` | Stable concept UUID; retained even though no global concept table currently exists |
   | `projection_version` | Monotonic positive revision per learner/course/concept key |
   | `policy_version` | `mastery_v1` |
   | `as_of` | Captured PostgreSQL projection time |
   | `replayed_at` | PostgreSQL `clock_timestamp()` at the durable projection-write operation, not literal commit time |
   | `evidence_set_digest` | Digest of the canonical ordered immutable evidence IDs and snapshot identities included in the rebuild |
   | `evidence_count` and replay boundary | Count plus maximum included occurrence/evidence UUID boundary for reproducibility |
   | `alpha`, `beta`, `n_eff`, `mastery`, `confidence`, `status` | Materialized mastery result |
   | `review_successes`, `review_rung` | Materialized review state |
   | `created_at` | PostgreSQL-generated row creation timestamp |
   | `rebuild_reason` | Controlled value such as initial apply, late evidence replay or current-time projection |

   A small projection-head row keyed by learner/course/concept identifies the
   current `projection_id` and current `projection_version`. Historical rows
   remain queryable by projection ID or revision. Each successful rebuild that
   changes the logical projection, evidence-set digest, replay boundary or
   `as_of` creates a new immutable revision and atomically advances the head.
   An exact idempotent replay with the same evidence digest, policy, `as_of` and
   materialized state returns the existing revision without creating another
   row. A failed rebuild changes neither the head nor the last valid revision.
   Concurrent rebuilds lock the head for the affected key and allocate the next
   monotonic revision in the caller-owned transaction. The evidence digest and
   immutable evidence snapshots keep the revision auditable without making the
   projection table a second source of truth.

4. **Question, attempt, graph and authorization validation — FINALIZED
   INTERPRETATION plus IMPLEMENTATION CONTRACT REQUIRED:** the current
   `Question` contract (`packages/domain/models.py:105-127`) has question/course/
   concept fields and status but no version, availability timestamp, graph
   context or `is_review`. `AnswerEvidence` (`packages/domain/models.py:129-143`)
   has no occurrence time, course, graph version or immutable review snapshot.
   There is no persisted question-version or answer-attempt model/table in the
   repository. `CurriculumGraphVersion.published_at` is the authoritative graph
   publication field (`packages/persistence/models.py:305-357`), and graph
   reads require the exact graph/course pair (`packages/persistence/graphs.py:338-370`).
   Course authorization currently checks the existence of a `CourseMember`
   (`packages/persistence/models.py:62-72`, `packages/persistence/repositories.py:17-30`);
   authentication resolves the actor identity from the bearer subject
   (`apps/api/auth/dependencies.py:65-79`).

   The minimum additive attempt/source contract is:

   - an immutable question-version record with `question_version_id`, stable
     question/course/concept context, `is_review` and an authoritative
     availability timestamp; the timestamp does not currently exist and must be
     added rather than guessed;
   - an immutable attempt record with `attempt_id`, learner identity,
     `question_version_id`, course, exact graph-version ID, attempt occurrence
     timestamp and copied `is_review`; the attempt timestamp also does not
     currently exist;
   - evidence fields/snapshot containing the originating attempt,
     question-version, learner, course, graph-version, occurrence timestamp and
     copied review marker.

    Validation occurs at two operation boundaries. At attempt creation, verify
    the immutable question version exists and is available, the graph exists for
    the course with `status=PUBLISHED` and non-null `published_at`, the actor is
    authorized for the course/learner, and `graph.published_at <=
    attempt_occurred_at`. At evidence submission,
   verify the attempt/question relationship, learner equality, exact course and
   graph context, immutable review-marker equality, `attempt_occurred_at <=
   evidence.occurred_at`, `graph.published_at <= evidence.occurred_at`, and
    `evidence.occurred_at <= validation_db_at`. Current membership and explicit
    actor-to-learner authorization are checked before the caller-owned write;
    the existing repository only checks membership existence and does not define
    role permissions or delegated-learner authorization. Self-submission can use
    the resolved actor/learner identity; delegated submission requires an
    additive authorization contract within Sprint 3.4 rather than an assumed
    role meaning.

   Historical replay does not recheck current membership, question status,
   graph publication or authorization. It uses the accepted immutable snapshots
   and their original graph/question/attempt metadata. No timestamp absent from
   the repository is treated as authoritative until the required question-
   version and attempt contracts add it.

5. **Application and replay timestamps — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** the meanings are distinct:

   | Timestamp | Meaning and source |
   |---|---|
   | `occurred_at` | Original domain occurrence supplied by the trusted caller, normalized to UTC and preserved across retries/replay |
   | `recorded_at` | Database ingestion/recording time assigned by PostgreSQL `clock_timestamp()`; audit chronology only |
   | `applied_at` | PostgreSQL database-clock time at the successful application-marker write inside the caller-owned transaction; durability occurs only if that transaction commits |
   | `replayed_at` | PostgreSQL database-clock time recorded on a new projection revision when the historical rebuild write completes inside its transaction; it is not literal commit time |
   | `as_of` | Captured PostgreSQL logical projection time used for lazy forgetting/current projection; it is not a receipt time |

   A timestamp generated inside a transaction is not described as the literal
   commit timestamp because the repository has no commit-timestamp mechanism.
   Exact duplicate evidence retries return the original logical result and
   preserve the original `applied_at`; conflicting reuse, including a changed
   occurrence timestamp, fails. Historical rebuilds write `replayed_at` on the
   new projection revision and never overwrite the original evidence
   `applied_at` or `recorded_at`. Failed transactions persist none of these new
   markers.

6. **Timestamp source and precision — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** all domain timestamps are timezone-aware
   UTC. Pydantic `LearningEventInput` already rejects naive `occurred_at` and
   normalizes aware values to UTC (`packages/domain/events.py:73-79`).
   PostgreSQL is authoritative for database-generated `recorded_at`, `applied_at`,
   `replayed_at`, `as_of` and validation times; `clock_timestamp()` is used
   where a wall-clock database reading is required. Application-supplied
   `occurred_at` is the deliberate domain-time exception and is normalized after
   awareness validation.

   Existing SQLAlchemy models and migrations use `DateTime(timezone=True)` /
   `sa.DateTime(timezone=True)` without an explicit precision
   (`packages/persistence/models.py:25-28`, `alembic/versions/0006_learning_identity_events.py:19-20`,
   `0007_learning_graph_versions.py:17-20`). PostgreSQL therefore supplies its
   standard microsecond precision for these `timestamptz` columns. Sprint 3.4
   new mastery/evidence/projection timestamps must standardize on
   `TIMESTAMP(6) WITH TIME ZONE` semantics. Equality and ordering use the
   persisted normalized values; no naive values are accepted. Migration 0008
   must inspect/confirm existing 0006/0007 column typmods and document any
   compatibility alteration rather than silently changing established columns.
   No application-clock value may substitute for a database-generated receipt or
   projection timestamp; existing application-clock domain occurrence producers
   remain distinct from those database-generated fields.

7. **Immutable `is_review` contract — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** the canonical value belongs to the
   immutable question version, is copied into the immutable attempt context and
   is copied again into the evidence snapshot used by replay. The current
   `Question` and `AnswerEvidence` contracts have no such field and no attempt
   persistence exists, so Sprint 3.4 must add the minimum records described in
   item 4 rather than claim an existing attempt table.

   Evidence validation requires the copied marker to equal both the originating
   question-version marker and attempt marker. Evidence cannot independently
   change it. A later question edit creates a new question version and cannot
   alter an accepted attempt/evidence snapshot. A review attempt cannot become a
   non-review attempt after submission. Exact retries preserve the original
   snapshot and conflicting reuse fails. `kind=INFERRED` can carry the marker
   for audit purposes but can never qualify as a successful review.

8. **Concept-affecting event taxonomy — FINALIZED INTERPRETATION plus
   IMPLEMENTATION CONTRACT REQUIRED:** a qualifying event must carry an existing
   event type, immutable schema/payload version, non-null learner identity,
   course identity when course-scoped, `occurred_at`, explicit
   `concept_impact=AFFECTS_CONCEPT`, one or more stable concept UUIDs and an
   immutable evidence/attempt/source association when applicable. The event
   remains idempotent and conflict-checked. Qualifying events use the same
   PostgreSQL future-date validation as evidence and are ordered by
   `occurred_at`, with event UUID as a deterministic tie-breaker; `recorded_at`
   remains audit-only.

    The smallest additive contract is a typed `learning-event-v2` concept-impact
    block and normalized event-to-stable-concept association for a qualifying
    event envelope. Existing `learning-event-v1` and `legacy-phase2-v1` rows stay
    readable and non-qualifying when the block is absent. The v2 block adds no
    new `LearningEventType` enum member and must not reinterpret an event name as
    concept impact. It must contain a classification, stable concept UUIDs,
    learner identity, course where required, and optional explicit source
    evidence/attempt ID. The existing generic JSON payload alone is insufficient.
    This additive envelope, association and query/index contract can be added in
    Sprint 3.4.

   | Event category/type | Affects concept clock? | Required evidence |
   |---|---|---|
   | Assessment/answer: `DIAGNOSTIC_COMPLETED`, `CHECKPOINT_ANSWERED`, `ANSWER_SUBMITTED`, `ANSWER_GRADED` | Only with the explicit concept-impact block and association | Learner + stable concept + explicit classification; source attempt/evidence where applicable |
   | Inferred learning: `MASTERY_UPDATED`, `MISCONCEPTION_DETECTED` | Only with the explicit concept-impact block and association | Learner + stable concept + explicit classification; source evidence/causation where applicable |
   | Operational/job: `JOB_FAILED`, `MODEL_FALLBACK_USED`, `PLAN_INVALIDATED`, `PLAN_REPLANNED`, `REMEDIATION_LOOP_BLOCKED`, `REVIEW_DUE` | No | Excluded |
   | Authentication | No current `LearningEventType`; excluded | Excluded |
   | Administrative/course/graph: `SYLLABUS_UPLOADED`, `SYLLABUS_PARSED`, `CURRICULUM_EDITED`, `CURRICULUM_CONFIRMED`, `GRAPH_BUILT`, `PREREQUISITE_EDGE_CONFIRMED`, `PREREQUISITE_EDGE_REJECTED`, `CURRICULUM_SUCCESSOR_CREATED` | No | Excluded |
   | Unrelated course event | No | No matching learner/concept association |

   No current event type or producer qualifies today. Current v1 producers are
   the course/graph/review producers in `packages/persistence/review.py:367-384`,
   `packages/persistence/graphs.py:289-308` and `444-456`, and
   `packages/persistence/successors.py:110-123`; the legacy upload producer is
   `apps/api/documents/service.py:121-129`. Their payloads do not establish the
   required learner/concept association. `ANSWER_GRADED` exists in fixtures but
   has no qualifying production contract. All qualifying persisted events will
   be included for the learner/concept review clock and ordered by the finalized
   occurrence-time policy. Existing legacy compatibility is preserved.

These are the remaining implementation blockers. They do not reopen the
owner-approved replay, weighting, rung or review-clock policies, nor the already
settled status, direct-count, inference-boundary, zero-denominator,
graph-identity or transaction decisions above.

---

## 6. Sprint 3.4 implementation acceptance requirements

Implementation may begin only after Section 5 is confirmed. The acceptance
requirements are:

### 6.1 Pure domain contracts and engine

- Strict immutable contracts for evidence, provenance, question metadata,
  contribution, Beta state, review metadata and update results.
- Original question metadata, graph version, concept-role snapshot and exact
  weight snapshot retained for replay.
- Exact source weights and formulas implemented without hidden thresholds;
  finalized Section 4.1 weights apply to every partial-credit path.
- Positive, negative, partial and finalized inferred-positive paths are
  deterministic.
- Inferred partial/incorrect paths are retained as auditable unapplied records.
- Zero-denominator role fallback conserves negative mass.
- Status evaluation follows the finalized precedence and thresholds.
- Chronological replay uses `occurred_at`, evidence UUID and one captured
  PostgreSQL `as_of`; the remaining approved timestamp validation rules are
  applied separately. `recorded_at` remains audit metadata only.

### 6.2 Persistence and migration

- Additive migration `0008_mastery_evidence`.
- Immutable evidence and contribution history, question-version and attempt
  snapshots, per-learner/course/concept mastery state, review-success/rung
   metadata and the immutable projection-revision/head contract in Section 5,
   item 3.
- Projection revisions retain policy version, captured `as_of`, replay digest and
  boundary, materialized Beta/status/review state, `replayed_at`, reason and
  creation metadata; failed rebuilds cannot move the current head.
- Qualifying concept-affecting learning-event classification and normalized
   event-to-stable-concept associations from Section 5, item 8, while legacy v1 rows
  remain readable and non-qualifying.
- Timestamp columns use the standardized timezone-aware microsecond contract;
  existing column compatibility is checked rather than silently rewritten.
- Foreign keys to internal learner identities, courses, graph versions and
  stable concepts where applicable.
- Unique evidence/idempotency constraints and learner/concept/time indexes.
- No latest-number-only design; evidence history remains queryable.
- Populated-data downgrade refuses destructive loss; empty-schema downgrade is
  available for migration isolation.

### 6.3 Atomic service

- Resolve authenticated actor and affected learner separately.
- Enforce learner authorization before writes.
- Validate question, graph version, concept references and immutable metadata.
- Validate immutable question-version/attempt relationships, learner equality,
  actor authorization, membership at the write boundary, graph publication
  ordering and the captured PostgreSQL future-date check.
- Deduplicate before replay.
- Lock or equivalently serialize affected mastery rows in deterministic order.
- Insert evidence and contributions, rebuild mastery, apply review transitions,
  insert the typed qualifying learning event and applied/projection markers in
  one caller-owned transaction.
- Exact replay returns the original logical result; conflicting reuse fails.
- Any failure leaves no partial evidence, contribution, mastery, review or
  event state.

### 6.4 Queries and replay

- Current learner/course mastery, concept mastery, confidence and `n_eff`.
- Supporting evidence and contribution history.
- Review-success/rung metadata.
- The approved 24-hour review clock considers only persisted events with the
  finalized concept-affecting classification and learner/concept association;
  the missing event taxonomy contract in Section 5 must be resolved first.
- Historical graph-version-aware reads where defined by the approved contract.
- Deterministic replay from immutable evidence and original snapshots.

No public HTTP API is required for Sprint 3.4 unless separately approved.

### 6.5 Required tests

- Exact formula and golden tests for every source weight.
- Partial credit with separate correct/incorrect components, the same MCQ type
  factor on both components, role attribution, weakest-link conservation and
  zero fallback.
- Beta prior, status precedence, `n_eff`, confidence and lazy decay.
- Chronological late evidence, UUID tie-breaking, captured-`as_of` replay and
  duplicate replay.
- Future-date rejection at equality and after the captured PostgreSQL validation
  time, unbounded late evidence, immutable retry timestamps and projection-head
  failure/concurrency behavior.
- Direct counts, repeated question IDs and distinct-question proficiency.
- Review marker, 24-hour occurrence rule, full-credit/direct requirement,
  persisted concept-affecting event filtering, success/rung separation and
  failure reset; zero-based indexing starts at rung 0 and advances the first
  successful review to rung 1.
- Inferred positive, inferred audit-only partial/incorrect and review exclusion.
- Immutable question/weight/graph snapshots.
- Question-version/attempt/evidence `is_review` equality, graph publication and
  learner/authorization validation, timestamp precision and qualifying-event
  concept association.
- Property tests for bounds, monotonicity, decay and replay idempotency.
- Atomic rollback, concurrency, conflicting idempotency, authorization,
  graph/concept validation and learning-event idempotency.
- Phase 3.1 graph, Phase 3.2 identity/event and Phase 3.3 publication
  regressions.

### 6.6 Final cross-policy consistency audit

The current document is internally consistent under the following finalized
rules:

- A removes `recorded_at` from mathematical mastery order while preserving the
  existing Sprint 3.2 event-read order for audit/diagnostics.
- A compares replay at one PostgreSQL `as_of`; forgetting can therefore differ
  only when the requested projection time differs, not because evidence arrived
  in a different order.
- B uses correct difficulty, type, correct-only hint and tag factors only for
  positive mass, and incorrect difficulty, type and tag factors for negative
  mass. The zero-denominator fallback consumes the same negative mass and
  preserves conservation.
- The explicit positive inferred rule uses `w_correct`; inferred
  partial/incorrect rows remain audit-only and cannot introduce a beta or
  partial formula outside this finalized policy.
- The finalized rung policy indexes the ladder from zero without skipping the
  one-day initial interval; `review_successes` remains cumulative and separate
  from the rung. Review scheduling remains deferred.
- The 24-hour review clock uses `occurred_at` for all persisted,
  learner/concept-associated events explicitly classified as concept-affecting;
  operational, administrative, authentication, job-lifecycle and unrelated
  course events are excluded. The missing classifier/association contract
  remains an explicit blocker.
- Status thresholds do not depend on the optional rung; `MASTERED` requires a
  qualifying direct review, and inferred evidence cannot qualify it.
- Stable concept UUIDs continue across graph versions; evidence keeps the
  original graph/role snapshot, so replay cannot reinterpret historical roles.
- Duplicate filtering precedes replay, and exact duplicate requests do not
  change posterior, counts, review state, contributions or events.
- `occurred_at` is the domain event time, `recorded_at` is ingestion/audit time,
  and `applied_at` records the application-marker time inside the transaction;
  durability requires commit. None is silently substituted for another.

No source contradiction was found for A, B, C or the owner-approved event
boundary. The sources are silent or ambiguous on those details; they are
therefore recorded as owner-approved interpretations rather than source
requirements. The remaining timestamp, audit and event-contract requirements
in Section 5 remain implementation blockers until added.

---

## 7. Final implementation-readiness assessment

The eight owner-approved directions are policy-closed. The matrix distinguishes
that closure from repository support: “ready after additive contract work” means
the policy is sufficiently specified for Sprint 3.4, but the listed contract or
migration does not yet exist in the checkout.

| # | Blocker/policy | Classification | Current repository state | Sprint 3.4 readiness |
|---|---|---|---|---|
| 1 | Reject future-dated evidence | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | Generic v1 events validate awareness but do not reject future occurrence; mastery evidence has no occurrence field | Ready after adding PostgreSQL validation-time capture and immutable evidence timestamp checks; no separate owner decision |
| 2 | Unbounded late evidence | FINALIZED INTERPRETATION; DERIVED | Chronological replay and fixed `as_of` are documented; no age cap exists | Ready for Sprint 3.4; replay optimization/checkpoints are deferred performance work |
| 3 | Version historical projections | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | No mastery/projection tables exist; additive migration pattern exists | Ready after adding the minimal projection revision/head tables and transaction rules in Section 5, item 3 |
| 4 | Question/attempt/graph/authorization validation | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | Question and evidence are domain-only; no question-version or attempt persistence; graph publication and current membership exist | Ready after adding immutable question-version/attempt/evidence context; current repository cannot support it without those additions |
| 5 | Separate application and replay timestamps | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | `recorded_at` exists for events; `AnswerEvidence.applied_at` is optional; no `replayed_at` projection field exists | Ready after adding immutable application receipt and projection replay metadata; no commit-time claim is required |
| 6 | Standard timestamp source/precision | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | Columns are timezone-aware but migrations omit explicit precision; PostgreSQL default microsecond behavior is the established basis | Ready after migration 0008 confirms/standardizes `timestamptz(6)` compatibility; no arbitrary precision is introduced |
| 7 | Immutable question-version `is_review` | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | Current `Question`, `AnswerEvidence` and repository contain no question-version or attempt marker | Ready after adding the immutable question-version, attempt snapshot and evidence-copy fields |
| 8 | Concept-affecting event taxonomy | FINALIZED INTERPRETATION; IMPLEMENTATION CONTRACT REQUIRED | Existing events have optional learner/course IDs, generic payloads and no concept-impact association; no current producer qualifies | Ready after adding the typed concept-impact block and normalized concept association; no new event enum member is required |

No remaining policy question is classified as **UNRESOLVED**. The current
checkout is not implementation-ready without the additive contracts marked above,
especially question/attempt snapshots, projection persistence and qualifying
event associations. Those additions are within Sprint 3.4 scope as specified;
if they are removed from that scope, the affected rows become implementation
blockers rather than policy ambiguities.

---

## 8. Sprint 3.5 deferred scope

The following are explicitly deferred:

- review scheduling;
- nightly due-review selection;
- planner insertion of review items;
- review queue prioritization;
- planner/replanning consumption of mastery;
- remediation decisions and diagnostic selection;
- frontend mastery dashboards.

Sprint 3.5 must consume the immutable review-success/rung metadata without
reinterpreting evidence or changing historical mastery. It must also preserve
the approved chronological-replay policy and stable-concept decisions recorded
here.

---

## 9. Source references and decision history

### Sources inspected

- `AAA_v3_BUILD_SPEC.md`, Sections 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 9, 12.4
  and the Phase 3 planning section.
- `agents.md`, corresponding Sections 5 and 6.
- `docs/decisions/0007-beta-mastery.md`.
- `docs/SPRINT_3_1.md`, `docs/SPRINT_3_2.md`, `docs/SPRINT_3_3.md`.
- `packages/domain/enums.py`, `packages/domain/events.py` and
  `packages/domain/models.py`.
- `packages/persistence/models.py`, `packages/persistence/database.py`,
  `packages/persistence/identities.py`, `packages/persistence/repositories.py`,
  `packages/persistence/learning_events.py`, `packages/persistence/review.py`,
  `packages/persistence/graphs.py`, `packages/persistence/successors.py` and
  `apps/api/auth/dependencies.py`, `apps/api/curriculum.py`,
  `apps/api/documents/service.py`.
- `alembic/versions/0006_learning_identity_events.py` and
  `alembic/versions/0007_learning_graph_versions.py`.
- `packages/mastery/__init__.py` and existing domain/persistence/test
  contracts for question, evidence, identity, learning events and graphs.

### Unavailable source

`AAA_v3_COMPLETE_BUILD_PLAN.md` was not present in the WSL checkout. No other
document was substituted for it.

### Decision history

- The previous version of this document was an assessment that identified
  unresolved policies and proposed chronological replay, catch-all
  `DEVELOPING`, direct-attempt counting, explicit review metadata, L2 base
  `1.0`, and a reject-on-zero-denominator fallback.
- This revision retains the project-owner-finalized decisions:
  - chronological replay replaces arrival-time mutation;
  - `DEVELOPING` is the valid-state catch-all and `MASTERED` precedes
    `PROFICIENT`;
  - every unique direct attempt counts while distinct question UUIDs are
    tracked separately;
  - review metadata, direct/full-credit/24-hour rules, review-side transitions
    and scheduler deferral are fixed;
  - inferred partial/incorrect evidence is audit-only;
  - zero denominator uses normalized role weights;
  - L2 base is `1.0`;
  - mastery is keyed by learner and stable concept UUID, not graph version;
  - transaction and conflict behavior is explicit.
- This consistency audit records the owner-approved interpretations:
  - A: mathematical replay order `(occurred_at, evidence UUID)` with
    `recorded_at` audit-only;
  - B: separate correct/incorrect partial-credit weights, including the same
    MCQ type factor on both components;
  - C: zero-based review-rung indexing with initial rung 0 selecting one day;
  - the 24-hour clock uses persisted learner/concept-associated events that are
    explicitly classified as concept-affecting.
- This document does not modify the build specification or existing ADRs. A
  future ADR may record these finalized interpretations if the project owner
  wants them promoted into the long-lived architecture record.

No policy in this document is represented as an existing source rule when it is
actually a finalized interpretation. Sprint 3.4 implementation remains
unstarted pending the timestamp, audit and event-contract confirmations in
Section 5.
