"""Live curriculum upload vertical-slice integration tests."""

import asyncio
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from apps.api.auth.jwt import JWTService
from packages.persistence import Course, CourseMember, Document, Job, LearningEventRecord

pytestmark = pytest.mark.live_integration


def pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


async def test_authenticated_upload_persists_storage_records_and_is_idempotent(
    migrate_database,
    live_database,
    live_object_storage,
    async_http_client,
    auth_headers,
) -> None:
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session:
        session.add(Course(id=course_id, title="Integration Course"))
        session.add(CourseMember(course_id=course_id, subject="fixture-student", role="student"))
        await session.commit()

    content = pdf_bytes()
    headers = {**auth_headers, "Idempotency-Key": "curriculum-upload-1"}
    files = {"upload": ("../../course.pdf", content, "text/plain")}
    response = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus", files=files, headers=headers
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "accepted"

    second = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus",
        files={"upload": ("different-name.pdf", content, "application/octet-stream")},
        headers=headers,
    )
    assert second.status_code == 202
    assert second.json() == accepted

    async with live_database.session() as session:
        document = await session.get(Document, accepted["document_id"])
        job = await session.get(Job, accepted["job_id"])
        events = (
            await session.execute(
                select(LearningEventRecord).where(
                    LearningEventRecord.course_id == course_id,
                )
            )
        ).scalars().all()

    assert document is not None
    assert document.original_filename == "course.pdf"
    assert document.content_type == "application/pdf"
    assert document.size_bytes == len(content)
    assert job is not None
    assert job.status == "PENDING"
    assert job.job_type == "syllabus_ingestion"
    assert len(events) == 1

    stored = live_object_storage.client.get_object(live_object_storage.bucket, document.storage_key)
    try:
        assert stored.read() == content
    finally:
        stored.close()
        stored.release_conn()
        live_object_storage.client.remove_object(live_object_storage.bucket, document.storage_key)


async def test_upload_requires_course_membership(
    migrate_database,
    live_database,
    async_http_client,
    test_settings,
) -> None:
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session:
        session.add(Course(id=course_id, title="Protected Course"))
        await session.commit()

    token = JWTService(test_settings).create_access_token("not-a-member")
    response = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus",
        files={"upload": ("syllabus.pdf", pdf_bytes(), "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "COURSE_UPLOAD_FORBIDDEN"


async def test_wakeup_failure_preserves_committed_upload_and_object(
    migrate_database, live_database, live_object_storage, async_http_client,
    auth_headers, test_app, monkeypatch,
) -> None:
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session:
        session.add(Course(id=course_id, title="Notification Failure Course"))
        session.add(CourseMember(course_id=course_id, subject="fixture-student", role="student"))
        await session.commit()
    publish = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    monkeypatch.setattr(test_app.state.runtime.redis.client, "publish", publish)
    response = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus",
        files={"upload": ("syllabus.pdf", pdf_bytes(), "application/pdf")},
        headers={**auth_headers, "Idempotency-Key": "wakeup-failure"},
    )
    assert response.status_code == 202
    publish.assert_awaited_once()
    async with live_database.session() as session:
        job = await session.get(Job, response.json()["job_id"])
        document = await session.get(Document, response.json()["document_id"])
        assert job.status == "PENDING"
        assert (await session.scalars(select(LearningEventRecord))).one().course_id == course_id
    try:
        stat = await asyncio.to_thread(
            live_object_storage.client.stat_object,
            live_object_storage.bucket, document.storage_key,
        )
        assert stat.size == document.size_bytes
    finally:
        await live_object_storage.delete_object(document.storage_key)
