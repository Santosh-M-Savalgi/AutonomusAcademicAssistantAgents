"""Caller-owned, idempotent persistence for v1 learning events."""

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload, LearningEventV1
from packages.domain.models import DomainModel, VersionStamp
from packages.persistence.models import LearningEventRecord, StudentIdentity


class LearningEventConflictError(ValueError):
    """An idempotency key was reused for a different logical event."""


class LegacyLearningEventError(ValueError):
    """A legacy Phase 2 row was requested as a v1 event without migration."""


def _logical_matches(row: LearningEventRecord, event: LearningEventInput) -> bool:
    return (
        row.event_id == event.event_id
        and row.event_type == event.type.value
        and row.actor_identity_id == event.actor_id
        and row.actor_subject == event.actor_subject
        and row.learner_identity_id == event.learner_id
        and row.course_id == event.course_id
        and row.occurred_at == event.occurred_at
        and row.payload == event.payload.model_dump(mode="json")
        and row.causation_id == event.causation_id
        and row.correlation_id == event.correlation_id
        and row.event_schema_version == event.schema_version
        and row.versions == (
            None if event.versions is None else event.versions.model_dump(mode="json")
        )
    )


def _assert_idempotent_match(row: LearningEventRecord, event: LearningEventInput) -> None:
    if not _logical_matches(row, event):
        raise LearningEventConflictError(
            "Learning-event idempotency key conflicts with an existing logical event"
        )


async def _recording_time(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if value is None:
        raise RuntimeError("Database did not return a recording timestamp")
    return cast(datetime, value)


async def insert_learning_event(
    session: AsyncSession,
    event: LearningEventInput,
) -> LearningEventRecord:
    """Insert or replay an event without committing the caller's transaction."""

    event = LearningEventInput.model_validate(event.model_dump())
    actor_identity = await session.scalar(
        select(StudentIdentity).where(
            StudentIdentity.id == event.actor_id,
            StudentIdentity.external_subject == event.actor_subject,
        )
    )
    if actor_identity is None:
        raise ValueError("Event actor identity does not match its authenticated subject")
    existing = await session.scalar(
        select(LearningEventRecord).where(
            LearningEventRecord.idempotency_key == event.idempotency_key,
        )
    )
    if existing is not None:
        _assert_idempotent_match(existing, event)
        return existing

    recorded_at = await _recording_time(session)
    row = LearningEventRecord(
        event_id=event.event_id,
        event_type=event.type.value,
        actor_subject=event.actor_subject,
        actor_identity_id=event.actor_id,
        learner_identity_id=event.learner_id,
        course_id=event.course_id,
        payload=event.payload.model_dump(mode="json"),
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
        created_at=recorded_at,
        event_schema_version=event.schema_version,
        occurred_at=event.occurred_at,
        recorded_at=recorded_at,
        idempotency_key=event.idempotency_key,
        versions=None if event.versions is None else event.versions.model_dump(mode="json"),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(LearningEventRecord).where(
                LearningEventRecord.idempotency_key == event.idempotency_key,
            )
        )
        if existing is None:
            event_id_match = await session.scalar(
                select(LearningEventRecord).where(
                    LearningEventRecord.event_id == event.event_id,
                )
            )
            if event_id_match is not None:
                raise LearningEventConflictError(
                    "Learning-event identifier conflicts with an existing event"
                ) from None
            raise
        _assert_idempotent_match(existing, event)
        return cast(LearningEventRecord, existing)
    return row


def event_from_record(row: LearningEventRecord) -> LearningEventV1:
    """Decode only v1 rows; legacy payloads remain explicitly legacy."""

    if row.event_schema_version != "learning-event-v1":
        raise LegacyLearningEventError(
            "Legacy learning events require a legacy-compatible reader"
        )
    if (
        row.actor_identity_id is None
        or row.recorded_at is None
        or row.occurred_at is None
        or row.idempotency_key is None
    ):
        raise ValueError("Incomplete v1 learning-event row")
    return LearningEventV1(
        event_id=row.event_id,
        type=LearningEventType(row.event_type),
        actor_id=row.actor_identity_id,
        actor_subject=row.actor_subject,
        learner_id=row.learner_identity_id,
        course_id=row.course_id,
        occurred_at=row.occurred_at,
        recorded_at=row.recorded_at,
        payload=LearningEventPayload.model_validate(row.payload),
        causation_id=row.causation_id,
        correlation_id=row.correlation_id,
        idempotency_key=row.idempotency_key,
        versions=(
            None if row.versions is None
            else VersionStamp.model_validate(row.versions)
        ),
    )


async def list_learning_events(
    session: AsyncSession,
    *,
    learner_id: UUID | None = None,
    course_id: UUID | None = None,
    event_types: Sequence[LearningEventType] | None = None,
) -> list[LearningEventRecord]:
    """Read events in deterministic occurrence/recording/UUID order."""

    query = select(LearningEventRecord)
    if learner_id is not None:
        query = query.where(LearningEventRecord.learner_identity_id == learner_id)
    if course_id is not None:
        query = query.where(LearningEventRecord.course_id == course_id)
    if event_types:
        query = query.where(
            LearningEventRecord.event_type.in_([event_type.value for event_type in event_types])
        )
    query = query.order_by(
        func.coalesce(LearningEventRecord.occurred_at, LearningEventRecord.recorded_at),
        LearningEventRecord.recorded_at,
        LearningEventRecord.event_id,
    )
    return list((await session.scalars(query)).all())


class LearningEventReadContract(DomainModel):
    """Small public read shape that does not expose raw legacy reinterpretation."""

    event_id: UUID
    event_type: LearningEventType
    learner_id: UUID | None
    course_id: UUID | None
    occurred_at: datetime | None
    recorded_at: datetime
