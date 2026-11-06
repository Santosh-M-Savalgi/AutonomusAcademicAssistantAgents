# Sprint 3.3: durable graph publication and confirmed-curriculum integration

## Scope and status

Sprint 3.3 connects the pure Sprint 3.1 graph contracts to the immutable Sprint
2.5 review lifecycle and the Sprint 3.2 identity, event and job repositories.
PostgreSQL owns graph publication metadata and normalized graph rows. MinIO owns
canonical graph artifacts. Redis remains a disposable wake-up mechanism and is
not part of graph correctness.

The graph build starts only after a curriculum revision is confirmed. A
confirmed review creates the graph-build job and `CURRICULUM_CONFIRMED` event
inside its existing caller-owned transaction. The API publishes the Redis
wake-up only after that transaction commits.

## Publication workflow

1. `confirm_review()` validates the exact immutable revision, resolves the
   authenticated actor identity, and atomically changes the review to
   `CONFIRMED`.
2. The same transaction creates an idempotent `graph_build` job containing the
   course, review, revision, revision artifact reference/checksum and actor
   identity. It also inserts the v1 `CURRICULUM_CONFIRMED` learning event.
3. `GraphHandler` claims the job through the existing Postgres lease protocol,
   revalidates the review/revision association and revision artifact checksum,
   and calls the pure confirmed-revision adapter.
4. The handler writes canonical graph JSON to MinIO using a content-addressed
   key, then calls `publish_graph_for_job()` in a new Postgres transaction.
5. Publication revalidates the job payload, confirmed review pointer, graph
   checksum, byte count and attempt lease before creating normalized rows and
   the `GRAPH_BUILT` event. A stale attempt cannot publish.

The graph job identity is deterministic from `(review_id, revision_id)`, so
concurrent or repeated confirmation requests resolve to the same job. The
original confirmer's actor metadata is retained when a later concurrent
request replays an already-confirmed review.

## Durable graph model

Migration `0007_learning_graph_versions` adds:

- `curriculum_graph_versions`: immutable course/revision graph publications,
  parent version, publication source, artifact checksum/size and actor fields;
- `curriculum_graph_nodes`: curriculum-derived and concept nodes with stable
  identities and retained `ReviewElement` provenance;
- `curriculum_graph_concepts`: normalized concept definitions;
- `curriculum_graph_mappings`: explicit or inferred topic-to-concept mappings;
- `curriculum_graph_edges`: directed relationships, independent status and
  per-edge review audit fields;
- `curriculum_successor_versions`: immutable parent/successor revision links
  and explicit element-level lineage.

The graph version plus its child rows are immutable. Edge review creates a new
version, records the old version as its parent, writes a new content-addressed
artifact, and emits either `PREREQUISITE_EDGE_CONFIRMED` or
`PREREQUISITE_EDGE_REJECTED`. Only `PROPOSED` prerequisite edges can be
reviewed, and cycle validation runs against the candidate snapshot before the
new version is inserted.

Published API responses expose graph IDs, checksums, versions, status, history
and typed snapshots. Raw MinIO object references are kept out of responses.
All graph routes require membership in the requested course.

## Successor curricula

`CurriculumSuccessorRequest` records explicit element-level lineage:

- `UNCHANGED`: one identical parent/successor element;
- `REPLACED`: one different successor element;
- `MERGED`: multiple parents to one successor;
- `SPLIT`: one parent to multiple successors.

Lineage IDs must be unique and must belong to the exact parent and successor
revision artifacts. A successor declaration does not mutate either immutable
revision. The persisted record is `DECLARED` until the exact successor revision
is confirmed. The normal confirmation transaction changes matching declarations
to `CONFIRMED`; if the successor is edited afterward, its new revision requires
a new declaration and reconfirmation rather than mutating the old lineage.

## Events and job progress

Learning events remain separate from `job_progress_events`:

| Domain event | Transaction owner |
|---|---|
| `CURRICULUM_CONFIRMED` | Phase 2 review confirmation |
| `GRAPH_BUILT` | fenced graph publication |
| `PREREQUISITE_EDGE_CONFIRMED` | edge-review transaction |
| `PREREQUISITE_EDGE_REJECTED` | edge-review transaction |
| `CURRICULUM_SUCCESSOR_CREATED` | successor declaration transaction |

The worker's stage/progress events continue to use the existing durable job
event stream and are never substituted for learning events.

## Tests

- Graph contract and algorithm tests continue to enforce provenance, fallback,
  direction, DAG and confirmed-only behavior.
- `tests/unit/test_successors.py` covers all lineage shapes and duplicate IDs.
- `tests/integration/test_curriculum_review_runtime.py` covers confirmation
  idempotency, graph job identity, fenced worker publication, artifact-backed
  graph reads, history and domain-event creation.
- `tests/integration/test_migrations.py` verifies migration `0007`, repeatable
  upgrades and populated-data downgrade refusal.
- Live integration uses disposable PostgreSQL, Redis and MinIO only; no model
  provider is called.

## Limitations and future integration points

- The deterministic confirmed-revision adapter does not invent prerequisite
  edges. Future proposal jobs/templates may add `PROPOSED` edges before users
  review them.
- Successor records represent declaration and exact-revision reconfirmation;
  downstream teaching still needs a later sprint to consume successor graphs.
- Graph artifact garbage collection and orphan cleanup remain deferred, as in
  the immutable curriculum revision workflow.
