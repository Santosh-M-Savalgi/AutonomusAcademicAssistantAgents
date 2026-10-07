"""Pure durable job event contract tests."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from packages.domain.jobs import (
    JobErrorCode,
    JobEventType,
    JobFailedPayload,
    JobRetryPayload,
    JobStagePayload,
)
from packages.persistence.job_events import validate_event_payload


def test_event_names_are_stable_and_versioned_payloads_are_serializable():
    payload = validate_event_payload(
        JobEventType.PROGRESS_UPDATED,
        JobStagePayload(stage="extracting", progress_percent=50, message="Reading source"),
    )
    assert JobEventType.PROGRESS_UPDATED.value == "job.progress_updated"
    assert payload == {
        "schema_version": "job-event-v1",
        "stage": "extracting",
        "progress_percent": 50,
        "message": "Reading source",
    }


def test_event_payload_type_and_bounds_are_enforced():
    with pytest.raises(ValidationError):
        validate_event_payload(
            JobEventType.STAGE_STARTED,
            {"schema_version": "job-event-v1", "stage": "bad stage", "progress_percent": 1},
        )
    with pytest.raises(ValidationError):
        validate_event_payload(
            JobEventType.FAILED,
            {"schema_version": "job-event-v1", "error_code": "private exception text"},
        )


def test_retry_and_failure_payloads_use_closed_error_codes():
    retry_at = datetime.now(UTC) + timedelta(seconds=2)
    assert validate_event_payload(
        JobEventType.RETRY_SCHEDULED,
        JobRetryPayload(error_code=JobErrorCode.LEASE_EXPIRED, retry_at=retry_at),
    )["error_code"] == JobErrorCode.LEASE_EXPIRED
    assert validate_event_payload(
        JobEventType.FAILED,
        JobFailedPayload(error_code=JobErrorCode.HANDLER_EXCEPTION),
    )["error_code"] == JobErrorCode.HANDLER_EXCEPTION
