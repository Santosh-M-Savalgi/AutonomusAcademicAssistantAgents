"""Authenticated syllabus upload API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from apps.api.auth.dependencies import get_current_identity
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.documents.service import UploadSubmissionError, submit_syllabus_upload
from apps.api.documents.validation import UploadValidationError, validate_pdf_upload
from apps.api.runtime import RuntimeResources

router = APIRouter(prefix="/api/v3/courses", tags=["curriculum"])


class SyllabusUploadAccepted(BaseModel):
    """202 response for a document accepted for asynchronous ingestion."""

    document_id: UUID
    job_id: UUID
    status: str = Field(default="accepted")


def _upload_error(error: UploadValidationError | UploadSubmissionError) -> HTTPException:
    """Create the upload API's consistent error envelope."""

    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post(
    "/{course_id}/syllabus",
    response_model=SyllabusUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_syllabus(
    course_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    upload: Annotated[UploadFile, File(description="A readable PDF syllabus")],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SyllabusUploadAccepted:
    """Validate, store, and enqueue a syllabus without running ingestion inline."""

    settings = request.app.state.settings
    resources: RuntimeResources = request.app.state.runtime
    try:
        validated = await validate_pdf_upload(upload, settings)
    except UploadValidationError as error:
        raise _upload_error(error) from None

    try:
        document_id, job_id = await submit_syllabus_upload(
            resources,
            course_id,
            identity.subject,
            idempotency_key,
            validated,
        )
    except UploadSubmissionError as error:
        raise _upload_error(error) from None
    finally:
        validated.close()

    return SyllabusUploadAccepted(document_id=document_id, job_id=job_id)
