"""Transactional syllabus upload submission service."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import structlog
from sqlalchemy.exc import IntegrityError

from apps.api.documents.validation import ValidatedPDF
from apps.api.runtime import RuntimeResources
from packages.domain.jobs import JobCreatedPayload, JobEventType
from packages.persistence import (
    CourseMember,
    Document,
    DocumentVersion,
    Job,
    LearningEventRecord,
    find_course,
    find_course_member,
    find_job_by_idempotency_key,
)
from packages.persistence.job_events import append_event
from packages.persistence.job_wakeups import notify_job_events

logger = structlog.get_logger("aaa.documents")


class UploadSubmissionError(RuntimeError):
    """Safe error returned when the upload cannot be accepted."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def submit_syllabus_upload(
    resources: RuntimeResources,
    course_id: UUID,
    actor_subject: str,
    idempotency_header: str | None,
    validated: ValidatedPDF,
) -> tuple[UUID, UUID]:
    """Store the PDF and atomically create its document, event, and job records."""

    database_key = _database_idempotency_key(course_id, actor_subject, idempotency_header)
    document_id = uuid5(NAMESPACE_URL, f"aaa-v3/document/{database_key}")
    job_id = uuid5(NAMESPACE_URL, f"aaa-v3/job/{database_key}")
    storage_key = f"courses/{course_id}/documents/{document_id}/versions/1.pdf"

    async with resources.database.session() as session:
        course = await find_course(session, course_id)
        if course is None:
            raise UploadSubmissionError("COURSE_NOT_FOUND", "Course not found.", 404)
        member: CourseMember | None = await find_course_member(session, course_id, actor_subject)
        if member is None:
            raise UploadSubmissionError(
                "COURSE_UPLOAD_FORBIDDEN",
                "You do not have permission to upload to this course.",
                403,
            )

        existing_job = await find_job_by_idempotency_key(session, database_key)
        if existing_job is not None:
            existing_document_id = _document_id_from_payload(existing_job.payload)
            return existing_document_id, existing_job.id

        object_uploaded = False
        try:
            await resources.object_storage.ensure_bucket()
            validated.file.seek(0)
            await resources.object_storage.put_object(
                storage_key,
                validated.file,
                validated.size_bytes,
                content_type="application/pdf",
                metadata={"x-amz-meta-original-filename": validated.original_filename},
            )
            object_uploaded = True

            document = Document(
                id=document_id,
                course_id=course_id,
                original_filename=validated.original_filename,
                content_type="application/pdf",
                size_bytes=validated.size_bytes,
                sha256=validated.sha256,
                page_count=validated.page_count,
                storage_key=storage_key,
                uploaded_by=actor_subject,
            )
            version = DocumentVersion(
                id=uuid4(),
                document_id=document_id,
                version_number=1,
                storage_key=storage_key,
                size_bytes=validated.size_bytes,
                sha256=validated.sha256,
                page_count=validated.page_count,
            )
            job = Job(
                id=job_id,
                job_type="syllabus_ingestion",
                payload={
                    "course_id": str(course_id),
                    "document_id": str(document_id),
                    "document_version_id": str(version.id),
                    "storage_key": storage_key,
                },
                status="PENDING",
                priority=0,
                lane="batch",
                attempts=0,
                max_attempts=3,
                idempotency_key=database_key,
            )
            event = LearningEventRecord(
                event_id=uuid4(),
                event_type="SYLLABUS_UPLOADED",
                actor_subject=actor_subject,
                course_id=course_id,
                payload={"document_id": str(document_id), "job_id": str(job_id)},
                correlation_id=job_id,
            )
            session.add_all([document, version, job, event])
            append_event(
                session, job, JobEventType.CREATED, JobCreatedPayload(job_type=job.job_type),
                attempt=0, idempotency_key="created",
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing_job = await find_job_by_idempotency_key(session, database_key)
            if existing_job is not None:
                return _document_id_from_payload(existing_job.payload), existing_job.id
            if object_uploaded:
                await _compensate_storage(resources, storage_key)
            raise UploadSubmissionError(
                "UPLOAD_CONFLICT",
                "The upload could not be committed safely.",
                409,
            ) from None
        except UploadSubmissionError:
            await session.rollback()
            if object_uploaded:
                await _compensate_storage(resources, storage_key)
            raise
        except Exception as error:
            await session.rollback()
            if object_uploaded:
                await _compensate_storage(resources, storage_key)
            logger.error("syllabus_upload_failed", error_type=type(error).__name__)
            raise UploadSubmissionError(
                "UPLOAD_UNAVAILABLE",
                "The syllabus could not be stored.",
                503,
            ) from error

    # Publication is outside both the DB transaction and storage compensation block.
    # A missing notification must never roll back an accepted upload or delete its object.
    await notify_job_events(resources.redis, job_id)
    return document_id, job_id


def _database_idempotency_key(
    course_id: UUID,
    actor_subject: str,
    idempotency_header: str | None,
) -> str:
    """Scope caller keys to the authenticated subject and course."""

    request_key = idempotency_header or str(uuid4())
    source = f"{course_id}:{actor_subject}:{request_key}".encode()
    return f"syllabus:{hashlib.sha256(source).hexdigest()}"


def _document_id_from_payload(payload: Mapping[str, object]) -> UUID:
    """Read the original document ID from an existing idempotent job."""

    document_id = payload.get("document_id")
    if not isinstance(document_id, str):
        raise UploadSubmissionError("UPLOAD_CONFLICT", "Stored upload state is invalid.", 409)
    try:
        return UUID(document_id)
    except ValueError as error:
        raise UploadSubmissionError(
            "UPLOAD_CONFLICT", "Stored upload state is invalid.", 409
        ) from error


async def _compensate_storage(resources: RuntimeResources, storage_key: str) -> None:
    """Best-effort cleanup after a database failure, with operational logging."""

    try:
        await resources.object_storage.delete_object(storage_key)
    except Exception as error:
        logger.error("syllabus_storage_compensation_failed", error_type=type(error).__name__)
