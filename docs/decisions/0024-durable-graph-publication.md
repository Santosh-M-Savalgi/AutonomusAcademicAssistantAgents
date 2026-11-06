# ADR 0024: durable graph publication follows confirmed immutable revisions

## Status

Accepted for Sprint 3.3.

## Decision

- A graph build is created only by the Phase 2 confirmation transaction. The
  graph job carries the exact review/revision IDs, revision artifact reference
  and checksum, actor identity and deterministic job identity.
- The worker revalidates those references and checksums, builds only from the
  confirmed revision through the pure graph adapter, stores canonical graph JSON
  in MinIO, and publishes normalized graph rows in PostgreSQL.
- PostgreSQL graph rows and learning events are written in the caller-owned
  publication transaction. The worker attempt must still own its lease at the
  publication boundary; Redis only wakes workers after commit.
- Graph publication versions are append-only. Edge confirmation or rejection
  creates a new immutable graph version with a parent pointer, preserves the
  original edge source, writes a new immutable artifact and emits a typed event.
- Only `CONFIRMED` prerequisite edges can participate in executable gates.
  Candidate DAG validation still considers non-rejected proposals so cycles do
  not hide in informational data.
- Successor curricula are explicit immutable links with validated element-level
  lineage. A declaration never mutates a parent or successor revision. The
  normal successor confirmation transaction activates only the exact declared
  revision; a later revision requires a new declaration and reconfirmation.

## Rationale

The confirmed Phase 2 artifact is the authoritative curriculum. Rebuilding a
graph from a mutable draft, a later revision, or worker-local state would make
the graph non-reproducible and could authorize a prerequisite that the learner
never confirmed. Content-addressed artifacts plus relational metadata provide
both deterministic replay and queryable history. Attempt fencing prevents a
stale worker from publishing after lease loss, while idempotent identities make
retries safe.

Separating graph publication from job progress preserves the distinction
between operational execution telemetry and durable learning-domain facts.
Explicit successor lineage makes post-confirmation amendments auditable without
silently changing historical graph behavior.

## Consequences

- A successful confirmation can leave an ordinary pending graph job until a
  worker claims it; the curriculum remains confirmed while graph publication is
  retried independently.
- MinIO may contain an unreferenced artifact after a failed database commit;
  this is safe and can be garbage-collected later.
- Graph reads can return complete historical versions without reconstructing
  them from mutable curriculum state.
- Proposal generation and successor reconfirmation remain separate workflows;
  neither is implicitly triggered by graph reads or by Redis delivery.
