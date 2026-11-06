# ADR 0022: PostgreSQL review pointers and immutable revision artifacts

## Status

Accepted for Sprint 2.5.

## Decision

Represent one generated draft's human-review lifecycle with additive PostgreSQL
`curriculum_reviews` and `curriculum_revisions` metadata. The review row is the
source of truth for course/document ownership, `DRAFT -> UNDER_REVIEW -> CONFIRMED`
status, current revision, confirmation actor/time and optimistic revision number.
Revision rows are immutable pointers to canonical MinIO JSON; complete curriculum
content is not duplicated in PostgreSQL. The original Sprint 2.4 `jobs.result_ref`
artifact is never overwritten.

Begin-review copies the validated generated draft to revision 1 in a review-specific
artifact namespace. Save uses full validated element snapshots: this supports title,
description/outcome, add/remove, move and sibling reorder operations without exposing
storage keys or applying unchecked patches. Existing extracted/generated IDs and exact
source references are immutable; human-created elements use `origin=HUMAN`, stable
server-validated IDs and no source claims.

Revision writes use a locked review row plus expected revision number and an idempotent
content/actor key. A concurrent different edit receives `STALE_REVISION`; a repeated
identical request returns the already-created revision. Confirmation locks the same row,
validates the current artifact and records actor/time atomically. Confirmed reviews have
no edit transition; repeated confirmation of the same revision is idempotent.

## Consequences

The API can retrieve review history and confirmed state from PostgreSQL metadata while
revalidating every MinIO artifact. Artifact/database partial failure can leave an
unreferenced object, which is safe and recoverable. No downstream teaching, graph,
embedding, SSE or frontend operation starts on confirmation. Garbage collection of
orphaned/old revision artifacts is deferred. Revision content is currently submitted
as a complete typed snapshot rather than a server-side operation log; the resulting
revision history remains auditable and deterministic.
