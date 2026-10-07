"""Trusted extraction source resolution and content-addressed MinIO JSON artifacts."""

import re
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select

from packages.domain.extraction import DocumentSource, ExtractionResult
from packages.domain.jobs import JobErrorCode
from packages.persistence.artifacts import persist_json
from packages.persistence.database import Database
from packages.persistence.models import Document, DocumentVersion
from packages.persistence.object_storage import (
    ObjectIntegrityError,
    ObjectLimitError,
    ObjectStorage,
)


class SourceResolutionError(Exception):
    def __init__(self, code: JobErrorCode):
        self.code = code
        super().__init__(code.value)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


async def resolve_source(
    database: Database, document_id: UUID, course_id: UUID, version_id: UUID | None,
) -> tuple[DocumentSource, str]:
    """Old upload jobs bind version 1, never the mutable latest version or payload key."""

    async with database.session() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise SourceResolutionError(JobErrorCode.DOCUMENT_NOT_FOUND)
        version = (await session.scalars(select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.id == version_id if version_id else DocumentVersion.version_number == 1,
        ))).one_or_none()
        if document.course_id != course_id or document.content_type != "application/pdf" or (
            version is None
        ):
            raise SourceResolutionError(JobErrorCode.INVALID_DOCUMENT)
        key = f"courses/{course_id}/documents/{document_id}/versions/{version.version_number}.pdf"
        if version.storage_key != key:
            raise SourceResolutionError(JobErrorCode.INVALID_DOCUMENT)
        if document.storage_key == version.storage_key and (
            (document.sha256, document.size_bytes, document.page_count)
            != (version.sha256, version.size_bytes, version.page_count)
        ):
            raise SourceResolutionError(JobErrorCode.SOURCE_MISMATCH)
        try:
            source = DocumentSource(
                course_id=course_id, document_id=document_id, version_id=version.id,
                version_number=version.version_number, sha256=version.sha256,
                size_bytes=version.size_bytes, page_count=version.page_count,
            )
        except ValidationError:
            raise SourceResolutionError(JobErrorCode.INVALID_DOCUMENT) from None
        return source, key


def persist_extraction(storage: ObjectStorage, result: ExtractionResult, max_bytes: int) -> str:
    """Validate before writing. Identical concurrent puts have identical bytes and key."""

    result = ExtractionResult.model_validate(result.model_dump())
    content = result.canonical_bytes()
    if len(content) > max_bytes:
        raise SourceResolutionError(JobErrorCode.EXTRACTION_OUTPUT_LIMIT)
    return persist_json(storage, result.artifact_key(), content, max_bytes)


def load_extraction(
    storage: ObjectStorage, reference: str, source: DocumentSource, max_bytes: int,
) -> ExtractionResult:
    prefix = (f"minio://{storage.bucket}/courses/{source.course_id}/documents/"
              f"{source.document_id}/extractions/{source.version_id}/extraction-v1/")
    if not reference.startswith(prefix) or not reference.endswith(".json"):
        raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION)
    digest = reference.removeprefix(prefix).removesuffix(".json")
    if not _SHA256.fullmatch(digest):
        raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION)
    try:
        content = storage.read_artifact(reference.removeprefix(f"minio://{storage.bucket}/"),
                                        max_bytes=max_bytes, sha256=digest)
        result = ExtractionResult.model_validate_json(content)
    except (ValidationError, ObjectIntegrityError, ObjectLimitError):
        raise SourceResolutionError(JobErrorCode.INVALID_EXTRACTION) from None
    if result.source != source:
        raise SourceResolutionError(JobErrorCode.SOURCE_MISMATCH)
    return result
