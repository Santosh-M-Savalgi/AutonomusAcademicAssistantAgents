# Sprint 3.1: Graph contracts, DAG validation and seed templates

## Status

Implemented as a pure, persistence-free Sprint 3.1 increment. This sprint does
not publish graphs, create jobs, expose HTTP routes, resolve student identity,
calculate mastery or select planner actions.

## Contracts and graph semantics

The public contracts are in `packages/domain/graph.py`:

- `GraphNode` represents a curriculum `CONTAINER`, `TOPIC` or `CONCEPT`. A
  confirmed-revision adapter retains the original typed `ReviewElement` for
  curriculum-derived nodes and validates its stable ID, parent, title, source
  origin, source ranges and parse confidence.
- `Concept` is a stable UUID definition with a key, title, provenance,
  confidence and independent verification flag.
- `TopicConceptMapping` supports `EXPLICIT` and `INFERRED_FALLBACK` mappings.
  Inferred mappings must use `INFERRED_FALLBACK` provenance and can never be
  marked verified by the contract. They are therefore visible as a fallback,
  never silently treated as manually verified.
- `GraphEdge` carries edge type, source provenance, confidence and status.
  For `PREREQUISITE_OF`, `source_node_id` is the prerequisite and
  `target_node_id` is the dependent. This direction is used by every traversal
  algorithm.
- `GraphSnapshot` binds graph contents to a `course_id`,
  `curriculum_revision_id` and a positive graph version. `GraphTemplate` is a
  separate versioned artifact and cannot itself represent curriculum
  confirmation.

Topic parentage is hierarchy metadata only. No prerequisite edge is generated
from topic order, topic parentage or list order.

Only `CONFIRMED` prerequisite edges are returned by
`confirmed_prerequisite_edges()` and may be used by future learning gates.
`PROPOSED` edges are informational; `REJECTED` edges remain in the snapshot for
audit but are excluded from candidate and executable prerequisite traversal.
Confidence never changes this rule.

## Algorithms

Pure algorithms are in `packages/curriculum/graph.py` and have no database,
HTTP, object-storage, Redis, clock or randomness dependency:

- Structural contract validation rejects unknown references and self-loops.
- `validate_dag()` checks all non-rejected prerequisite candidates by default,
  including proposed edges, so a proposed candidate cannot hide a cycle.
- `topological_order()` uses Kahn's algorithm with UUID-string tie-breaking.
  It defaults to confirmed edges and can inspect non-rejected candidates with
  `confirmed_only=False`.
- `topological_depth()` computes longest prerequisite distance from roots.
- `unique_descendant_counts()` computes reachability counts without counting a
  shared descendant more than once.
- `descendants()` returns stable topological-order descendants.
- `infer_leaf_topic_concept()` creates one deterministic UUID concept node,
  concept definition and explicitly inferred fallback mapping for an unmapped
  leaf topic. It refuses non-leaf topics and topics that already have a
  mapping.
- `graph_from_confirmed_revision()` validates a Phase 2 `ReviewRecord` and
  `CurriculumRevision`, preserves curriculum element provenance and optionally
  adds only explicit, visibly inferred leaf fallbacks. It never creates
  prerequisite edges from hierarchy.
- `canonical_bytes()` sorts graph collections by stable identifiers before
  JSON serialization, making equivalent input permutations byte-identical.

For `V` nodes and `E` prerequisite edges, Kahn ordering and cycle detection are
`O(V + E)`. Depth is `O(V + E)`. Descendant counts use reverse dynamic
programming over descendant sets; the traversal is linear in the graph plus
the total size of the reachable sets and is `O(V²)` in the dense worst case.

Non-prerequisite relationship types are represented for later graph features,
but DAG traversal and gate enforcement apply only to `PREREQUISITE_OF` edges.

## Seed template provenance

`packages/curriculum/templates.py` provides deterministic v1 templates:

- `algebra_foundations_template()`
- `programming_foundations_template()`
- `seed_template(template_id)` registry lookup

Template node, concept, mapping and edge IDs are UUID5 values derived from a
versioned namespace, template ID and stable key. Both templates contain
explicit topic-to-concept mappings and prerequisite relationships. All template
edges are `PROPOSED`, use `SEED_TEMPLATE` provenance and remain unverified.
Template concepts and mappings are also not automatically verified. A later
curriculum confirmation/edge-review workflow must explicitly confirm any
relationship before it can enforce a gate.

## Tests and coverage

- `tests/unit/test_graph_contracts.py` covers reference identity, inferred
  fallback semantics, self-loop contract validation and both seed templates.
- `tests/unit/test_graph_algorithms.py` covers cycles, self-loops, confirmed
  filtering, topological direction/depth, unique descendants and canonical
  serialization.
- Hypothesis generates arbitrary forward-edge DAG candidates and verifies DAG
  validity, cycle rejection, self-loop rejection, confirmed-edge filtering,
  stable topological ordering, canonical serialization and prerequisite
  direction properties.
- A diamond graph verifies that shared descendants are counted once.

The test dependency `hypothesis==6.144.0` is pinned in `pyproject.toml` and
`uv.lock`.

## Limitations and future integration points

- Graphs are in-memory contracts only. Sprint 3.2+ must add PostgreSQL graph
  persistence and publication without moving these algorithms into the
  persistence layer.
- The hybrid concept fallback does not decide whether a topic is pedagogically
  adequate; it only supplies a stable, visibly inferred placeholder.
- Template mappings and edges do not confirm themselves. Future review APIs
  must preserve their provenance while changing status explicitly.
- No graph diff, graph job, mastery, planner, diagnostic, review or student
  identity behavior is included in this sprint.
