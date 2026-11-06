# ADR 0025: Sprint 3.6 preserves build-spec diagnostic precedence

## Status

Accepted for Sprint 3.6 by explicit owner decision: Option 2, build-spec order.

## Context

`AAA_v3_BUILD_SPEC.md` v3.2 §6.4 requires first-match planner evaluation with
topic teaching/check/quiz progression and satisfied-gate advancement before
pending diagnostics (rules 6, 7 and 8 respectively).

The Sprint 3.6 implementation request §8 places diagnostics before normal
topic progression and prerequisite-gate handling. Required test E in §18 demands
`DIAGNOSE` when both a diagnostic candidate and normal topic progression exist.

`docs/SPRINT_3_5_POLICY_DECISIONS.md` §5.3 preserves hard stops, directives,
review due and active remediation as the first four rules, then defers “later
diagnostic/topic/gate rules” while retaining source-specified precedence. The
existing Sprint 3.5 planner has no normal-topic progression branch.

No existing Sprint 3.6-specific policy resolves the conflicting combined-state
outcomes. The implementation request explicitly requires stopping on a policy
conflict, documenting it and obtaining clarification.

## Decision

Preserve `AAA_v3_BUILD_SPEC.md` §6.4 first-match precedence. Normal authorized
topic progression and satisfied-gate advancement precede pending diagnostics.
When a valid diagnostic candidate and an authorized untaught topic coexist,
select `TEACH_CURRENT_TOPIC`.

The owner revised Sprint 3.6 §8/test E accordingly. This resolves the request's
conflict in favor of the existing specification; it is not a build-spec deviation
or a diagnostics-first policy. Protected source-of-truth documents remain intact.

## Consequences

Implementation can proceed with explicit build-spec precedence and a combined-
state regression test expecting `TEACH_CURRENT_TOPIC`. Diagnostics are selected
when earlier applicable rules produce no action. The pure planner boundary and
Sprint 3.5 semantics remain preserved.
