# Sprint 2.3: PDF extraction and deterministic structure detection

## Scope and ownership

The registered `syllabus_ingestion` worker consumes the uploaded document/version
and produces a validated, durable extraction artifact. It consumes no mastery
state, produces no learning evidence, and makes no curriculum graph/plan changes.
No OCR, provider (real or fake), embeddings, draft generation or UI is involved.

## Files

Created:
- `packages/domain/extraction.py`: versioned Pydantic contracts, traceability
  validation, stable node IDs and canonical JSON/artifact names.
- `packages/curriculum/pdf.py`: pypdf extraction and line-preserving normalization.
- `packages/curriculum/structure.py`: pure deterministic heading/hierarchy detector.
- `packages/persistence/extractions.py`: trusted source resolution and artifact storage.
- `apps/worker/extraction_config.py`: extraction-only bounds.
- `apps/worker/extraction_process.py`: disposable Linux process and safe IPC contracts.
- `apps/worker/syllabus.py`: production registry, payload validation and orchestration.
- `tests/pdf_fixtures.py`: programmatic synthetic PDFs, including Unicode font mappings.
- `tests/unit/test_pdf_extraction.py`, `test_structure_detection.py`,
  `test_extraction_storage.py`, `test_extraction_process.py`.
- `tests/integration/test_syllabus_extraction.py`.
- `docs/decisions/0020-deterministic-pdf-extraction.md`, this report.

Modified:
- `packages/domain/jobs.py`: safe extraction error codes.
- `packages/persistence/object_storage.py`: bounded download, response cleanup,
  optional bounded HTTP pool for extraction subprocesses.
- `apps/worker/__main__.py`: production syllabus registration.
- `apps/worker/handlers.py`: update historical empty-registry module description.
- `apps/api/documents/service.py`: explicit version UUID in new jobs, retaining the
  existing upload transaction and validation.
- `.env.example`, `docker-compose.yml`, `infra/compose/test.yml`, `docs/STACK.md`:
  settings, local MinIO worker wiring and operational documentation.

## Retrieval, identity and validation

`SyllabusPayload` accepts course/document UUIDs and optional version UUID; all
other fields except the legacy storage key are rejected. That legacy key is
ignored. PostgreSQL resolves the course/document/version relationship and the
server-generated `courses/{course}/documents/{document}/versions/{n}.pdf` key.
Jobs without a version UUID always mean version **1**, even when later versions
exist. Explicit versions must belong to the requested document. Source metadata
includes document, version and course identities, checksum, size and page count.

Download reads at most 64 KiB per chunk into an anonymous temporary file. It
enforces the configured upload-size limit and verifies exact size and SHA-256
against database version metadata. Responses are closed and released even on
failure. Metadata/key mismatches, missing records and missing objects have explicit
safe failure codes. New uploads retain all existing Sprint 2.1 validation.

## Extraction architecture and bounds

The worker resolves DB references, then launches `apps.worker.extraction_process`
using the existing Python interpreter (no shell). That child performs synchronous
MinIO I/O, pypdf parsing and validated artifact persistence. Credentials travel in
a bounded stdin message; stdout carries only a bounded result reference/error code.
Child stderr and pypdf diagnostics are suppressed to prevent content logging.

The parent wall deadline covers lookup, download, extraction and storage. The
child has Linux address-space, CPU and temporary-file size limits. Cancellation
kills and reaps it, including cancellation racing subprocess creation. Linux
parent-death signaling stops it if the worker is killed. Anonymous temporary
files in the working directory are closed by context managers or kernel cleanup
on process death, with no named PDF residue. Default concurrency 2 allows at most
two such children per worker; default address-space limit is 512 MiB each.

Page extraction uses pypdf `strict=True`, rejects encryption/malformed inputs,
checks the page cap and stored page count, and checks text/serialized artifact
output bounds. It never accesses attachments or executes actions, JavaScript,
embedded files or external processing APIs. Process isolation is a resource bound,
not a general-purpose hostile-code sandbox.

## Page text and traceability

Pages retain original one-based numbers and individual normalized text fields.
There is no duplicate full-document text. CRLF/CR becomes LF; tabs become four
spaces, nonbreaking spaces become spaces, trailing spaces are removed, repeated
interior gaps become two spaces, indentation is retained up to 16 spaces. Meaningful
newlines, numbering, bullets, Unicode and table-like column gaps remain; lines
are never concatenated or dehyphenated. Leading/trailing empty lines are trimmed.

Source references are one-based inclusive ranges in each **normalized** page's
lines, not PDF byte offsets or visual coordinates. Heading nodes reference their
source title; remaining nonempty lines are preserved as ordered unclassified
ranges pointing into page text. Empty and whitespace-only pages remain with
`OCR_CANDIDATE` and `NO_EXTRACTABLE_TEXT`. Overall `NO_TEXT`/`LOW_TEXT` is explicit;
no text is invented and no claim is made that an empty page necessarily is scanned.

## Structure rules and confidence

`MODULE`, `UNIT`, `CHAPTER`, `SECTION`, `TOPIC`, `SUBTOPIC` are structural observations,
not curriculum entities. Fixed heuristic scores are deliberately not probabilities:

| Rule | Score |
|---|---:|
| Explicit Module/Unit/Chapter/Section/Topic plus Arabic or valid Roman numbering | 0.98 |
| Decimal numbering with a known numeric parent | 0.90 |
| Decimal numbering without a known numeric parent | 0.80 |
| Exact common syllabus heading (Course Objectives, Learning Outcomes, etc.) | 0.85 |
| At least two distinct all-caps, multiword headings surrounded by blank lines | 0.65 |

All candidates are limited to 120 characters/14 words, avoid sentence-ending
punctuation and multi-column gaps. Bare numbered titles start with an uppercase
character and numeric components 1–99 (avoids academic years). Keyword headings
do not require title capitalization. Isolated short/capitalized lines are not
sufficient. Ambiguous numbered candidates remain unclassified with a warning.

Explicit keyword hierarchy uses the order above; peers pop the current stack.
Numeric prefixes take precedence where available. Bare depth-1 numbering starts
a TOPIC; depth 2 without a topic parent starts a SECTION; depth 3 under a SECTION
is a TOPIC; deeper levels are SUBTOPIC. Numeric descendants of a TOPIC/SUBTOPIC
remain SUBTOPIC. A new Module/Unit/Chapter clears the numeric context. Missing
parents are not invented. Repeated identical headings get different IDs from their
source locations. UUID5 IDs include version identity, source checksum, policy,
type, page, line range and title.

The schema rejects duplicate IDs, invalid or forward parents/cycles, hierarchy
rank inversions, unordered nodes, invalid page/line references, invented titles,
overlapping or omitted content references, invalid schema versions and inconsistent
summaries. Serialization is UTF-8 JSON with sorted keys and compact separators,
without timestamps or attempt IDs.

## Persistence, idempotency and completion

ADR 0020 evaluates PostgreSQL JSONB against existing MinIO/result references.
The existing architecture suffices: **no new table or migration**. Artifact paths:

`courses/{course}/documents/{document}/extractions/{version_uuid}/extraction-v1/{json_sha256}.json`

The artifact includes source checksum/identity, schema `extraction-v1`, policy
`syllabus-structure-v1`, useful-text threshold, pages, nodes, unclassified references,
warnings and summary. Validation is repeated immediately before persistence.
Existing artifacts are bounded-read and checksum-verified; matching bytes reuse
the key and conflicting bytes fail instead of overwriting. Concurrent identical
puts converge on identical bytes and one key in the unversioned application bucket.
Different documents/versions have separate namespaces.

The handler returns `minio://{bucket}/{key}` only after storage succeeds. The generic
worker then applies its existing attempt/owner/lease fence to PostgreSQL completion.
An artifact write failure cannot report success. A failed completion transaction
leaves RUNNING for reaping, and retry reuses the durable artifact. Unreferenced
artifacts are deliberately retained on uncertain completion; deleting them could
break another successful attempt. PostgreSQL remains authoritative for job state.

## Failure behavior and registration

`create_handler_registry` registers only `syllabus_ingestion`; unknown types still
fail `UNKNOWN_JOB_TYPE`. Missing/invalid source, malformed/encrypted PDF, integrity
mismatch, output/page/size limit, timeout or process resource exhaustion fail with
explicit permanent codes. Temporary storage/DB failures and unexpected internal
errors use bounded worker retry policy and safe enum codes. Timeouts are permanent
for the current configuration to avoid repeated expensive parsing. A process restart
interruption follows Sprint 2.2 `WORKER_SHUTDOWN` retry/exhaustion behavior.

The handler allows work already running at shutdown to finish during the worker
grace period; after cancellation its child is killed. Lease loss suppresses stale
completion. An orphan artifact is harmless and a fresh attempt is idempotent.

## Security and operation

- Object names come from validated DB metadata, never caller keys, filenames or URLs.
- Configured local PostgreSQL/MinIO are the only processing dependencies; no egress
  to student-content APIs or model providers.
- Logs contain operational IDs/status codes, never text, payloads or credentials.
- API authorization and upload validation remain in force.
- Redis continues to provide optional wake-up hints; PostgreSQL polling is independent.
- `.env.example`/`docs/STACK.md` list the four extraction settings. Upload-size/page
  settings are reused and Compose passes the same overrides to API and worker.

## Verification

Executed on 2026-10-03 in the WSL-native repository; host Python 3.13.16, shared
application image Python 3.12.15. **65 new cases**: 46 unit and 19 live integration.
Full collection: 157 unit cases and 56 integration cases (one integration case is
an offline migration check).

| Command/check | Actual result |
|---|---|
| `make check` | PASS: Ruff; strict Mypy on 24 package files; all 5 import contracts kept; **158 passed, 55 explicit live-service skips**, 213 collected |
| `make test` | PASS: **158 passed, 55 explicit live-service skips**, 213 collected |
| `make integration` | PASS: **56 passed, zero skips** in 61.29 seconds |
| `uv run --locked --group dev mypy --strict packages apps/worker` | PASS: **32 source files** |
| `docker compose --profile mock config --quiet` | PASS |
| `docker compose --env-file /dev/null -f infra/compose/test.yml --profile worker config --quiet` | PASS |
| `docker compose --env-file /dev/null -f infra/compose/test.yml --profile worker build worker` | PASS: shared `aaa-v3-api` image built |
| Container authenticated upload → registered worker → artifact | PASS: job SUCCEEDED with a validated two-page artifact, correct document/version association, hierarchy and page references |
| Container `/healthz` and `/readyz` | PASS: both HTTP 200; readiness confirmed PostgreSQL, Redis and authenticated MinIO |
| Container worker SIGTERM | PASS: exit 0; structured start/persist/success/stop logs without PDF text or credentials |
| `git diff --check` / `git diff --cached --exit-code` | PASS; no staged changes |

All 55 live cases skipped by default were explicitly executed by `make integration`.
That includes the original Sprint 2.1 upload tests, migration upgrade/downgrade,
resource isolation/readiness and all Sprint 2.2 concurrency/recovery tests.

The new live suite exercises authenticated synthetic upload, actual child extraction,
durable storage before completion, concurrent artifact reuse, legacy and explicit
version binding, untrusted payload-key rejection by non-use, missing/wrong references,
missing/corrupt/encrypted/malformed objects, size/checksum mismatches, temporary MinIO
and DB faults, real PostgreSQL completion rollback and retry, interruption while
the downloaded PDF is open, hard timeout, and unchanged unsupported-type behavior.
Unit tests additionally cover Unicode/table-like text, empty/whitespace pages,
source/schema validation, conservative heuristics, limits, failed artifact writes,
conflict protection, file/response cleanup and cancellation racing process creation.

The smoke used unique project `aaa-v3-extraction-smoke-51c088c12a1a`, random loopback
ports, tmpfs services and synthetic data. Existing migrations ran **only in its
disposable PostgreSQL**. A separately started API container used the shared image;
the actual Compose worker processed its upload. All smoke containers and its network
were removed, with absence verified. No development DB was migrated.

Implementation checks initially found Ruff `E501` (two long declarations) and Mypy
`Argument "status" to "ExtractionSummary" has incompatible type "str"; expected
"Literal['TEXT', 'LOW_TEXT', 'NO_TEXT']"`. Line wrapping and an explicit literal
annotation fixed these; the full gates above were then rerun successfully. No test
assertions were weakened and no additional skips were introduced. The sole remaining
test warning is the pre-existing Starlette use of deprecated `anyio.abc.BlockingPortal`.

## Known limitations and approvals

Reading order/font encodings and table geometry are limited by pypdf. This stage
retains table-like text; it does not infer cells or semantic curriculum relationships.
Conservative heuristics may miss unusual headings or misclassify numbered prose;
unclassified content remains available for Sprint 2.4. Empty scans produce a traceable
artifact and warnings, not OCR. OCR and LLM-based curriculum draft extraction are deferred.

Linux/WSL is required for process resource limits and parent-death signaling. Resource
ceilings can reject valid but expensive PDFs; configuration changes allow later
reprocessing. Runtime policy/schema versions must change with extraction semantics.
No extraction checkpoint within a PDF; a retry restarts bounded extraction. Artifact
retention/garbage collection and bucket versioning are not configured here. Historical
terminal Sprint 2.2 unsupported jobs are not automatically resurrected.

No dependency was added, no locked architecture decision was changed, no development
migration was run, and no decision requires additional approval. The later D-09
curriculum pipeline remains outside this deterministic preprocessing stage.

## Git safety

Work is confined to `/home/smsav/projects/AAAv3`. All existing Sprint 2.1/2.2 tracked
and untracked work is preserved. No staging, commits, reset, clean, stash, revert or
history rewriting. Ignored source documents and `__agent__/` bookkeeping are untouched.
No Windows paths accessed. Test cleanup targets only fixture-owned resources; no
development volume deletion or development database migration.
Final status/index review confirmed all changes remain unstaged. No test/smoke
containers or networks remain. The existing `aaa-v3_postgres_data`, `aaa-v3_redis_data`
and `aaa-v3_minio_data` volumes still exist.
