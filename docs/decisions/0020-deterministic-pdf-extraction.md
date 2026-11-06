# ADR 0020: Page-aware extraction artifacts and bounded processing

## Status

Accepted for Sprint 2.3; extends D-08 and the document/artifact ownership model.

## Decision

Use existing MinIO artifact storage plus `jobs.result_ref`. No existing extraction
table exists; adding JSONB storage would duplicate the object-store responsibility
and require a migration without a query use case. The validated JSON artifact
contains schema/policy versions, document/course/version IDs, original checksum,
page text once, line references, hierarchy and summary. Canonical JSON's SHA-256
forms its object name inside a document-version-specific namespace. Re-execution
with the same source/policy produces the same bytes and key. Existing matching
artifacts are reused; mismatches fail instead of overwriting. Concurrent identical
puts are safe on the unversioned application bucket.

The artifact is durable before the handler returns its `minio://bucket/key`
reference. Only the existing fenced PostgreSQL completion makes it authoritative.
An interrupted write/completion can leave an unreferenced artifact; retry converges
on the same key. Do not delete an artifact on uncertain completion because a
concurrent valid attempt may reference it. Future retention/garbage collection is
outside this sprint.

Resolve document and version through PostgreSQL. Legacy jobs without a version ID
mean version **1**, never "latest"; new uploads include the version UUID. Ignore
legacy payload storage keys. Validate course/document/version association and
server-generated key shape, then verify downloaded size and SHA-256.

Run synchronous MinIO retrieval, pypdf and artifact persistence in a disposable
Python subprocess with anonymous temporary files in the working directory, Linux
address-space/CPU/file-size limits, and a parent wall deadline. Parent cancellation
kills and reaps the child; Linux parent-death signaling also terminates it if the
worker is killed. Network responses are closed on all normal/error paths and OS
resource cleanup applies on kill. This is resource isolation, not a general
hostile-code sandbox; pypdf only interprets PDF text, never executes PDF actions.
Credentials pass through a bounded stdin message, never process arguments/logs.

The pure page normalization/detector and domain schemas are independent of worker,
database, MinIO and FastAPI. This deterministic preprocessing does not implement
or replace the later D-09 checkpointed curriculum-generation pipeline. No new
dependency, external provider, schema migration or locked decision change.

## Consequences

Results are structural observations, not a curriculum draft. Empty/scanned pages
remain present with explicit OCR-candidate warnings; no OCR is attempted. Confidence
is a fixed heuristic score, not a calibrated probability. Changing extraction
semantics requires a policy/schema version bump. PDF reading order and table geometry
are limited by pypdf. No student data leaves the configured local infrastructure.
