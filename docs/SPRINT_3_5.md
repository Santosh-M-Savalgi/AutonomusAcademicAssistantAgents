# Sprint 3.5: Spaced Review and Diagnostics

## Scope and status

Sprint 3.5 adds the deterministic adaptation layer on top of the Sprint 3.4
Beta mastery engine. It does not implement the complete later remediation,
replanning, loop-guard, dashboard, or frontend systems.

The implementation follows `docs/SPRINT_3_5_POLICY_DECISIONS.md`. The policy
document remains the authority for review anchors, candidate ranking, diagnostic
selection, self-report priors, concept-impact event boundaries, graph-version
handling, and planner precedence.

## Module responsibilities

- `packages/domain/adaptation.py` contains frozen strict contracts for review
  reasons, schedules, candidates, freshness, self-report priors, diagnostic
  state/candidates/provenance, and the Sprint 3.5 planner state.
- `packages/mastery/scheduling.py` contains pure UTC schedule arithmetic,
  schedule-cycle hashing, due-event idempotency keys, eligibility, ranking, and
  maximum-three selection.
- `packages/mastery/engine.py` replays self-report priors and excludes the
  current concept-impact event by matching source evidence or attempt identity.
  Review transitions remain owned by the Sprint 3.4 engine.
- `packages/curriculum/diagnostics.py` performs pure diagnostic ranking,
  deterministic question inventory selection, confirmed transitive prerequisite
  closure, and inference provenance construction.
- `packages/planner/policy.py` implements the minimum pure
  `PlanningState -> PlannerDecision` precedence slice.
- `packages/persistence/review_schedule.py` persists schedule state, emits
  non-impact `REVIEW_DUE` events, synchronizes schedule state from replay, and
  reads candidates without creating revisions.
- `packages/persistence/mastery.py` persists self-report priors, replay-derived
  review metadata, diagnostic provenance, and the qualifying grading event
  boundary in the caller-owned evidence transaction.
- `alembic/versions/0009_sprint35_adaptation.py` is additive. It adds review
  schedules, self-report assertions, replay review metadata, and diagnostic
  provenance.

## Review scheduling

The ladder remains `[1, 3, 7, 14, 30, 60]` days. Rung transitions are still
owned exclusively by `packages/mastery/engine.py`.

The first explicit `learning-event-v2` concept-impact event seeds rung 0 and a
one-day due date:

```text
initial_due_at = first_concept_event.occurred_at + 1 day
```

After a successful review, the post-transition rung determines the next
interval. A first successful review moves rung 0 to rung 1 and schedules three
days from the successful review's `occurred_at`. `recorded_at`, `applied_at`,
and `replayed_at` never anchor scheduling.

Candidates are eligible when decayed mastery is below `0.6` or an existing due
date has passed. Both reasons are preserved. Ranking is overdue first, earliest
due date, lower decayed mastery, then stable concept UUID. Duplicate concepts
are removed and no more than three candidates are returned. Active remediation
blocks review insertion.

Missing projections return typed unavailable state and are never treated as
zero mastery. Read-time lazy forgetting does not create a projection revision.

The schedule cycle hashes the policy-defined canonical learner/course/concept,
graph, policy, anchor, rung, due-date, and evidence-set values. The resulting
stable cycle is used in the durable `REVIEW_DUE` idempotency key. `REVIEW_DUE`
is persisted as a non-impact operational event and is not inserted into
`learning_event_concepts`.

## Self-report weak prior

Self-report is an immutable assertion, not a synthetic question, attempt, or
direct evidence row. Replay applies it once per learner/course/stable concept:

```text
(alpha, beta) = (1, 1) -> (2, 1)
n_eff = 1
confidence = 1 / (1 + 4) = 0.2
```

The assertion does not increment `n_direct`, add a direct question, satisfy a
mastery gate, qualify a review, or clear diagnostic pending state. Diagnostic
eligibility uses an independent `diagnostic_assessed` predicate, while the
diagnostic score uses the actual Beta confidence of the current posterior.

## Diagnostic selection and inference

Diagnostic selection is pure and deterministic. It uses:

```text
score = (descendant_count + 1) * (1 - confidence)
```

Only diagnostically unassessed concepts in the current confirmed graph are
considered. Equal scores use stable confirmed-graph topological order, then
stable concept UUID. Up to two active question versions are selected per
concept, ordered by question-version UUID, with a total budget of 12. Concepts
without valid questions are skipped without generating replacements.

Correct, full-credit diagnostic answers can produce one inferred contribution
per `(source_attempt_id, prerequisite_concept_id)` for the confirmed transitive
prerequisite closure. Diamond paths are deduplicated. Each contribution stores
diagnostic run, source attempt/question/evidence, graph, confirmed edge, learner,
and target-concept provenance. The existing inferred-positive formula and
prerequisite role weight are used; inferred evidence never affects direct counts,
distinct-question counts, `MASTERED`, or review-rung state.

## Concept-impact event boundary

The existing caller-owned `apply_evidence()` boundary is the Sprint 3.5 grading
integration point. A real `ANSWER_GRADED` concept-impact event must carry both
`source_evidence_id` and `source_attempt_id`, learner/concept associations,
occurrence time, and causation/correlation metadata in the same transaction as
evidence and projection updates.

During replay, the current evidence's event is excluded when either source ID
matches the current evidence or attempt. The exclusion is per evidence item.
Unrelated earlier events remain eligible, and the current event remains stored
for subsequent attempts.

Generic v1 events, graph events, operational events, and `REVIEW_DUE` do not
qualify for the 24-hour review clock.

## Projection and schedule persistence

Migration `0009_sprint35_adaptation` adds:

- `self_report_assertions` with learner/course/concept uniqueness and idempotency;
- `review_schedule` with current schedule state, cycle identity, due time,
  reasons, graph/projection/evidence provenance, and supporting IDs;
- `last_successful_review_at`, `last_successful_review_evidence_id`, and
  `last_successful_review_event_id` on projection revisions; and
- optional diagnostic provenance on immutable evidence rows.

Projection review history is derived from chronological replay. It is never
inferred from `status == "MASTERED"`. Schedule and projection updates use
caller-owned transactions and deterministic row locking. PostgreSQL remains the
source of truth; Redis is only a post-commit wake-up mechanism.

## Planner boundary

The review selector and diagnostic selector produce immutable, ranked typed
values. The pure planner consumes `PlanningState` and returns the existing
`PlannerDecision`.

The Sprint 3.5 precedence is:

1. hard stops;
2. user directives;
3. `REVIEW_DUE` when candidates exist and no active remediation frame exists;
4. remediation continuation or return; and
5. later diagnostic/topic/gate behavior only where existing contracts support it.

The planner performs no database, Redis, HTTP, clock, random, mastery, graph,
question-selection, or event-persistence work.

## Tests and verification

Pure tests cover self-report confidence, initial one-day/next three-day review
intervals, candidate ranking, diagnostic score/ties/budget, diamond inference,
current-attempt event exclusion, and planner precedence in
`tests/unit/test_sprint35_adaptation.py`.

Live integration coverage is in `tests/integration/test_sprint35_runtime.py`.
It covers self-report idempotency, replayed confidence, grading-event schedule
seeding, due selection, and non-impact `REVIEW_DUE` persistence. It requires the
fixture-owned service integration environment.

The full mandatory Phase 3/§16.5 closed-loop acceptance remains deferred because
the later planner, remediation, replan, and frontend systems are outside Sprint
3.5.

## Known limitations and deferred work

- The repository still has no complete production answer-grading API/worker
  workflow; `apply_evidence()` is the available legitimate caller-owned grading
  boundary.
- Current graph-context revalidation returns a typed stale result when a schedule
  points at an older published graph; a future caller must explicitly refresh or
  supersede that schedule without rewriting history.
- The complete planner policy, plan stack, remediation frames, replan triggers,
  loop guard, dashboards, and frontend are deferred.
- No real LLM or paid external service is used by Sprint 3.5 tests.
