"""Draft lifecycle metadata uses existing jobs; only committed extraction results are admitted."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from packages.curriculum.drafts import validate_draft_source
from packages.domain.curriculum import CurriculumDraft, DraftJobPayload, draft_identity
from packages.domain.extraction import DocumentSource
from packages.domain.jobs import JobCreatedPayload, JobErrorCode, JobEventType
from packages.persistence.artifacts import persist_json
from packages.persistence.database import Database
from packages.persistence.extractions import SourceResolutionError, load_extraction, resolve_source
from packages.persistence.job_events import append_event
from packages.persistence.models import Job
from packages.persistence.object_storage import ObjectStorage


async def extraction_source(
    database: Database, extraction_id: UUID,
) -> tuple[DocumentSource, str]:
    async with database.session() as session:
        job = await session.get(Job, extraction_id)
        if job is None or job.job_type != "syllabus_ingestion":
            raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION)
        if job.status != "SUCCEEDED" or not job.result_ref:
            raise SourceResolutionError(JobErrorCode.EXTRACTION_NOT_READY)
        try:
            document_id = UUID(job.payload["document_id"])
            course_id = UUID(job.payload["course_id"])
            version = job.payload.get("document_version_id")
            version_id = UUID(version) if version else None
        except (ValueError, KeyError, TypeError):
            raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION) from None
        reference = job.result_ref
    source, _ = await resolve_source(database, document_id, course_id, version_id)
    return source, reference


async def enqueue_draft(database: Database, course_id: UUID, extraction_id: UUID) -> UUID:
    source, reference = await extraction_source(database, extraction_id)
    if source.course_id != course_id:
        raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION)
    return await enqueue_draft_for_source(database, course_id, extraction_id, source, reference)


async def enqueue_draft_for_source(
    database: Database, course_id: UUID, extraction_id: UUID,
    source: DocumentSource, reference: str,
) -> UUID:
    identity = draft_identity(extraction_id, reference)
    payload = DraftJobPayload(course_id=course_id, document_id=source.document_id,
                              document_version_id=source.version_id,
                              extraction_job_id=extraction_id)
    async with database.session() as session, session.begin():
        result = await session.execute(insert(Job).values(
            id=identity, job_type="curriculum_draft", payload=payload.model_dump(mode="json"),
            status="PENDING", lane="batch", priority=0, attempts=0, max_attempts=3,
            parent_job_id=extraction_id, idempotency_key=f"curriculum-draft:{identity}",
        ).on_conflict_do_nothing(index_elements=[Job.idempotency_key]).returning(Job.id))
        if result.scalar_one_or_none() is not None:
            job = await session.get(Job, identity)
            assert job is not None
            append_event(
                session, job, JobEventType.CREATED,
                JobCreatedPayload(job_type=job.job_type), attempt=0, idempotency_key="created",
            )
    return identity


async def draft_record(database: Database, identity: UUID) -> Job | None:
    async with database.session() as session:
        return (await session.scalars(select(Job).where(
            Job.id == identity, Job.job_type == "curriculum_draft",
        ))).one_or_none()


def persist_draft(
    storage: ObjectStorage, draft: CurriculumDraft, extraction_max_bytes: int, max_bytes: int,
) -> str:
    draft = CurriculumDraft.model_validate(draft.model_dump())
    extraction = load_extraction(storage, draft.extraction_ref, draft.source, extraction_max_bytes)
    validate_draft_source(draft, extraction)
    return persist_json(storage, draft.artifact_key(), draft.canonical_bytes(), max_bytes)


def load_draft(
    storage: ObjectStorage, reference: str, identity: UUID, extraction_id: UUID,
    extraction_ref: str, source: DocumentSource, max_bytes: int,
) -> CurriculumDraft:
    import re

    prefix = (f"minio://{storage.bucket}/courses/{source.course_id}/documents/{source.document_id}/"
              f"drafts/{source.version_id}/curriculum-draft-v1/{identity}/")
    if not reference.startswith(prefix) or not reference.endswith(".json"):
        raise ValueError("Invalid draft namespace")
    digest = reference.removeprefix(prefix).removesuffix(".json")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid draft reference")
    content = storage.read_artifact(reference.removeprefix(f"minio://{storage.bucket}/"),
                                    max_bytes=max_bytes, sha256=digest)
    draft = CurriculumDraft.model_validate_json(content)
    if (draft.id != identity or draft.source != source or draft.extraction_job_id != extraction_id
            or draft.extraction_ref != extraction_ref):
        raise ValueError("Draft association mismatch")
    extraction = load_extraction(storage, extraction_ref, source, max_bytes)
    validate_draft_source(draft, extraction)
    return draft
