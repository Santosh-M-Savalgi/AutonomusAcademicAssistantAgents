"""Versioned, validated v1 learning-event envelopes.

The legacy ``LearningEvent`` contract in ``packages.domain.models`` remains
available for Phase 2 compatibility. New transactional event persistence uses
the contracts in this module and never reinterprets legacy payloads.
"""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from packages.domain.enums import LearningEventType
from packages.domain.mastery import FrozenDomainModel, _utc
from packages.domain.models import DomainModel, VersionStamp

LEARNING_EVENT_SCHEMA_VERSION: Literal["learning-event-v1"] = "learning-event-v1"
LEARNING_PAYLOAD_SCHEMA_VERSION: Literal["learning-payload-v1"] = "learning-payload-v1"

_FORBIDDEN_PAYLOAD_KEY_PARTS = (
    "credential",
    "password",
    "secret",
    "token",
    "authorization",
    "private_key",
)


def _validate_payload_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).casefold()
            if any(part in key_text for part in _FORBIDDEN_PAYLOAD_KEY_PARTS):
                raise ValueError("Learning-event payload contains a restricted field")
            _validate_payload_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _validate_payload_keys(nested)


class LearningEventPayload(DomainModel):
    """Typed outer payload wrapper for event-specific JSON data."""

    schema_version: Literal["learning-payload-v1"] = LEARNING_PAYLOAD_SCHEMA_VERSION
    kind: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    data: dict[str, Any]

    @field_validator("data")
    @classmethod
    def reject_restricted_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_payload_keys(value)
        return value


class LearningEventInput(DomainModel):
    """Caller-supplied event data; recording time is assigned by persistence."""

    schema_version: Literal["learning-event-v1"] = LEARNING_EVENT_SCHEMA_VERSION
    event_id: UUID
    type: LearningEventType
    actor_id: UUID
    actor_subject: str = Field(min_length=1, max_length=255)
    learner_id: UUID | None = None
    course_id: UUID | None = None
    occurred_at: datetime
    payload: LearningEventPayload
    causation_id: UUID | None = None
    correlation_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    versions: VersionStamp | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurrence_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event occurrence time must be timezone-aware")
        return value.astimezone(UTC)


class LearningEventV1(LearningEventInput):
    """Persisted v1 envelope with separate occurrence and recording times."""

    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def require_aware_recording_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event recording time must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def preserve_event_identity(self) -> Self:
        if self.event_id == self.causation_id:
            raise ValueError("An event cannot causally reference itself")
        return self


LearningEventContract = LearningEventV1


class ConceptLearningEventInput(FrozenDomainModel):
    """Typed v2 envelope for persisted concept-affecting learning events."""

    schema_version: Literal["learning-event-v2"] = "learning-event-v2"
    event_id: UUID
    type: LearningEventType
    actor_id: UUID
    actor_subject: str
    learner_id: UUID
    course_id: UUID | None = None
    occurred_at: datetime
    payload: LearningEventPayload
    correlation_id: UUID
    causation_id: UUID | None = None
    idempotency_key: str
    stable_concept_ids: tuple[UUID, ...]
    concept_impact: Literal["AFFECTS_CONCEPT"] = "AFFECTS_CONCEPT"
    source_evidence_id: UUID | None = None
    source_attempt_id: UUID | None = None
    versions: VersionStamp | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurrence_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event occurrence time must be a datetime")
        return _utc(value)

    @model_validator(mode="after")
    def validate_concepts(self) -> Self:
        if not self.stable_concept_ids:
            raise ValueError("Concept-affecting events require stable concept IDs")
        if len(set(self.stable_concept_ids)) != len(self.stable_concept_ids):
            raise ValueError("Concept-affecting event concept IDs must be unique")
        if self.event_id == self.causation_id:
            raise ValueError("An event cannot causally reference itself")
        return self


ConceptLearningEventContract = ConceptLearningEventInput
