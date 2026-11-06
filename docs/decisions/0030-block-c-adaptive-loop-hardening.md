# ADR 0030: Block C adaptive-loop transaction and recovery boundaries

## Status

Accepted for Sprint 3.7 Block C implementation.

## Decision

Stages 8–10 keep learner-facing state in caller-owned PostgreSQL transactions.
The learner identity is locked first, followed by the session and the
operation-specific durable row. Each composite operation records its canonical
request and immutable result in the existing runtime operation journal. A retry
returns that result before checking dependencies that may have changed after the
original commit.

The remediation guard uses one three-attempt budget per ladder rung. Exhausting
a rung advances exactly one applicable strategy, resets the count to zero and
uses the latest observed mastery as the next baseline. Only the terminal ladder
outcome emits `REMEDIATION_LOOP_BLOCKED`; previous frame-attempt rows remain
immutable. Model escalation is an explicit authorization input and is included
in retry material.

Diagnostic reservations use the durable `RESERVED`, `ATTEMPTED`, and `ASSESSED`
states. Candidate selection remains pure and deterministic. Completion applies
the original source evidence through the existing mastery repository, then
persists confirmed prerequisite inference with its original source and graph
provenance. Review execution retains the original due-cycle identity and
reasons even after the schedule advances.

Worker attempts remain delivery identities. They may be linked to an execution
receipt, but a generic job success is not an educational outcome. Domain
receipts, evidence rows, reservation state, frame history, and session
transitions are authoritative.

## Consequences

- Pre-commit failures roll back source rows, state transitions, events and
  operation results together.
- A lost response after commit can be recovered without regenerating a result.
- Changed immutable request material conflicts instead of being silently
  accepted.
- The existing mastery formulas, graph closure, planner precedence, review
  identity, worker lease model and migrations 0010–0013 remain unchanged.
- Identifier-only structured observations can be emitted without learner answer
  content or external telemetry.
