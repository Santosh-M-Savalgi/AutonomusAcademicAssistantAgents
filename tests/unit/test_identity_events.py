"""Pure identity, authorization and v1 learning-event contract tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from apps.api.auth.dependencies import identity_provider_namespace
from apps.api.config import Settings
from packages.domain.enums import LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload, LearningEventV1
from packages.domain.identity import (
    LearnerAuthorizationError,
    require_learner_access,
)
from packages.persistence.identities import stable_identity_id


def event_input(*, event_id=None, idempotency_key="event-1") -> LearningEventInput:
    actor_id = uuid4()
    return LearningEventInput(
        event_id=event_id or uuid4(),
        type=LearningEventType.ANSWER_GRADED,
        actor_id=actor_id,
        actor_subject="opaque-subject",
        learner_id=actor_id,
        course_id=uuid4(),
        occurred_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
        payload=LearningEventPayload(
            kind="answer_graded",
            data={"evidence_id": str(uuid4()), "correct": 1.0},
        ),
        correlation_id=uuid4(),
        idempotency_key=idempotency_key,
    )


def test_subject_mapping_does_not_parse_or_require_uuid_subjects() -> None:
    first = stable_identity_id("jwt:issuer:audience", "student@example.invalid")
    second = stable_identity_id("jwt:issuer:audience", "student@example.invalid")
    other = stable_identity_id("jwt:issuer:audience", "another-subject")
    assert first == second
    assert first != other


@given(st.text(min_size=1, max_size=80))
def test_subject_mapping_is_stable_for_arbitrary_opaque_subjects(subject: str) -> None:
    assert stable_identity_id("jwt:test", subject) == stable_identity_id("jwt:test", subject)


def test_provider_namespace_is_derived_from_configured_jwt_context(test_settings: Settings) -> None:
    assert identity_provider_namespace(test_settings) == "jwt:aaa-v3:aaa-v3-api"


def test_cross_learner_access_requires_explicit_authorization() -> None:
    actor_id, learner_id = uuid4(), uuid4()
    with pytest.raises(LearnerAuthorizationError):
        require_learner_access(actor_id, learner_id)
    require_learner_access(actor_id, learner_id, explicitly_authorized=True)
    require_learner_access(actor_id, actor_id)


def test_event_contract_separates_occurrence_and_recording_time() -> None:
    occurred = datetime(2026, 1, 1, 12, tzinfo=UTC)
    recorded = occurred + timedelta(seconds=3)
    event = LearningEventV1(**event_input().model_dump(), recorded_at=recorded)
    assert event.occurred_at == occurred
    assert event.recorded_at == recorded
    assert event.actor_id == event.learner_id


def test_event_contract_rejects_naive_time_and_restricted_payload_fields() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        LearningEventInput(**(event_input().model_dump() | {
            "occurred_at": datetime(2026, 1, 1, 12),
        }))
    with pytest.raises(ValidationError, match="restricted"):
        LearningEventPayload(kind="unsafe", data={"access_token": "secret"})


def test_event_contract_rejects_self_causation() -> None:
    event_id = uuid4()
    data = event_input(event_id=event_id).model_dump()
    data["causation_id"] = event_id
    with pytest.raises(ValidationError, match="causally"):
        LearningEventV1(
            **data,
            recorded_at=datetime.now(UTC),
        )
