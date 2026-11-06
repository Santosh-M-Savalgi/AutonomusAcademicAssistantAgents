# Sprint 3.4: Beta mastery engine and atomic evidence

## Scope and status

Sprint 3.4 adds the pure `mastery_v1` Beta engine and the persistence contracts
needed to retain immutable evidence, replay history and materialized mastery
projections. The implementation follows
`docs/SPRINT_3_4_POLICY_DECISIONS.md`; Sprint 3.5 scheduling, due-item selection
and planner integration remain deferred.

The engine is deterministic and receives all timestamps explicitly. It has no
database, Redis, FastAPI, network or application-clock dependency.

## Module responsibilities

- `packages/domain/mastery.py` contains frozen, strict contracts for question
  versions, attempts, evidence, roles, weights, Beta state, contributions and
  replay results.
- `packages/domain/events.py` retains the v1/legacy event contracts and adds the
  typed `learning-event-v2` concept-impact envelope.
- `packages/mastery/weights.py` calculates and freezes exact correct and
  incorrect components.
- `packages/mastery/engine.py` owns Beta calculations, lazy forgetting, status
  classification, direct counters, review transitions and chronological replay.
- `packages/persistence/models.py` contains the additive question-version,
  attempt, evidence, contribution, projection revision/head and normalized
  concept-event association models.
- `packages/persistence/mastery.py` performs source-context validation and
  evidence application inside a caller-owned SQLAlchemy transaction.
- `packages/persistence/concept_events.py` writes idempotent v2
  concept-affecting events without changing legacy/v1 event behavior.
- `alembic/versions/0008_mastery_evidence.py` creates the additive Sprint 3.4
  schema and refuses destructive downgrade when data exists.

## Beta formulas and weights

The initial prior is `alpha=1`, `beta=1`.

```text
n_eff = alpha + beta - 2
mastery = alpha / (alpha + beta)
confidence = n_eff / (n_eff + 4)
```

Correct difficulty weights are `0.7`, `1.0`, `1.3` for difficulty bands 1–2,
3 and 4–5. Incorrect weights are `1.3`, `1.0`, `0.7`.

```text
w_correct = correct_difficulty * type_weight * correct_hint_factor * tag_confidence
w_incorrect = incorrect_difficulty * type_weight * tag_confidence
positive_mass = c * w_correct
negative_mass = (1-c) * w_incorrect
```

MCQ uses `0.6 * (1 - 1/n_options)` for both components as the owner-approved v1
interpretation. Hints affect only `w_correct`; tag confidence is clipped to
`[0.5, 1.0]`. Primary and prerequisite role weights are `1.0` and `0.5`.

Positive mass is attributed directly by role. Negative mass uses weakest-link
allocation and falls back to normalized role weights when the denominator is
zero. Empty concepts and zero role-weight totals are rejected.

Inferred positive evidence applies `0.3 * w_correct * role` to alpha. Inferred
partial or incorrect evidence is retained as an unapplied audit contribution.

## Status and review state

Statuses are evaluated in the approved order: `UNASSESSED`, `WEAK`, `MASTERED`,
`PROFICIENT`, then `DEVELOPING`. Every unique direct evidence attempt increments
`n_direct`; distinct direct question IDs are tracked independently.

Review state uses `[1, 3, 7, 14, 30, 60]` with a zero-based rung. Rung `0` is the
one-day interval, the first qualifying success advances to rung `1`, and failure
resets to rung `0`. `review_successes` is cumulative. A successful review must
be immutable `is_review=true`, direct, full-credit, unique and at least 24 hours
after the previous qualifying learner/concept learning event.

## Evidence lifecycle and validation

1. The caller resolves actor and learner identities and checks authorization.
2. Immutable question-version and attempt snapshots are validated.
3. Evidence occurrence time is normalized to UTC and compared to one captured
   PostgreSQL `clock_timestamp()`; future evidence is rejected and equality is
   accepted.
4. Evidence, original role/weight metadata and the database recording receipt
   are inserted idempotently.
5. All accepted learner/course evidence is replayed in `(occurred_at, evidence
   UUID)` order using original snapshots.
6. Lazy forgetting projects to one captured PostgreSQL `as_of`.
7. Contributions, review state, event associations and projection revisions are
   persisted in the same caller-owned transaction.

Exact retries preserve original occurrence, recording and application receipts.
Conflicting evidence or idempotency-key reuse fails. Historical replay records a
new projection `replayed_at` and never overwrites original evidence receipts.

## Replay and projection revisions

Replay deduplicates evidence before processing, reconstructs all co-tagged
concepts together and applies forgetting between evidence times. It does not use
`recorded_at`, `applied_at`, SQL insertion order or query-plan order for
mathematical ordering.

Migration `0008_mastery_evidence` stores immutable projection revisions and a
current head per learner/course/stable-concept key. Revisions retain the policy
version, captured `as_of`, evidence digest/count/boundary, all materialized Beta
values, status, review state, creation time, replay time and rebuild reason.
Ordinary reads may calculate a transient lazy-forgetting projection; they do not
create a new immutable revision merely because wall-clock time advanced.

Failed rebuilds leave the previous head intact. Concurrent rebuilds lock heads
for affected keys and allocate monotonically increasing revisions.

## Concept-impact events

`learning-event-v2` adds an explicit `AFFECTS_CONCEPT` block with learner
identity, stable concept UUIDs, course where applicable, occurrence time and
optional source evidence/attempt IDs. A normalized association table supports
learner/concept review-clock queries. Existing v1 and legacy rows remain readable
and are non-qualifying when this block is absent. No current production event
producer is automatically classified as concept-affecting.

## Transaction boundaries

`apply_evidence()` never commits. The caller owns commit and rollback. Evidence,
contributions, application markers, event associations, review state and
projection head advancement succeed or fail together. PostgreSQL-generated
timestamps are database-clock values written inside the transaction, not literal
commit timestamps.

## Migration and tests

Migration `0008_mastery_evidence` is additive and uses timezone-aware
microsecond timestamp semantics. Its downgrade checks all Sprint 3.4 tables and
refuses to discard populated data; empty-schema downgrade remains available for
isolated migration tests.

Pure unit coverage includes weights, partial credit, conservation, inferred
evidence, status precedence, forgetting, deterministic UUID replay and review
transitions. Persistence coverage must exercise migration upgrade/downgrade,
idempotency, source validation, projection heads, event-v2 associations,
authorization, rollback and concurrent serialization in the live integration
environment.

## Known limitations and deferred work

- The existing repository has no production question-version or answer-attempt
  producer; Sprint 3.4 persistence contracts provide the required immutable
  records for integration.
- Existing course membership stores membership existence but does not define
  delegated learner roles. Self-submission is supported by the current identity
  boundary; delegated operations require an explicit authorization contract.
- No current production learning event qualifies for the concept clock until a
  producer supplies the v2 concept-impact block.
- Replay checkpoints and performance optimization are not implemented as policy
  shortcuts; late evidence remains unbounded.
- Review scheduling, nightly due-review selection, planner insertion, planner
  consumption, remediation and dashboards remain Sprint 3.5 scope.
