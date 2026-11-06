# ADR 0021: Checkpointed provider boundary for curriculum drafts

## Status

Accepted for Sprint 2.4.

## Decision

Curriculum draft generation is a separate `curriculum_draft` child job. A completed
`syllabus_ingestion` job inserts it using a deterministic idempotency identity based
on the extraction job and artifact reference. The job uses a bounded LangGraph graph
with one node invocation per extracted root and a vendor-neutral `CurriculumProvider`.
The current mock profile injects `FakeProvider`; no provider SDK or external model is
configured. Provider bytes are untrusted JSON and must pass independent Pydantic,
provenance, identity and hierarchy validation before assembly or persistence.

Use `langgraph-checkpoint-postgres` in an isolated PostgreSQL schema provisioned by
Alembic revision `0003_curriculum_checkpoints`. Checkpoint threads include the stable
draft identity and worker attempt, so stale work cannot resume into a replacement
attempt. Checkpointed provider values are revalidated on resume. The existing worker
lease remains the only authority for job completion.

Draft output is an immutable MinIO JSON artifact referenced by `jobs.result_ref`.
No curriculum tables are added until editing/confirmation requires queryable domain
state. The draft's status is explicitly `DRAFT`; this job cannot approve, confirm,
edit or construct a graph. `POST` is an idempotent request to enqueue an existing
completed extraction and `GET` is authenticated/read-only status and artifact access.

## Consequences

Provider integration can later replace `FakeProvider` behind the same contract and
gateway boundary without changing domain validation or persistence. A large syllabus
is bounded by root/output/time limits; a retry resumes validated generation prefix or
restarts safely from the same deterministic identity. An orphaned draft artifact is
safe on uncertain completion and is not deleted by a competing attempt. Real LLM
provider, curriculum editing/confirmation, graph construction, embeddings, OCR and
SSE remain deferred. The additional checkpoint dependency and migration are the only
new runtime architecture for this sprint.
