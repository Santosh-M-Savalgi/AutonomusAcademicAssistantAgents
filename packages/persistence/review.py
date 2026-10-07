"""Transactional review/revision service with immutable MinIO artifacts and OCC."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.domain.curriculum import CurriculumDraft
from packages.domain.enums import JobLane, JobType, LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload
from packages.domain.graph import GraphBuildJobPayload
from packages.domain.review import (
    CurriculumRevision,
    ReviewElement,
    ReviewErrorCode,
    ReviewRecord,
    ReviewStatus,
    review_identity,
    validate_confirmable,
    validate_review_transition,
    validate_revision_against_draft,
)
from packages.persistence.artifacts import persist_json
from packages.persistence.database import Database
from packages.persistence.drafts import draft_record, extraction_source, load_draft
from packages.persistence.graphs import graph_build_job_identity
from packages.persistence.identities import resolve_student_identity
from packages.persistence.job_creation import create_job_in_transaction
from packages.persistence.learning_events import insert_learning_event
from packages.persistence.models import CurriculumReview, CurriculumSuccessorVersion, Job
from packages.persistence.models import CurriculumRevision as RevisionRow
from packages.persistence.object_storage import ObjectStorage
from packages.persistence.worker_storage import storage_call


class ReviewServiceError(ValueError):
    def __init__(self, code: ReviewErrorCode, message: str):
        self.code = code
        super().__init__(message)


DEFAULT_IDENTITY_NAMESPACE = "jwt:aaa-v3:aaa-v3-api"


def _review_record(row: CurriculumReview) -> ReviewRecord:
    return ReviewRecord(
        id=row.id, course_id=row.course_id, document_id=row.document_id,
        document_version_id=row.document_version_id, draft_id=row.draft_job_id,
        original_draft_ref=row.original_draft_ref, status=ReviewStatus(row.status),
        current_revision_id=row.current_revision_id, revision_number=row.revision_number,
        confirmed_revision_id=row.confirmed_revision_id, created_by=row.created_by,
        updated_by=row.updated_by, confirmed_by=row.confirmed_by,
    )


def _review_elements(draft: CurriculumDraft) -> list[ReviewElement]:
    return [ReviewElement.model_validate(element.model_dump()) for element in draft.elements]


def _revision_key(review_id: UUID, revision_id: UUID, content: bytes) -> str:
    digest = sha256(content).hexdigest()
    return (f"courses/reviews/{review_id}/revisions/{revision_id}/"
            f"curriculum-review-v1/{digest}.json")


def _revision_domain(row: RevisionRow, content: bytes) -> CurriculumRevision:
    return CurriculumRevision.model_validate_json(content)


async def _original_draft(
    database: Database, storage: ObjectStorage, review: CurriculumReview,
) -> tuple[CurriculumDraft, str]:
    async with database.session() as session:
        draft_job = await session.get(Job, review.draft_job_id)
        if draft_job is None or draft_job.result_ref is None:
            raise ReviewServiceError(
                ReviewErrorCode.REVIEW_NOT_FOUND, "Original draft is unavailable",
            )
        payload = dict(draft_job.payload)
    extraction_id = UUID(str(payload["extraction_job_id"]))
    source, extraction_ref = await extraction_source(database, extraction_id)
    return await storage_call(
        load_draft, storage, draft_job.result_ref, draft_job.id, extraction_id,
        extraction_ref, source, 4 * 1024 * 1024,
    ), draft_job.result_ref


async def _load_revision(
    database: Database, storage: ObjectStorage, row: RevisionRow,
) -> CurriculumRevision:
    content = await storage_call(
        storage.read_artifact, row.artifact_ref.removeprefix(f"minio://{storage.bucket}/"),
        max_bytes=4 * 1024 * 1024, sha256=row.artifact_sha256,
    )
    revision = _revision_domain(row, content)
    if revision.id != row.id or revision.review_id != row.review_id:
        raise ReviewServiceError(ReviewErrorCode.INVALID_REVISION, "Revision metadata mismatch")
    return revision


async def begin_review(
    database: Database, storage: ObjectStorage, draft_id: UUID, actor: str,
) -> tuple[ReviewRecord, CurriculumRevision]:
    draft_job = await draft_record(database, draft_id)
    if draft_job is None or draft_job.result_ref is None or draft_job.status != "SUCCEEDED":
        raise ReviewServiceError(ReviewErrorCode.REVIEW_NOT_FOUND, "A completed draft is required")
    async with database.session() as session:
        existing = (await session.scalars(select(CurriculumReview).where(
            CurriculumReview.draft_job_id == draft_id,
        ))).one_or_none()
    if existing is not None:
        async with database.session() as session:
            revision_row = await session.get(RevisionRow, existing.current_revision_id)
        if revision_row is None:
            raise ReviewServiceError(
                ReviewErrorCode.INVALID_REVISION, "Current revision is missing",
            )
        return _review_record(existing), await _load_revision(database, storage, revision_row)
    # Resolve and validate the original generated artifact before making review state.
    async with database.session() as session:
        review_source = dict(draft_job.payload)
    extraction_id = UUID(str(review_source["extraction_job_id"]))
    source, extraction_ref = await extraction_source(database, extraction_id)
    draft = await storage_call(
        load_draft, storage, draft_job.result_ref, draft_job.id, extraction_id,
        extraction_ref, source, 4 * 1024 * 1024,
    )
    review_id = review_identity(draft_id)
    revision_id = uuid5(review_id, "revision:1")
    revision = CurriculumRevision(
        id=revision_id, review_id=review_id, draft_id=draft_id, revision_number=1,
        parent_revision_id=None, source=draft.source, original_draft_ref=draft_job.result_ref,
        elements=_review_elements(draft), created_by=actor,
    )
    content = revision.canonical_bytes()
    reference = f"minio://{storage.bucket}/{_revision_key(review_id, revision_id, content)}"
    await storage_call(persist_json, storage, _revision_key(review_id, revision_id, content),
                       content, 4 * 1024 * 1024)
    try:
        async with database.session() as session, session.begin():
            existing = (await session.scalars(select(CurriculumReview).where(
                CurriculumReview.draft_job_id == draft_id,
            ).with_for_update())).one_or_none()
            if existing is not None:
                revision_row = await session.get(RevisionRow, existing.current_revision_id)
                if revision_row is None:
                    raise ReviewServiceError(
                        ReviewErrorCode.INVALID_REVISION, "Current revision missing",
                    )
                return _review_record(existing), await _load_revision(
                    database, storage, revision_row,
                )
            review_row = CurriculumReview(
                id=review_id, course_id=source.course_id, document_id=source.document_id,
                document_version_id=source.version_id, draft_job_id=draft_id,
                original_draft_ref=draft_job.result_ref, status=ReviewStatus.UNDER_REVIEW,
                current_revision_id=revision_id, revision_number=1, created_by=actor,
                updated_by=actor,
            )
            session.add(review_row)
            session.add(RevisionRow(
                id=revision_id, review_id=review_id, parent_revision_id=None,
                revision_number=1, artifact_ref=reference,
                artifact_sha256=sha256(content).hexdigest(), content_bytes=len(content),
                idempotency_key=f"review:{review_id}:revision:1", created_by=actor,
            ))
            await session.flush()
            return _review_record(review_row), revision
    except IntegrityError:
        # A concurrent creator may commit between the initial lookup and flush.
        async with database.session() as session:
            existing = (await session.scalars(select(CurriculumReview).where(
                CurriculumReview.draft_job_id == draft_id,
            ))).one_or_none()
            if existing is None:
                raise
            revision_row = await session.get(RevisionRow, existing.current_revision_id)
        if revision_row is None:
            raise ReviewServiceError(
                ReviewErrorCode.INVALID_REVISION, "Current revision missing",
            ) from None
        return _review_record(existing), await _load_revision(database, storage, revision_row)


async def get_review(
    database: Database, storage: ObjectStorage, review_id: UUID,
) -> tuple[ReviewRecord, CurriculumRevision]:
    async with database.session() as session:
        review = await session.get(CurriculumReview, review_id)
        if review is None:
            raise ReviewServiceError(ReviewErrorCode.REVIEW_NOT_FOUND, "Review not found")
        revision = await session.get(RevisionRow, review.current_revision_id)
    if revision is None:
        raise ReviewServiceError(ReviewErrorCode.INVALID_REVISION, "Current revision is missing")
    return _review_record(review), await _load_revision(database, storage, revision)


async def list_revisions(
    database: Database, storage: ObjectStorage, review_id: UUID,
) -> list[CurriculumRevision]:
    async with database.session() as session:
        rows = (await session.scalars(select(RevisionRow).where(
            RevisionRow.review_id == review_id,
        ).order_by(RevisionRow.revision_number))).all()
    return [await _load_revision(database, storage, row) for row in rows]


async def save_revision(
    database: Database, storage: ObjectStorage, review_id: UUID, expected_revision: int,
    elements: list[ReviewElement], actor: str,
) -> tuple[ReviewRecord, CurriculumRevision]:
    async with database.session() as session:
        review = await session.get(CurriculumReview, review_id)
        if review is None:
            raise ReviewServiceError(ReviewErrorCode.REVIEW_NOT_FOUND, "Review not found")
        current_row = await session.get(RevisionRow, review.current_revision_id)
    if review.status == ReviewStatus.CONFIRMED:
        raise ReviewServiceError(
            ReviewErrorCode.CONFIRMED_IMMUTABLE, "Confirmed curriculum is immutable",
        )
    if review.status != ReviewStatus.UNDER_REVIEW:
        raise ReviewServiceError(ReviewErrorCode.INVALID_TRANSITION, "Review has not begun")
    element_digest = sha256(json.dumps(
        [element.model_dump(mode="json") for element in elements],
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    idempotency = (
        f"review:{review_id}:expected:{expected_revision}:actor:{actor}:sha:{element_digest}"
    )
    async with database.session() as session:
        existing = (await session.scalars(select(RevisionRow).where(
            RevisionRow.idempotency_key == idempotency,
        ))).one_or_none()
    if existing is not None:
        return _review_record(review), await _load_revision(database, storage, existing)
    if review.revision_number != expected_revision or current_row is None:
        raise ReviewServiceError(ReviewErrorCode.STALE_REVISION, "Revision is stale")
    current = await _load_revision(database, storage, current_row)
    original, _ = await _original_draft(database, storage, review)
    try:
        seed = CurriculumRevision(
            id=UUID(int=0), review_id=review_id, draft_id=review.draft_job_id,
            revision_number=expected_revision + 1, parent_revision_id=current.id,
            source=current.source, original_draft_ref=review.original_draft_ref,
            elements=elements, created_by=actor,
        )
        revision_id = uuid5(review_id, f"revision:{expected_revision + 1}:{sha256(
            seed.canonical_bytes()
        ).hexdigest()}")
        candidate = seed.model_copy(update={"id": revision_id})
        validate_revision_against_draft(candidate, original)
    except (ValueError, ValidationError) as error:
        raise ReviewServiceError(ReviewErrorCode.INVALID_REVISION, str(error)) from error
    content = candidate.canonical_bytes()
    key = _revision_key(review_id, revision_id, content)
    reference = await storage_call(persist_json, storage, key, content, 4 * 1024 * 1024)
    async with database.session() as session, session.begin():
        locked = (await session.scalars(select(CurriculumReview).where(
            CurriculumReview.id == review_id,
        ).with_for_update())).one()
        if locked.status == ReviewStatus.CONFIRMED:
            raise ReviewServiceError(
                ReviewErrorCode.CONFIRMED_IMMUTABLE, "Confirmed curriculum is immutable",
            )
        existing = (await session.scalars(select(RevisionRow).where(
            RevisionRow.idempotency_key == idempotency,
        ))).one_or_none()
        if existing is not None:
            return _review_record(locked), candidate
        if locked.current_revision_id != current.id or locked.revision_number != expected_revision:
            raise ReviewServiceError(ReviewErrorCode.STALE_REVISION, "Revision changed during save")
        session.add(RevisionRow(
            id=revision_id, review_id=review_id, parent_revision_id=current.id,
            revision_number=expected_revision + 1, artifact_ref=reference,
            artifact_sha256=sha256(content).hexdigest(), content_bytes=len(content),
            idempotency_key=idempotency, created_by=actor,
        ))
        locked.current_revision_id = revision_id
        locked.revision_number = expected_revision + 1
        locked.updated_by = actor
        locked.updated_at = datetime.now(UTC)
        await session.flush()
        return _review_record(locked), candidate


async def confirm_review(
    database: Database, storage: ObjectStorage, review_id: UUID,
    expected_revision: int, actor: str,
    actor_namespace: str = DEFAULT_IDENTITY_NAMESPACE,
) -> ReviewRecord:
    async with database.session() as session, session.begin():
        review = (await session.scalars(select(CurriculumReview).where(
            CurriculumReview.id == review_id,
        ).with_for_update())).one_or_none()
        if review is None:
            raise ReviewServiceError(ReviewErrorCode.REVIEW_NOT_FOUND, "Review not found")
        if review.status == ReviewStatus.CONFIRMED and review.revision_number != expected_revision:
            raise ReviewServiceError(
                ReviewErrorCode.STALE_REVISION, "A different revision is confirmed",
            )
        if review.status not in {ReviewStatus.UNDER_REVIEW, ReviewStatus.CONFIRMED}:
            raise ReviewServiceError(ReviewErrorCode.INVALID_TRANSITION, "Review has not begun")
        if review.revision_number != expected_revision:
            raise ReviewServiceError(ReviewErrorCode.STALE_REVISION, "Revision is stale")
        revision_row = await session.get(RevisionRow, review.current_revision_id)
        if revision_row is None:
            raise ReviewServiceError(
                ReviewErrorCode.INVALID_REVISION, "Current revision is missing",
            )
    revision = await _load_revision(database, storage, revision_row)
    try:
        validate_confirmable(revision)
    except ValueError as error:
        raise ReviewServiceError(ReviewErrorCode.CONFIRMATION_INVALID, str(error)) from error
    validate_review_transition(ReviewStatus.UNDER_REVIEW, ReviewStatus.CONFIRMED)
    async with database.session() as session, session.begin():
        review = (await session.scalars(select(CurriculumReview).where(
            CurriculumReview.id == review_id,
        ).with_for_update())).one()
        already_confirmed = review.status == ReviewStatus.CONFIRMED
        if (
            (not already_confirmed and review.status != ReviewStatus.UNDER_REVIEW)
            or review.revision_number != expected_revision
        ):
            raise ReviewServiceError(
                ReviewErrorCode.STALE_REVISION, "Review changed during confirmation",
            )
        if not already_confirmed:
            review.status = ReviewStatus.CONFIRMED
            review.confirmed_revision_id = review.current_revision_id
            review.confirmed_by = actor
            review.confirmed_at = datetime.now(UTC)
            review.updated_by = actor
            review.updated_at = datetime.now(UTC)
        revision_row = await session.get(RevisionRow, review.current_revision_id)
        if revision_row is None:
            raise ReviewServiceError(
                ReviewErrorCode.INVALID_REVISION, "Current revision is missing",
            )
        confirmation_actor = review.confirmed_by or actor
        actor_identity = await resolve_student_identity(
            session, actor_namespace, confirmation_actor,
        )
        job_id = graph_build_job_identity(review.id, revision_row.id)
        graph_payload = GraphBuildJobPayload(
            course_id=review.course_id,
            review_id=review.id,
            curriculum_revision_id=revision_row.id,
            revision_artifact_ref=revision_row.artifact_ref,
            revision_artifact_sha256=revision_row.artifact_sha256,
            actor_identity_id=actor_identity.id,
            actor_subject=confirmation_actor,
        )
        job = await create_job_in_transaction(
            session,
            job_id=job_id,
            job_type=JobType.GRAPH_BUILD.value,
            payload=graph_payload.model_dump(mode="json"),
            idempotency_key=f"graph-build:{review.id}:{revision_row.id}",
            lane=JobLane.BATCH,
        )
        now = datetime.now(UTC)
        await insert_learning_event(session, LearningEventInput(
            event_id=uuid5(review.id, f"curriculum-confirmed:{revision_row.id}"),
            type=LearningEventType.CURRICULUM_CONFIRMED,
            actor_id=actor_identity.id,
            actor_subject=confirmation_actor,
            course_id=review.course_id,
            occurred_at=review.confirmed_at or now,
            payload=LearningEventPayload(
                kind="curriculum_confirmed",
                data={
                    "review_id": str(review.id),
                    "curriculum_revision_id": str(revision_row.id),
                    "graph_job_id": str(job.id),
                },
            ),
            correlation_id=job.id,
            idempotency_key=f"curriculum-confirmed:{review.id}:{revision_row.id}",
        ))
        declared_successors = (await session.scalars(select(
            CurriculumSuccessorVersion,
        ).where(
            CurriculumSuccessorVersion.successor_review_id == review.id,
            CurriculumSuccessorVersion.successor_revision_id == revision_row.id,
            CurriculumSuccessorVersion.status == "DECLARED",
        ).with_for_update())).all()
        for successor in declared_successors:
            successor.status = "CONFIRMED"
        return _review_record(review)
