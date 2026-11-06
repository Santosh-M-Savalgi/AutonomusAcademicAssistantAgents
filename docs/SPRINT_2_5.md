# Sprint 2.5: Curriculum review, editing and confirmation

## Objective

Sprint 2.5 adds a human-controlled lifecycle around the Sprint 2.4 generated draft:

`DRAFT -> UNDER_REVIEW -> CONFIRMED`

The generated draft remains immutable. Review revisions and confirmation metadata are
stored separately. Confirmation never starts teaching, graph construction, assessment,
mastery or planning.

## Files created

- `packages/domain/review.py`: review status/error contracts, revision model, hierarchy,
  provenance, transition and confirmation validation.
- `packages/persistence/review.py`: review/revision service, optimistic concurrency,
  immutable artifact pointers, confirmation and revision history.
- `alembic/versions/0004_curriculum_review.py`: additive review/revision metadata tables.
- `tests/unit/test_curriculum_review.py`: pure transition, edit, provenance and hierarchy tests.
- `tests/integration/test_curriculum_review_runtime.py`: disposable full lifecycle, authorization,
  stale revisions, idempotent repeats and original artifact immutability.
- `docs/decisions/0022-curriculum-review-revisions.md`, this report.

## Files modified

- `packages/domain/curriculum.py`: optional review-edit fields, human origin and safe
  source-node handling while preserving Sprint 2.4 generated contracts.
- `packages/persistence/models.py`, `packages/persistence/__init__.py`: review and
  revision metadata models/exports.
- `packages/persistence/drafts.py`: existing draft source/relation conventions retained.
- `apps/api/curriculum.py`: authenticated review, revision, confirmation and confirmed-read
   routes plus typed request/response schemas.
- `tests/integration/test_migrations.py`: revision head and repeatable migration assertions.
- `tests/conftest.py`: integration worker timing defaults that prevent lease expiry during the
  dead-Redis polling case under the complete suite.

## Review lifecycle and domain model

`ReviewStatus` is closed and centrally transitions only `DRAFT -> UNDER_REVIEW` and
`UNDER_REVIEW -> CONFIRMED`; `CONFIRMED` is terminal. The review row records course,
document/version, originating draft job/reference, current revision pointer, revision
number, actor metadata and confirmation actor/time. `CurriculumRevision` records review,
draft/source identity, parent revision, revision number, actor and immutable typed elements.

Begin-review validates the completed Sprint 2.4 draft and creates revision 1 as a separate
review artifact. Existing generated/extracted IDs, types and source ranges remain intact.
Review elements may edit title, description and learning outcomes; may reorder/move valid
nodes; may remove subtrees; and may add `HUMAN` elements. A human element has a stable UUID,
has no source node or source-page reference, and is never presented as source-derived.

## Editing and validation

The save endpoint accepts a complete typed revision snapshot. This is the editing contract
for title/description/outcome changes, add/remove, sibling reorder and parent moves. The
server validates:

- unique IDs and contiguous order;
- parent existence, parent-before-child ordering and permitted hierarchy ranks;
- absence of cycles/orphans;
- extracted/generated identity, type and exact source provenance;
- empty provenance for human-created elements;
- valid source pages and required titles;
- preserved origin and draft/source relationships.

Removing a parent while retaining a child is rejected. Removing a subtree is permitted.
The original draft is loaded and revalidated before saving, so client-submitted IDs and
course/document references cannot substitute another resource.

## Revision concurrency and persistence

`curriculum_reviews` is PostgreSQL lifecycle truth. `curriculum_revisions` contains one
immutable metadata row per revision and a MinIO artifact pointer, SHA-256 and content size.
Revision content is canonical JSON under:

`courses/reviews/{review_id}/revisions/{revision_id}/curriculum-review-v1/{sha256}.json`

The generated Sprint 2.4 artifact remains at its original key and is never written by
review code. Save locks the review row and requires the caller's `expected_revision`.
Different concurrent edits produce `STALE_REVISION`; identical repeated submissions use
a stable content/actor idempotency key and return the existing revision. Confirmation
locks and rechecks the current revision before recording `CONFIRMED`, `confirmed_by` and
`confirmed_at`. A repeated confirmation for the same revision succeeds without change.
Artifacts are persisted before metadata success; orphaned objects after uncertain database
failure are safe and retained for later cleanup.

## API and authorization

All routes require the existing Bearer authentication dependency and course membership:

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v3/courses/{course_id}/curriculum/drafts/{draft_id}/review` | Begin or return review revision 1 |
| `GET` | `/api/v3/curriculum/{draft_id}/review` | Read current review/revision |
| `GET` | `/api/v3/curriculum/{draft_id}/review/revisions` | Read immutable revision history |
| `PUT` | `/api/v3/curriculum/{draft_id}/review/revisions` | Save an expected-revision snapshot |
| `POST` | `/api/v3/curriculum/{draft_id}/confirm` | Explicitly confirm expected revision |
| `GET` | `/api/v3/curriculum/{draft_id}/confirmed` | Read only after confirmation |

Routes expose typed revision content and lifecycle metadata, not MinIO keys. Cross-course
draft IDs, missing membership, stale revisions, invalid transitions and confirmed edits
return safe 403/404/409/422 responses. No API route invokes an LLM or begins downstream work.

## Testing and exact verification

The review unit suite contains **8 passed tests** covering transitions, human provenance,
title/description/outcome edits, invalid IDs/provenance, removal/orphan rules, reorder,
confirmation preconditions and stable revision identity. The review live suite contains
**4 passed tests** covering upload → extraction → draft → review → edit → stale conflict →
confirmation, duplicate save/confirm idempotency, confirmed immutability, authenticated
confirmed read, revision history, cross-course rejection and original artifact byte
immutability.

Final commands on 2026-10-03, after the complete implementation was finished, produced:

| Command/check | Result |
|---|---|
| `make test` | **179 passed, 63 skipped**, 1 expected Starlette/AnyIO warning |
| `make check` | Ruff passed; strict Mypy for `packages` passed on 35 files; import contracts 5 kept/0 broken; pytest **179 passed, 63 skipped**, 1 expected warning |
| `make integration` | **64 passed**, 1 expected Starlette/AnyIO warning |
| `uv run --locked --group dev mypy --strict packages apps/worker` | **Success**, no issues in 44 source files |
| Compose configuration/image/health checks | Compose config passed for mock and worker profiles; shared API/worker image build passed on retry after a transient BuildKit snapshot-export error; migration `0004` applied in Compose; `/healthz` and `/readyz` returned OK with PostgreSQL, Redis and MinIO healthy; worker stopped cleanly with exit 0 |

The existing Starlette/AnyIO deprecation warning is expected to remain. No new dependency
was added in Sprint 2.5.

## Limitations and deferred work

- No frontend editor or SSE progress stream.
- Review saves use complete snapshots, not an operation log; immutable revision history
  still preserves every saved state.
- No instructor-specific role policy beyond existing course membership; later RBAC can
  narrow confirmation permissions.
- No graph construction, embeddings, retrieval, teaching, assessment or mastery starts
  after confirmation.
- Artifact garbage collection is deferred.

## Safety confirmation

All work is confined to `/home/smsav/projects/AAAv3`. No Windows paths or ignored source
documents were accessed for modification. Existing tracked/untracked Sprint 2.1–2.4 work
and `__agent__/` are preserved. Nothing was staged or committed; no Git history operation,
reset, clean, stash or revert was performed. No development database or Docker volume was
deleted. Only disposable integration resources are cleaned up. Sprint 2.6 was not started.
