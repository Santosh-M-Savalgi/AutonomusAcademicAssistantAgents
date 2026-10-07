"""Explicit links between immutable curriculum revisions."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload
from packages.domain.identity import StudentIdentity
from packages.domain.review import CurriculumRevision, ReviewRecord, ReviewStatus
from packages.domain.successor import CurriculumSuccessorRecord, SuccessorLineage
from packages.persistence.learning_events import insert_learning_event
from packages.persistence.models import CurriculumReview, CurriculumSuccessorVersion


class SuccessorVersionError(ValueError):
    """Invalid parent/successor relationship or lineage."""


def successor_identity(
    parent_revision_id: UUID, successor_review_id: UUID, successor_revision_id: UUID,
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "aaa-v3:curriculum-successor:v2:"
        f"{parent_revision_id}:{successor_review_id}:{successor_revision_id}",
    )


def _element_ids(revision: CurriculumRevision) -> set[UUID]:
    return {element.id for element in revision.elements}


async def create_successor_version(
    session: AsyncSession,
    *,
    parent_review: ReviewRecord,
    parent_revision: CurriculumRevision,
    successor_review: ReviewRecord,
    successor_revision: CurriculumRevision,
    lineage: list[SuccessorLineage],
    actor: StudentIdentity,
    actor_subject: str,
) -> CurriculumSuccessorRecord:
    if parent_review.status != ReviewStatus.CONFIRMED:
        raise SuccessorVersionError("Parent curriculum must be confirmed")
    if parent_review.confirmed_revision_id != parent_revision.id:
        raise SuccessorVersionError("Parent review does not reference the supplied revision")
    if successor_review.id == parent_review.id:
        raise SuccessorVersionError("A curriculum cannot be its own successor")
    if parent_review.course_id != successor_review.course_id:
        raise SuccessorVersionError("Parent and successor must belong to one course")
    if successor_review.current_revision_id != successor_revision.id:
        raise SuccessorVersionError("Successor revision is not current")
    parent_row = await session.get(CurriculumReview, parent_review.id, with_for_update=True)
    successor_row = await session.get(CurriculumReview, successor_review.id, with_for_update=True)
    if (
        parent_row is None
        or parent_row.status != ReviewStatus.CONFIRMED.value
        or parent_row.confirmed_revision_id != parent_revision.id
        or successor_row is None
        or successor_row.current_revision_id != successor_revision.id
    ):
        raise SuccessorVersionError("Successor lineage references a stale review revision")
    parent_ids = _element_ids(parent_revision)
    successor_ids = _element_ids(successor_revision)
    for item in lineage:
        if not set(item.parent_element_ids) <= parent_ids:
            raise SuccessorVersionError("Lineage references an unknown parent element")
        if not set(item.successor_element_ids) <= successor_ids:
            raise SuccessorVersionError("Lineage references an unknown successor element")
    record_id = successor_identity(
        parent_revision.id, successor_review.id, successor_revision.id,
    )
    existing = await session.get(CurriculumSuccessorVersion, record_id)
    if existing is not None:
        if existing.lineage != [item.model_dump(mode="json") for item in lineage]:
            raise SuccessorVersionError("Successor idempotency key conflicts with lineage")
        return CurriculumSuccessorRecord(
            id=existing.id, course_id=existing.course_id,
            parent_review_id=existing.parent_review_id,
            parent_revision_id=existing.parent_revision_id,
            successor_review_id=existing.successor_review_id,
            successor_revision_id=existing.successor_revision_id,
            status=existing.status, created_by_identity_id=existing.created_by_identity_id,
            lineage=[SuccessorLineage.model_validate(item) for item in existing.lineage],
        )
    successor_status = (
        "CONFIRMED"
        if successor_review.status == ReviewStatus.CONFIRMED
        and successor_review.confirmed_revision_id == successor_revision.id
        else "DECLARED"
    )
    row = CurriculumSuccessorVersion(
        id=record_id,
        course_id=parent_review.course_id,
        parent_review_id=parent_review.id,
        parent_revision_id=parent_revision.id,
        successor_review_id=successor_review.id,
        successor_revision_id=successor_revision.id,
        status=successor_status,
        created_by_identity_id=actor.id,
        lineage=[item.model_dump(mode="json") for item in lineage],
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await insert_learning_event(session, LearningEventInput(
        event_id=uuid5(record_id, "learning-event:successor-created"),
        type=LearningEventType.CURRICULUM_SUCCESSOR_CREATED,
        actor_id=actor.id,
        actor_subject=actor_subject,
        course_id=parent_review.course_id,
        occurred_at=row.created_at,
        payload=LearningEventPayload(
            kind="curriculum_successor_created",
            data={"successor_id": str(record_id), "parent_revision_id": str(parent_revision.id),
                  "successor_review_id": str(successor_review.id)},
        ), correlation_id=record_id,
        idempotency_key=f"curriculum-successor:{record_id}",
    ))
    return CurriculumSuccessorRecord(
        id=row.id, course_id=row.course_id, parent_review_id=row.parent_review_id,
        parent_revision_id=row.parent_revision_id, successor_review_id=row.successor_review_id,
        successor_revision_id=row.successor_revision_id, status=row.status,
        created_by_identity_id=row.created_by_identity_id,
        lineage=[SuccessorLineage.model_validate(item) for item in row.lineage],
    )


async def get_successor(
    session: AsyncSession, successor_id: UUID, course_id: UUID,
) -> CurriculumSuccessorRecord | None:
    row = await session.scalar(select(CurriculumSuccessorVersion).where(
        CurriculumSuccessorVersion.id == successor_id,
        CurriculumSuccessorVersion.course_id == course_id,
    ))
    if row is None:
        return None
    return CurriculumSuccessorRecord(
        id=row.id, course_id=row.course_id, parent_review_id=row.parent_review_id,
        parent_revision_id=row.parent_revision_id, successor_review_id=row.successor_review_id,
        successor_revision_id=row.successor_revision_id, status=row.status,
        created_by_identity_id=row.created_by_identity_id,
        lineage=[SuccessorLineage.model_validate(item) for item in row.lineage],
    )
