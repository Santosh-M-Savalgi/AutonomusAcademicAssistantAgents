# ADR 0027: Stage 1 adaptation persistence alignment

## Status

Implemented for the owner's Sprint 3.7 Stage 1 authorization. This records
persistence mechanisms consistent with the accepted Sprint 3.4/3.5 policies;
it does not amend their formulas or Sprint 3.6 planner behavior.

## Decisions

### Review notification envelope ownership

The first committed v1 `REVIEW_DUE` envelope owns one approved schedule cycle.
The producer locks the existing learner identity and current schedule before
creating or replaying its notification. It validates the stored cycle hash,
current schedule/candidate context, original actor and source provenance.

For an existing event, the producer reconstructs its original envelope and
passes that exact input through the unchanged strict v1 event writer. Later
calculation time, eligibility reasons and projection revision observations do
not regenerate the envelope. An explicitly requested different correlation,
different supporting source identities, stale candidate, incorrect cycle or
conflicting stored payload is rejected. Projection-revision metadata can advance
for the same immutable evidence/cycle; the original event retains its revision.

For new events, correlation defaults to a deterministic UUID derived from the
existing cycle key. This improves reproducibility, but preservation of the whole
original envelope is what provides later-time retry safety. The approved cycle
material, key formula and event ID derivation remain unchanged.

New payloads additionally record canonical cycle material and the explicit anchor
event. Existing valid v1 notifications can be replayed without rewriting them or
requiring those additive fields. Notifications remain non-impact events with no
`learning_event_concepts` association. Schedule reason annotations are written on
first emission; selectors continue computing current reasons independently.

### Evidence and projection time

Replay fingerprints serialize only `EvidenceInput` fields, plus the existing
self-report contribution fields, in the existing canonical ordering. Persisted
`EvidenceRecord.recorded_at` and `applied_at` are excluded. The projection `as_of`
and ledger maximum occurrence remain outside immutable evidence identity.

Projection alpha/beta values have already been decayed to stored `as_of`.
Restoration therefore uses `as_of` as the domain state's decay reference.
`max_occurred_at` remains the ledger boundary and is not a second decay origin.
No forgetting, weight, status, review or gating formula changes.

Replaying separate concepts now retains untouched concept posteriors. This fixes
state-map loss exposed by direct-plus-inferred replay, without changing any
per-concept calculation.

### Legitimate diagnostic inference

`apply_evidence(..., diagnostic_inferences=...)` accepts provenance attached to
the original full-credit, non-review direct evidence. It validates original
question/attempt/evidence context, published historical graph membership and the
exact confirmed transitive closure using the shared pure diagnostic algorithm.

Derived `INFERRED` ledger rows preserve original question, question version,
attempt, occurrence time, weighting metadata and graph, and carry the approved
run/source/edge/prerequisite provenance. They have a prerequisite role for the
derived contribution; the source question's roles are untouched. The normal
direct evidence validator still requires original question-role agreement.
Submitting a derived diagnostic request through that normal path is rejected.

Migration 0010 adds explicit source-evidence/source-attempt/target linkage,
foreign keys, a linked-source check constraint, and the source-attempt/target
unique partial index. Existing rows are retained with nullable linkage; there is
no automatic historical backfill or source fabrication. Existing conflicting
legacy identities require explicit reconciliation rather than overwriting.

### Transactions and concurrency

Supported mastery application/self-report operations acquire the existing learner
identity row before reading/replaying source evidence. This serializes concurrent
first insertions and course replay, including absent heads/schedules. Due emission
uses the same learner-before-schedule order, avoiding reversed learner/schedule
lock order. Multiple due candidates lock in concept UUID order and are returned
in the selector's original ranking order.

Inference insertion uses a nested savepoint and exact immutable source comparison.
Exact retries reuse existing evidence/projection results. A committed direct source
can acquire previously missing inferred contributions through chronological replay;
its direct mass/count is not applied twice. Derived rows, projections, schedules,
optional grading event and applied markers share the caller-owned transaction.
No method commits or waits on an external service/model.

## Consequences and limits

- These are Stage 1 persistence alignments, not a session/plan/execution runtime.
- A future trusted outcome boundary must authenticate/authorize learner access
  and bind provenance to a durable diagnostic run/reservation.
- Direct low-level source/event/schedule writes outside the supported application
  seams are not certified by this serialization protocol.
- Old projection digests and notification envelopes remain immutable. A later
  authorized replay creates new revisions; migrations do not rewrite history.
- The isolated live test stack uses tmpfs. Cleanup removes its containers without
  a Docker volume-deletion flag and never targets development databases.
