"""Authenticated draft submission/status/read endpoints, without generation in HTTP requests."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from apps.api.auth.dependencies import (
    get_current_identity,
    get_current_student_identity,
    identity_provider_namespace,
)
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.runtime import RuntimeResources
from packages.curriculum.config import DraftSettings
from packages.domain.curriculum import CurriculumDraft, DraftJobPayload
from packages.domain.enums import JobStatus
from packages.domain.identity import StudentIdentity
from packages.domain.models import DomainModel
from packages.domain.review import (
    CurriculumRevision,
    ReviewElement,
    ReviewErrorCode,
    ReviewRecord,
    ReviewStatus,
    review_identity,
)
from packages.domain.successor import CurriculumSuccessorRecord, CurriculumSuccessorRequest
from packages.persistence import find_course_member
from packages.persistence.drafts import draft_record, enqueue_draft, extraction_source, load_draft
from packages.persistence.extractions import SourceResolutionError
from packages.persistence.graphs import graph_build_job_identity
from packages.persistence.job_wakeups import notify_job_events
from packages.persistence.review import (
    ReviewServiceError,
    begin_review,
    confirm_review,
    get_review,
    list_revisions,
    save_revision,
)
from packages.persistence.successors import SuccessorVersionError, create_successor_version
from packages.persistence.worker_storage import bounded_storage, storage_call

router = APIRouter(prefix="/api/v3", tags=["curriculum"])


class GenerateDraftRequest(DomainModel):
    extraction_job_id: UUID


class DraftResponse(BaseModel):
    status: JobStatus
    job_id: UUID
    draft: CurriculumDraft | None = None
    error_code: str | None = None


class ReviewResponse(BaseModel):
    review: ReviewRecord
    revision: CurriculumRevision
    graph_job_id: UUID | None = None


class SaveRevisionRequest(DomainModel):
    expected_revision: int
    elements: list[ReviewElement]


class ConfirmRequest(DomainModel):
    expected_revision: int


class SuccessorResponse(BaseModel):
    successor: CurriculumSuccessorRecord


def _review_error(error: ReviewServiceError) -> HTTPException:
    status = 404 if error.code == ReviewErrorCode.REVIEW_NOT_FOUND else (
        403 if error.code == ReviewErrorCode.UNAUTHORIZED else (
            422 if error.code in {ReviewErrorCode.INVALID_REVISION,
                                  ReviewErrorCode.INVALID_PROVENANCE,
                                  ReviewErrorCode.CONFIRMATION_INVALID} else 409
        )
    )
    return HTTPException(
        status_code=status, detail={"code": error.code.value, "message": str(error)},
    )


async def _review_storage(request: Request):
    settings = request.app.state.settings
    return bounded_storage(settings.minio_endpoint, settings.minio_access_key,
                           settings.minio_secret_key.get_secret_value(),
                           settings.minio_bucket, settings.minio_secure)


async def require_membership(resources: RuntimeResources, course_id: UUID, subject: str) -> None:
    async with resources.database.session() as session:
        member = await find_course_member(session, course_id, subject)
    if member is None:
        raise HTTPException(status_code=403, detail={
            "code": "COURSE_DRAFT_FORBIDDEN", "message": "Course membership is required.",
        })


@router.post(
    "/courses/{course_id}/curriculum/drafts", status_code=202, response_model=DraftResponse,
)
async def generate_curriculum_draft(
    course_id: UUID, body: GenerateDraftRequest, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> DraftResponse:
    resources: RuntimeResources = request.app.state.runtime
    await require_membership(resources, course_id, identity.subject)
    try:
        identity_id = await enqueue_draft(resources.database, course_id, body.extraction_job_id)
    except SourceResolutionError as error:
        raise HTTPException(status_code=409, detail={
            "code": error.code.value, "message": "A valid completed extraction is required.",
        }) from None
    await notify_job_events(resources.redis, identity_id)
    job = await draft_record(resources.database, identity_id)
    assert job is not None
    return DraftResponse(status=JobStatus(job.status), job_id=job.id, error_code=job.error_code)


@router.get("/curriculum/{draft_id}/draft", response_model=DraftResponse)
async def read_curriculum_draft(
    draft_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> DraftResponse:
    resources: RuntimeResources = request.app.state.runtime
    job = await draft_record(resources.database, draft_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "DRAFT_NOT_FOUND",
                                                    "message": "No draft job exists."})
    payload = DraftJobPayload.model_validate(job.payload)
    await require_membership(resources, payload.course_id, identity.subject)
    draft = None
    if job.status == "SUCCEEDED":
        settings = request.app.state.settings
        storage = bounded_storage(settings.minio_endpoint, settings.minio_access_key,
                                  settings.minio_secret_key.get_secret_value(),
                                  settings.minio_bucket, settings.minio_secure)
        try:
            source, reference = await extraction_source(resources.database,
                                                        payload.extraction_job_id)
            if job.result_ref is None:
                raise ValueError("Missing draft result")
            draft = await storage_call(
                load_draft, storage, job.result_ref, job.id, payload.extraction_job_id,
                reference, source, DraftSettings().artifact_max_bytes,
            )
        except Exception:
            raise HTTPException(status_code=503, detail={
                "code": "DRAFT_UNAVAILABLE", "message": "The stored draft cannot be read safely.",
            }) from None
        finally:
            await storage.close()
    return DraftResponse(status=JobStatus(job.status), job_id=job.id, draft=draft,
                         error_code=job.error_code)


@router.post("/courses/{course_id}/curriculum/drafts/{draft_id}/review",
             status_code=200, response_model=ReviewResponse)
async def start_curriculum_review(
    course_id: UUID, draft_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> ReviewResponse:
    resources: RuntimeResources = request.app.state.runtime
    await require_membership(resources, course_id, identity.subject)
    draft_job = await draft_record(resources.database, draft_id)
    if draft_job is None:
        raise HTTPException(status_code=404, detail={
            "code": "DRAFT_NOT_FOUND", "message": "No curriculum draft exists.",
        })
    draft_payload = DraftJobPayload.model_validate(draft_job.payload)
    if draft_payload.course_id != course_id:
        raise HTTPException(status_code=403, detail={
            "code": "COURSE_DRAFT_FORBIDDEN", "message": "Draft belongs to another course.",
        })
    storage = await _review_storage(request)
    try:
        review, revision = await begin_review(
            resources.database, storage, draft_id, identity.subject,
        )
        if review.course_id != course_id:
            raise ReviewServiceError(
                ReviewErrorCode.UNAUTHORIZED, "Review belongs to another course",
            )
        return ReviewResponse(review=review, revision=revision)
    except ReviewServiceError as error:
        raise _review_error(error) from None
    finally:
        await storage.close()


async def _read_review_for_actor(
    request: Request, draft_id: UUID, identity: AuthenticatedIdentity,
) -> tuple[ReviewRecord, CurriculumRevision]:
    resources: RuntimeResources = request.app.state.runtime
    storage = await _review_storage(request)
    try:
        review, revision = await get_review(resources.database, storage, review_identity(draft_id))
    finally:
        await storage.close()
    await require_membership(resources, review.course_id, identity.subject)
    return review, revision


@router.get("/curriculum/{draft_id}/review", response_model=ReviewResponse)
async def read_curriculum_review(
    draft_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> ReviewResponse:
    try:
        review, revision = await _read_review_for_actor(request, draft_id, identity)
        return ReviewResponse(review=review, revision=revision)
    except ReviewServiceError as error:
        raise _review_error(error) from None


@router.put("/curriculum/{draft_id}/review/revisions", response_model=ReviewResponse)
async def save_curriculum_revision(
    draft_id: UUID, body: SaveRevisionRequest, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> ReviewResponse:
    resources: RuntimeResources = request.app.state.runtime
    try:
        review, _ = await _read_review_for_actor(request, draft_id, identity)
        if review.status != ReviewStatus.UNDER_REVIEW:
            raise ReviewServiceError(ReviewErrorCode.INVALID_TRANSITION, "Review is not editable")
        storage = await _review_storage(request)
        try:
            updated, revision = await save_revision(
                resources.database, storage, review.id, body.expected_revision,
                body.elements, identity.subject,
            )
        finally:
            await storage.close()
        return ReviewResponse(review=updated, revision=revision)
    except ReviewServiceError as error:
        raise _review_error(error) from None


@router.get("/curriculum/{draft_id}/review/revisions", response_model=list[CurriculumRevision])
async def list_curriculum_revisions(
    draft_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> list[CurriculumRevision]:
    resources: RuntimeResources = request.app.state.runtime
    try:
        review, _ = await _read_review_for_actor(request, draft_id, identity)
        storage = await _review_storage(request)
        try:
            return await list_revisions(resources.database, storage, review.id)
        finally:
            await storage.close()
    except ReviewServiceError as error:
        raise _review_error(error) from None


@router.post("/curriculum/{draft_id}/confirm", response_model=ReviewResponse)
async def confirm_curriculum(
    draft_id: UUID, body: ConfirmRequest, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> ReviewResponse:
    resources: RuntimeResources = request.app.state.runtime
    try:
        review, _ = await _read_review_for_actor(request, draft_id, identity)
        storage = await _review_storage(request)
        try:
            confirmed = await confirm_review(
                resources.database, storage, review.id, body.expected_revision, identity.subject,
                identity_provider_namespace(request.app.state.settings),
            )
            _, revision = await get_review(resources.database, storage, review.id)
        finally:
            await storage.close()
        graph_job_id = (
            None if confirmed.confirmed_revision_id is None
            else graph_build_job_identity(confirmed.id, confirmed.confirmed_revision_id)
        )
        if graph_job_id is not None:
            await notify_job_events(resources.redis, graph_job_id)
        return ReviewResponse(review=confirmed, revision=revision, graph_job_id=graph_job_id)
    except ReviewServiceError as error:
        raise _review_error(error) from None


@router.get("/curriculum/{draft_id}/confirmed", response_model=ReviewResponse)
async def read_confirmed_curriculum(
    draft_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> ReviewResponse:
    try:
        review, revision = await _read_review_for_actor(request, draft_id, identity)
        if review.status != ReviewStatus.CONFIRMED:
            raise ReviewServiceError(ReviewErrorCode.INVALID_TRANSITION,
                                     "Curriculum has not been confirmed")
        return ReviewResponse(review=review, revision=revision)
    except ReviewServiceError as error:
        raise _review_error(error) from None


@router.post(
    "/curriculum/{parent_draft_id}/successors",
    response_model=SuccessorResponse,
)
async def declare_curriculum_successor(
    parent_draft_id: UUID,
    body: CurriculumSuccessorRequest,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    student: Annotated[StudentIdentity, Depends(get_current_student_identity)],
) -> SuccessorResponse:
    """Declare an amendment lineage without mutating either review artifact."""

    try:
        parent_review, parent_revision = await _read_review_for_actor(
            request, parent_draft_id, identity,
        )
        resources: RuntimeResources = request.app.state.runtime
        storage = await _review_storage(request)
        try:
            successor_review, successor_revision = await get_review(
                resources.database, storage, review_identity(body.successor_draft_id),
            )
        finally:
            await storage.close()
        await require_membership(resources, successor_review.course_id, identity.subject)
        async with resources.database.session() as session, session.begin():
            successor = await create_successor_version(
                session,
                parent_review=parent_review,
                parent_revision=parent_revision,
                successor_review=successor_review,
                successor_revision=successor_revision,
                lineage=body.lineage,
                actor=student,
                actor_subject=identity.subject,
            )
        return SuccessorResponse(successor=successor)
    except SuccessorVersionError as error:
        raise HTTPException(status_code=409, detail={
            "code": "SUCCESSOR_VERSION_CONFLICT", "message": str(error),
        }) from error
    except ReviewServiceError as error:
        raise _review_error(error) from None
