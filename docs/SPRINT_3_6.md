# Sprint 3.6: Deterministic Planner

## Objective and current status

Extend the existing pure `PlanningState -> PlannerDecision` boundary with typed,
immutable planning inputs and deterministic, auditable first-match decisions.
Sprint 3.5 remains the implementation baseline.

**Status: Sprint 3.6 deterministic planner implementation and required verification
complete.** The owner resolved the precedence conflict in favor of
`AAA_v3_BUILD_SPEC.md` §6.4 (Option 2). Implementation follows the existing
specification; there is no build-spec deviation. The live integration suite and
Compose configuration check pass after WSL Docker availability was restored.

## Sources inspected

- `AAA_v3_BUILD_SPEC.md` v3.2, especially §§4, 5.1, 6.4, 9 and 12.
- `agents.md` and existing repository/package boundaries.
- `packages/domain/adaptation.py`, `packages/domain/models.py`, graph and job
  contracts, and package references to sessions, directives and gates.
- `packages/planner/policy.py` and the existing Sprint 3.5 scheduling,
  diagnostic, persistence and planner tests.
- `docs/SPRINT_3_5.md` and `docs/SPRINT_3_5_POLICY_DECISIONS.md` §5.3.
- Accepted ADRs 0005, 0023 and 0024.

No Sprint 3.6-specific policy/decision document existed at inspection time.
`AAA_v3_COMPLETE_BUILD_PLAN.md` and `AGENTS.md` are absent from this checkout.

## Resolved policy conflict and precedence

`AAA_v3_BUILD_SPEC.md` §6.4 (lines 319–329) specifies first-match rules:

1. Hard stops.
2. Pending user directive.
3. Review due, excluding active remediation.
4. Active remediation continuation/return.
5. Latest-assessment failure handling.
6. Topic teaching/check/quiz progression.
7. Satisfied-gate advancement.
8. Pending diagnostics.
9. Insufficient-evidence/ambiguity fallback.

The Sprint 3.6 implementation request §8 instead places diagnostic work before
topic progression and prerequisite-gate handling. Its required test E explicitly
states that a diagnostic candidate plus normal topic progression must select
diagnostics.

For a state containing both a pending valid diagnostic candidate and an untaught,
authorized current topic, these requirements demand different actions:

- Build-spec §6.4: `TEACH_CURRENT_TOPIC`.
- Sprint 3.6 request §18 E: `DIAGNOSE`.

The finalized Sprint 3.5 policy §5.3 preserves the common first four rules, then
says “later diagnostic/topic/gate rules” and retains source-specified precedence.
It does not resolve the ordering of these later rules. The Sprint 3.5 planner had
no normal-topic progression branch, so its diagnostic behavior did not establish
precedence for this combined state. ADR 0005 establishes determinism without
specifying that ordering.

The owner selected Option 2: preserve build-spec §6.4 precedence. Sprint 3.6
§8/test E is therefore revised to expect `TEACH_CURRENT_TOPIC` when an authorized
untaught topic and a pending valid diagnostic candidate coexist. Normal topic
progression and satisfied-gate advancement precede diagnostics. This resolution
is recorded in accepted `docs/decisions/0025-sprint36-diagnostic-precedence.md`.

## Planner boundary and contracts

```text
caller-authenticated authoritative snapshot / existing selectors
    -> PlanningState
    -> PlannerPolicy.decide(state) / decide(state)
    -> PlannerDecision
    -> future executor / replanner
```

`packages/planner/policy.py` implements one shared pure function. The class entry
point is a static alias, preserving Sprint 3.5's exported `decide()` API. It makes
one decision without persisting, emitting an event, creating a job or executing
the selected action.

### PlanningState

The existing frozen `packages/domain/adaptation.py` contract is extended with:

- Explicit session-complete, user-pause and budget-exhaustion facts.
- `PlanningDirective`: stable identity, closed directive kind, target and source.
- `PlanningGraphContext`: caller-validated published/current graph IDs,
  course-scoped topic/concept vocabulary and mandatory topics.
- `RemediationFrame`: frame identity, current concept, return topic, complete
  flag and already-authorized practice/reassessment continuation action.
- Ordered Sprint 3.5 `ReviewCandidate` and `DiagnosticCandidate` collections,
  the existing `DiagnosticState`, and required typed projection freshness results.
- `TopicPlanningState`: authorized current topic, core concepts, teaching/check/
  quiz completion, pre-evaluated prerequisites, topic-gate result and an
  already-authorized next topic.
- `AssessmentPlanningState`: current-topic failing concepts and caller-ranked
  weak prerequisites with ordered causal edge paths.
- Source event IDs for audit.

Nested contracts use frozen models and tuples; no service, repository, callback,
database session, random source, clock or client can be attached. Input validation
rejects duplicate candidates/directives/questions, more than three reviews,
invalid topic positions and self-targeting advancement.

Sprint 3.5 action-shaped fields remain compatibility seams. Typed frames and
directives are preferred for new callers. A legacy diagnostic target alone does
not supply question inventory; callers provide the existing selected candidates.
Legacy mapped remediation targets remain usable without inventing new targets;
supplied graph context and required freshness are still validated.

### PlannerDecision

The existing `packages/domain/models.py` decision is extended, with no competing
result type. It is frozen; reason/evidence tuples serialize as JSON arrays. The
original action, target, confidence, outcome, policy version and plan version are
preserved. An additive optional `PlannerDecisionProvenance` includes selected
rule, learner/course/session/graph context, canonical input SHA-256, selected
directive/frame/run/question IDs, review reasons and projection/evidence digest,
causal edge IDs, source events, return topic and any needs-state issue.

Every planner-produced decision has a deterministic templated explanation and
provenance. Evidence confidence is copied from supplied authoritative inputs;
branches without assessment evidence use zero rather than claiming certainty.
Both state and decision expose stable `canonical_bytes()`. Unordered directives,
freshness records, graph vocabulary and source events are canonicalized; ordered
selector candidate collections preserve their meaning.

## Rule behavior

### Hard stops and required state

An explicitly complete session returns `COMPLETE`; pause returns `PAUSE`; an
exhausted budget returns `ASK_USER` with `BUDGET_EXCEEDED` and `BLOCK`. Concurrent
hard stops resolve in that order. Existing mapped stop actions are supported;
non-stop actions supplied as hard stops are blocked.

Required missing/stale projections, stale published graph identity, cross-course
graph context and invalid selected targets produce a typed blocked `ASK_USER`
decision with an audit issue. A stale graph is never migrated or interpreted as
current. Empty action inventories do not imply completion.

### Explicit directives

Directive UUID bytes determine the selected directive across learner/system
sources. Free-form text is never parsed. `SKIP` maps to `ADVANCE_TOPIC`, with the
skipped topic as target; mandatory skipping requires confirmation.
`EXPLAIN_SIMPLER` maps to `RETEACH_WITH_NEW_STRATEGY`; `MORE_PRACTICE` maps to
`PRACTICE_CONCEPT`. `I_KNOW_THIS` requests its already-selected diagnostic, never
waiving a gate or adding self-report mass. Assertions remain caller-owned.

### Reviews, remediation and assessments

The first already-ranked review candidate wins. The planner preserves its
detailed reasons, evidence, events and projection provenance and never reranks
or rechecks mastery/review eligibility. An active typed or legacy remediation
frame suppresses review insertion, including when the frame awaits return.

Remediation produces only continuation or `RETURN_TO_TARGET`; it does not push,
pop, execute or guard a frame. Latest-assessment failures consume caller-ranked
deepest-first weak prerequisites through confirmed causal paths. With no
executable weak prerequisite, the planner proposes `RETEACH_WITH_NEW_STRATEGY`.

### Normal topics and prerequisite gates

Authorized topic position selects `TEACH_CURRENT_TOPIC`, then
`GENERATE_MICRO_CHECK`, then `GENERATE_QUIZ`. A completed quiz is not regenerated.
Advancement requires the caller's satisfied topic gate and authorized next
target. Topic gate evaluation remains outside the planner, using the existing
policy (default minimum core mastery 0.70, each core concept's direct count at
least three, latest quiz at least 0.6); the planner adds no mastery formula.

Prerequisites authorize progression before its educational action. Only
`CONFIRMED PREREQUISITE_OF` edges from prerequisite to dependent core concept
enforce a gate. Unsatisfied gates propose `TEACH_PREREQUISITE`; unknown gate
results block rather than guess. Proposed, rejected, informational and reversed/
unrelated edges do not gate the topic. No mastery transfers across graph versions.

### Diagnostics and fallback

Diagnostics are evaluated after normal topic progression and satisfied-gate
advancement. The first already-selected candidate supplies its target, confidence
and question versions. The planner validates run identity, graph context,
remaining budget and prior-use identifiers without scoring, selecting questions,
traversing the graph, inferring evidence or mutating the run.

If no authoritative action is available, the deterministic fallback is `ASK_USER`
with `LOW_EVIDENCE` and `REQUIRE_CONFIRMATION`. Explicit completion is required
for `COMPLETE`.

## Determinism, purity and integration

The existing planner remains pure. Candidate generation, mastery calculations,
graph traversal, prerequisite inference, evidence/event production, job creation
and persistence remain owned by their existing layers. Confirmed-only executable
prerequisite semantics remain established by ADRs 0023 and 0024.

Planner imports are limited to domain contracts and pure standard-library
operations. `.importlinter` adds an explicit planner purity contract excluding
infrastructure, environment, clocks, curriculum/mastery engines and model clients.
The planner generates no UUIDs and uses no clock, randomness or process hash order.

Existing review/diagnostic selector results cross the domain seam directly.
Integration coverage includes persisted review selection converted to a detached
snapshot, planning after the read transaction closes, and verifying that neither
projection revisions nor learning events change. There is no learning-session
runtime in this checkout to connect to a production executor.

Implementation choices for unspecified detached inputs and ties are recorded in
`docs/decisions/0026-detached-planning-inputs.md`.

## Out of scope and known limitations

The full runtime loop, remediation execution, loop guards, replanning, session FSM
expansion, production grading workflow, graph-version schedule migration and
frontend remain outside this sprint's requested implementation.

- The trusted caller authenticates detached facts, evaluates topic/prerequisite
  gates and freshness, validates current graph provenance and orders/authorizes
  next targets. A detached identifier is not proof of database authenticity.
- Production directive ingestion, session FSM execution, decision persistence,
  event routing, content generation and a production grading workflow are absent.
- Loop guards, bounded remediation execution and event-driven replanning remain
  Sprint 3.7 work. This sprint does not claim the full adaptive loop or Phase 3.
- No schema/migration, dependency, LLM, review or mastery formula change is needed.

## Verification and limitations

Tests are added in `tests/unit/test_planner_policy.py`,
`tests/unit/test_planner_purity.py` and `tests/integration/test_planner_boundary.py`.
They cover the requested precedence matrix (owner-revised E), combinations of
hard stops/directives/reviews/frames/diagnostics/topics, confirmed-only gates,
required freshness, missing state, failures, return behavior, inventory bounds,
input/output immutability, canonical round trips and deterministic invariants.

Purity tests use isolated processes with hash seeds 1 and 42, unavailable
infrastructure imports, denied environment/clock/random access and denied
filesystem/network/subprocess I/O during decision execution. Selector integration
tests exercise review ranking/UUID ties/bounds and real graph/self-report
diagnostic outputs. Service-independent and live suites pass, including the
persisted-review planning boundary test.

### Executed validation

| Command | Observed result |
| --- | --- |
| Focused planner policy/purity/boundary pytest run | 96 passed, 1 live test skipped |
| `make test` | 336 passed, 91 live tests skipped, 1 warning |
| `make check` | Passed: Ruff clean, strict mypy clean for 58 source files, 7 import contracts kept / 0 broken, pytest 336 passed / 91 skipped / 1 warning |
| `make integration` | 94 passed, 1 warning in 128.71 seconds |
| `docker compose -f infra/compose/test.yml config --quiet` | Passed |
| `git diff --check` | Passed |

The warning is the existing Starlette TestClient use of deprecated
`anyio.abc.BlockingPortal`.

An earlier integration attempt failed Docker preflight with 3 service-independent
passes and 91 setup errors before service startup; the earlier Compose check was
also blocked. After WSL Docker availability was restored, the owner-requested
`make integration` retry passed all 94 integration tests, including the live
persisted-review planning boundary test. The Compose check then passed. The
successful retry resolves the verification blocker; earlier Sprint 3.5 results
were not substituted for Sprint 3.6 verification.

Existing tracked/untracked work, source-of-truth documents and `__agent__/` are
preserved. Nothing is staged or committed.
