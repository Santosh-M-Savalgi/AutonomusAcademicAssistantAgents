# ADR 0023: Pure graph contracts preserve confirmed-revision provenance

## Status

Accepted for Sprint 3.1.

## Decision

- Keep graph contracts in `packages.domain.graph` and graph algorithms/templates
  in `packages.curriculum`. Neither package may perform persistence, HTTP,
  storage, queue, network, clock or random I/O.
- A confirmed curriculum graph retains the original `ReviewElement` in each
  curriculum-derived graph node, while also retaining its stable element ID,
  parent ID, source provenance, source ranges and parse confidence. The graph
  adapter validates that these values agree before constructing a snapshot.
- `GraphSnapshot` is course-scoped and revision-scoped. A seed template can be
  attached to a snapshot only through an explicit caller-provided course and
  confirmed revision identity; template edges remain `PROPOSED`.
- Leaf-topic fallback concepts are opt-in and receive deterministic UUIDs. They
  retain `INFERRED_FALLBACK` provenance, a source topic ID and `verified=false`.
  They are never created by graph validation or by topic ordering alone.
- The dependency candidate DAG validates non-rejected prerequisite proposals;
  the executable DAG filters to `CONFIRMED` edges only. Rejected relationships
  remain available for audit but do not affect traversal or gating.

## Rationale

Phase 2 stores the authoritative confirmed revision as typed, immutable content
with stable curriculum element identities. Keeping that provenance in the pure
graph contract prevents future persistence code from reconstructing or silently
weakening source guarantees. Separating candidate-DAG validation from confirmed
execution preserves proposed graph quality checks without allowing confidence or
template origin to act as confirmation.

## Consequences

The graph package can be tested without PostgreSQL or a provider. Future graph
publication must verify the persisted review/revision association before calling
the adapter. Future edge-review operations must change status explicitly while
preserving original edge source provenance.
