"""Unit tests for upload transaction failure behavior."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.api.documents.service import UploadSubmissionError, submit_syllabus_upload
from apps.api.documents.validation import ValidatedPDF
from packages.persistence import Course


class FakeSessionContext:
    def __init__(self) -> None:
        self.session = SimpleNamespace(
            add_all=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock()
        )

    async def __aenter__(self) -> SimpleNamespace:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class FailingStorage:
    ensure_bucket = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    put_object = AsyncMock()


async def test_storage_failure_does_not_create_database_records(monkeypatch) -> None:
    import apps.api.documents.service as service

    database_session = FakeSessionContext()
    database = SimpleNamespace(session=lambda: database_session)
    resources = SimpleNamespace(database=database, object_storage=FailingStorage())
    course_id = uuid4()

    monkeypatch.setattr(
        service,
        "find_course",
        AsyncMock(return_value=Course(id=course_id, title="Course")),
    )
    monkeypatch.setattr(service, "find_course_member", AsyncMock(return_value=object()))
    monkeypatch.setattr(service, "find_job_by_idempotency_key", AsyncMock(return_value=None))

    validated = ValidatedPDF(
        file=BytesIO(b"pdf"),
        original_filename="syllabus.pdf",
        size_bytes=3,
        sha256="a" * 64,
        page_count=1,
    )
    with pytest.raises(UploadSubmissionError) as error:
        await submit_syllabus_upload(resources, course_id, "student", "key", validated)

    assert error.value.code == "UPLOAD_UNAVAILABLE"
    assert database_session.session.add_all.await_count == 0
    assert database_session.session.commit.await_count == 0
    resources.object_storage.put_object.assert_not_awaited()
