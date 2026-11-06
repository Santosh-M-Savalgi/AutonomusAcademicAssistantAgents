# ADR 0029: Block A runtime ownership and coherent planning reads

## Status

Implemented under the owner's Stage 3–5 authorization. ADR 0028
and migration 0011 remain the accepted baseline. No learning policy is changed.

## Logical operations, defined before implementation

Every write requires an explicit caller transaction. The existing learner identity
is locked first, then the session and operation-specific rows. Detached results
and exact canonical requests are retained in immutable operation receipts, in the
same transaction as the write. This is a retry journal, not a generic object-save
API: each repository entry point has its own validation and write boundary.

| Operation | Logical identity | Exact retry / stale retry |
| --- | --- | --- |
| Create session | session UUID | Original creation snapshot; conflicting scope/content rejected |
| Transition session / position | session + transition event | Original post-transition snapshot; changed request rejected; new stale version fails |
| Store supplied immutable plan/version | established plan-version identity | Original bytes; exact predecessor and dependency fence required for first insert; no publication/head update |
| Create/update frame | frame + creation execution / update event | Original result; actual session/frame versions checked; no ladder or action execution |
| Record frame learner attempt | frame + original learner attempt | Immutable attempt result; no worker retry counter; no automatic guard advance |
| Create/update execution receipt | established educational identity + update event | Original receipt; terminal result immutable; no dispatcher/jobs created |
| Diagnostic run create/update | run + source / completion event | Original result; no budget expansion |
| Diagnostic reservation | run + question version | Original slot/result; locked capacity allocation; no selector or diagnostic execution |
| Diagnostic acknowledgement/link | reservation + original attempt/completion / inferred evidence | Exact original source; reject changed source and stale versions |
| Worker transport link | worker-attempt identity + educational execution | Exact link; worker identity never replaces educational identity |
| Topic window/facts | explicit window + source event | Original result; current session/topic/graph and fact revision checked |
| Directive | directive + source/update event | Original result; immutable original directive identity and versioned lifecycle |
| Completed assessment batch | batch + completion source event | Actual distinct graded source items; exact immutable batch |
| Trigger admission | established source/learner/kind/window trigger identity | Original first evaluation; no second cooldown slot; current recovery status is separate |
| Deferred recovery | trigger + explicit recovery request identity | Original recovery result; revalidate current guards under learner ownership |

Concurrent first insertions serialize on learner ownership before checking absent
rows. Lost responses load immutable operation results. A crash before caller
commit rolls all writes back; after commit the original result is replayed. A new
operation using a stale dependency raises a typed stale-state error. Exact replay
does not apply its old mutation again, even after the live head has advanced.

## Stage boundaries

Stage 3 stores explicit trusted internal facts and supplied contracts. Stage 4
evaluates material triggers with explicit time and stores admitted/deferred work.
Stage 5 reads a coherent authoritative snapshot and freshness/fence context.
Planner invocation, plan publication, educational execution, remediation ladder
orchestration and diagnostic/review execution remain Stages 6–11.

Snapshot assembly takes learner ownership, session ownership, course/review graph
context locks, then ordered concept heads. Existing projection objects are refreshed
from PostgreSQL. Snapshot fingerprints include source digests/counts, projection
identities, session/fact/directive/frame/run versions and trigger/cooldown state.
Revalidation reacquires ownership and rejects a changed fingerprint. Missing facts
stay missing; no mastery, authorization, topic order or graph lineage is guessed.
