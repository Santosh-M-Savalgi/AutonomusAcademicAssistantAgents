"""Unit tests for the durable job contract."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain import JobContract, JobLane, JobStatus, JobType


def make_job(**overrides: object) -> JobContract:
    values: dict[str, object] = {
        "id": uuid4(),
        "type": JobType.SYLLABUS_INGESTION,
        "payload": {"document_id": str(uuid4())},
        "run_after": datetime.now(UTC),
        "idempotency_key": "upload-key",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return JobContract.model_validate(values)


@pytest.mark.parametrize("status", list(JobStatus))
def test_job_contract_accepts_every_lifecycle_status(status: JobStatus) -> None:
    assert make_job(status=status).status is status


def test_job_contract_preserves_lane_and_retry_fields() -> None:
    job = make_job(lane=JobLane.INTERACTIVE, attempts=2, max_attempts=5, priority=10)

    assert job.lane is JobLane.INTERACTIVE
    assert job.attempts == 2
    assert job.max_attempts == 5
    assert job.priority == 10


def test_job_contract_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        make_job(status="BROKEN")
