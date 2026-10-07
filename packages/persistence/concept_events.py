"""Caller-owned persistence for typed concept-affecting learning events."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.enums import LearningEventType
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.persistence.models import (
    LearningEventConceptAssociation,
    LearningEventRecord,
    StudentIdentity,
)


class ConceptLearningEventConflictError(ValueError):
    """An idempotency key was reused for different concept-event content."""


def concept_event_from_record(
    row: LearningEventRecord,
    stable_concept_ids: Sequence[UUID],
) -> ConceptLearningEventInput:
    """Decode only a v2 row with its normalized concept associations."""

    if row.event_schema_version != "learning-event-v2":
        raise ValueError("Learning-event row is not a concept-impact v2 event")
    if (
        row.actor_identity_id is None
        or row.learner_identity_id is None
        or row.occurred_at is None
    ):
        raise ValueError("Incomplete concept-impact event row")
    payload = row.payload
    return ConceptLearningEventInput(
        event_id=row.event_id,
        type=LearningEventType(row.event_type),
        actor_id=row.actor_identity_id,
        actor_subject=row.actor_subject,
        learner_id=row.learner_identity_id,
        course_id=row.course_id,
        occurred_at=row.occurred_at,
        payload=LearningEventPayload(
            schema_version="learning-payload-v1",
            kind=str(payload["kind"]),
            data=cast(dict[str, object], payload["data"]),
        ),
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        idempotency_key=row.idempotency_key or str(row.event_id),
        stable_concept_ids=tuple(stable_concept_ids),
        source_evidence_id=(
            None if not payload.get("source_evidence_id")
            else UUID(str(payload["source_evidence_id"]))
        ),
        source_attempt_id=(
            None if not payload.get("source_attempt_id")
            else UUID(str(payload["source_attempt_id"]))
        ),
    )


async def _db_clock(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if value is None:
        raise RuntimeError("Database did not return a timestamp")
    return cast(datetime, value).astimezone(UTC)


def _payload(event: ConceptLearningEventInput) -> dict[str, object]:
    return {
        "schema_version": event.payload.schema_version,
        "kind": event.payload.kind,
        "data": event.payload.data,
        "concept_impact": event.concept_impact,
        "stable_concept_ids": [str(value) for value in event.stable_concept_ids],
        "source_evidence_id": (
            None if event.source_evidence_id is None else str(event.source_evidence_id)
        ),
        "source_attempt_id": (
            None if event.source_attempt_id is None else str(event.source_attempt_id)
        ),
    }


async def insert_concept_learning_event(
    session: AsyncSession,
    event: ConceptLearningEventInput,
    *,
    validation_db_at: datetime | None = None,
) -> LearningEventRecord:
    """Insert or replay a v2 event without committing the caller transaction."""

    validation_time = validation_db_at or await _db_clock(session)
    if event.occurred_at > validation_time:
        raise ValueError("Concept-affecting event cannot occur in the future")
    actor = await session.scalar(
        select(StudentIdentity).where(
            StudentIdentity.id == event.actor_id,
            StudentIdentity.external_subject == event.actor_subject,
        )
    )
    if actor is None:
        raise ValueError("Event actor identity does not match its authenticated subject")

    existing = await session.scalar(
        select(LearningEventRecord).where(
            LearningEventRecord.idempotency_key == event.idempotency_key,
        )
    )
    payload = _payload(event)
    if existing is not None:
        logical_match = (
            existing.event_id == event.event_id
            and existing.event_type == event.type.value
            and existing.actor_identity_id == event.actor_id
            and existing.actor_subject == event.actor_subject
            and existing.learner_identity_id == event.learner_id
            and existing.course_id == event.course_id
            and existing.occurred_at == event.occurred_at
            and existing.payload == payload
            and existing.event_schema_version == event.schema_version
        )
        if not logical_match:
            raise ConceptLearningEventConflictError(
                "Concept learning-event idempotency key conflicts with existing content"
            )
        return existing

    recorded_at = await _db_clock(session)
    row = LearningEventRecord(
        event_id=event.event_id,
        event_type=event.type.value,
        actor_subject=event.actor_subject,
        actor_identity_id=event.actor_id,
        learner_identity_id=event.learner_id,
        course_id=event.course_id,
        payload=payload,
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
        created_at=recorded_at,
        event_schema_version=event.schema_version,
        occurred_at=event.occurred_at,
        recorded_at=recorded_at,
        idempotency_key=event.idempotency_key,
        versions=None if event.versions is None else event.versions.model_dump(mode="json"),
    )
    session.add(row)
    await session.flush()
    session.add_all([
        LearningEventConceptAssociation(
            event_id=event.event_id,
            stable_concept_id=concept_id,
            learner_identity_id=event.learner_id,
            course_id=event.course_id,
            occurred_at=event.occurred_at,
            concept_impact=event.concept_impact,
            source_evidence_id=event.source_evidence_id,
            source_attempt_id=event.source_attempt_id,
        )
        for concept_id in event.stable_concept_ids
    ])
    await session.flush()
    return row
