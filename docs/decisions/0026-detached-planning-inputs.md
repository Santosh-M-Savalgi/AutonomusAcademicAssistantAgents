# ADR 0026: Detached authoritative inputs for the deterministic planner

## Status

Accepted for Sprint 3.6 as the smallest implementation consistent with D-05,
build-spec §§4, 5.1 and 6.4, ADRs 0023/0024, and the owner's ADR 0025 resolution.

## Context

Sprint 3.5 supplies ordered review/diagnostic results and a minimal planning
state. There is no learning-session runtime, directive mapper, topic-gate
repository or remediation executor in this checkout. The specification describes
their facts and actions but does not prescribe detached submodels, directive
ties, simultaneous hard-stop ties, or how a completed quiz is represented.

## Decision

- Extend the existing `PlanningState` and `PlannerDecision`; retain the public
  `decide()` function and expose the spec-named `PlannerPolicy.decide()` entry.
- Use frozen, tuple-based inputs for explicit directives, graph vocabulary,
  topic position, pre-evaluated gates, assessment failures and remediation frames.
  A caller authenticates these facts and captures graph/freshness context before
  planning. The planner does not assemble evidence or calculate gates/mastery.
- Consume review/diagnostic/weak-prerequisite candidates in caller-supplied order.
  The caller ranks weak prerequisites deepest-first using existing curriculum
  algorithms. The planner only validates supplied causal paths, confirmed-edge
  status, graph vocabulary and context; it never traverses/ranks a graph.
- Resolve simultaneous hard stops by complete, pause, budget. Resolve multiple
  explicit learner/system directives by smallest directive UUID bytes; source
  does not add an unspecified priority.
- Map `SKIP` to `ADVANCE_TOPIC` (target is the topic to skip), `EXPLAIN_SIMPLER`
  to `RETEACH_WITH_NEW_STRATEGY`, and `MORE_PRACTICE` to `PRACTICE_CONCEPT`.
  Skipping a mandatory topic always requires confirmation. Map `I_KNOW_THIS` to
  its already-selected diagnostic so it never waives a gate. The caller owns
  self-report assertion application; planning cannot add prior mass.
- Require explicit topic authorization and completed prerequisite evaluation
  before normal topic actions. Unsatisfied confirmed gates yield a prerequisite
  teaching proposal; missing gate results yield a blocked needs-state decision.
  Proposed/rejected/informational relationships never enforce gates.
- A completed quiz suppresses regenerating the same quiz. Advancement requires a
  supplied satisfied topic gate and a supplied next target in the published
  vocabulary. An empty candidate list never implies course/session completion.
- Preserve Sprint 3.5 action-shaped hard-stop/directive/remediation fields as
  compatibility seams. New callers use typed directives/frames. The legacy
  remediation target is already caller-mapped; when a graph context is supplied,
  it is validated. New educational selections require graph context. Legacy
  diagnostic target identity alone is insufficient to select questions; the
  caller supplies the Sprint 3.5 candidate collection.
- Return frozen decisions with tuple fields (still JSON arrays), a templated
  explanation, selected rule, input-snapshot SHA-256 and selected provenance.
  Decision provenance is additive and optional for existing external constructors.

## Consequences

The domain seam can be verified with real existing selector outputs without
inventing a production session API, database schema, decision log or event router.
The caller must authenticate the snapshot, evaluate authoritative topic gates
using the existing mastery policy, and authorize/order next targets. The planner
does not prove database authenticity from detached identifiers.

Remediation decisions do not push/pop frames or increment attempts. Execution,
bounded loop guards and event-driven replanning remain Sprint 3.7 work. No mastery
or review formula, graph mutation rule, or protected policy document changes.
