# Sprint 2.1: Curriculum upload and job foundation

## Vertical slice

`POST /api/v3/courses/{course_id}/syllabus` authenticates the caller, checks
course membership, validates a PDF, stores it in MinIO, and transactionally
persists the document, version, `SYLLABUS_UPLOADED` event, and `PENDING`
`syllabus_ingestion` job. The endpoint returns `202` with `document_id` and
`job_id`; parsing and worker execution are intentionally deferred.

## Limits and validation

- Maximum upload size: 20 MiB (`MAX_UPLOAD_SIZE_BYTES`).
- Maximum PDF pages: 500 (`MAX_PDF_PAGES`).
- Upload reads use bounded chunks (`UPLOAD_CHUNK_SIZE_BYTES`) and a temporary
  file rather than unrestricted application memory.
- PDF magic bytes are sniffed independently of filename and Content-Type.
- pypdf readability and encryption checks are enforced.
- Common archive, script, launch, attachment, rich-media, and XFA markers are
  rejected when detectable.
- Original filenames are sanitized for metadata; storage keys are generated
  exclusively from server-side course/document IDs.

## Storage and idempotency

The MinIO object is uploaded before the database transaction. If persistence
fails, compensating object deletion is attempted and the request fails. The
database remains the source of truth. Caller idempotency keys are scoped to the
authenticated subject and course, hashed into a bounded database key, and map
to deterministic document/job IDs. Retries return the original accepted IDs.

## Models and migration

Migration `0002_curriculum_upload_foundation` adds minimal `courses`,
`course_members`, `documents`, `document_versions`, `jobs`, and
`learning_events` tables. Jobs include the Phase 2 lifecycle, lease fields,
retry fields, idempotency uniqueness, and claiming indexes.

## Known limitations

The worker loop, PDF text extraction, structure detection, curriculum editing,
OCR, SSE progress, and curriculum graph construction belong to later sprints.
The current validator rejects detectable active/embedded PDF content rather than
attempting to execute or sanitize it.
