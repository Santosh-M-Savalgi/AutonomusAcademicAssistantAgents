"""End-to-end deterministic curriculum draft generation through the durable worker."""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update

from apps.worker.config import WorkerSettings
from apps.worker.draft import DraftHandler
from apps.worker.extraction_config import ExtractionSettings
from apps.worker.runner import Worker
from apps.worker.syllabus import create_handler_registry
from packages.curriculum.config import DraftSettings
from packages.model_client.curriculum import FakeProvider, ProviderError
from packages.persistence.drafts import load_draft
from packages.persistence.jobs import JobRepository
from packages.persistence.models import Course, CourseMember, Document, DocumentVersion, Job
from packages.persistence.worker_storage import bounded_storage
from tests.pdf_fixtures import syllabus_pdf

pytestmark = pytest.mark.live_integration


@pytest.fixture
async def pipeline(migrate_database, live_database, live_object_storage, minio_bucket,
                   async_http_client, auth_headers, service_settings):
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Synthetic draft generation"))
        session.add(CourseMember(course_id=course_id, subject="fixture-student", role="student"))
    pdf = syllabus_pdf([
        "Module I: Foundations\nUnit 1: Algebra\nChapter I: Sets\nSection 1.1 Relations\n"
        "1.1.1 Functions\nCafé α concepts\nName    Hours\nTheory    3",
        "Module II: Applications\n2.1 Methods\n2.1.1 Practice", "",
    ])
    response = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus", headers=auth_headers,
        files={"upload": ("synthetic.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 202, response.text
    job_id, document_id = UUID(response.json()["job_id"]), UUID(response.json()["document_id"])
    async with live_database.session() as session:
        document = await session.get(Document, document_id)
        version = (await session.scalars(select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
        ))).one()
    config = WorkerSettings(_env_file=None, concurrency=1, lease_seconds=30,
                            heartbeat_seconds=1, io_timeout_seconds=1, poll_seconds=0.05,
                            reaper_seconds=1, shutdown_grace_seconds=0.05)
    yield SimpleNamespace(
        database=live_database, storage=live_object_storage, settings=service_settings,
        client=async_http_client, auth_headers=auth_headers, course_id=course_id,
        repository=JobRepository(live_database, retry_base=0.01, retry_max=0.04),
        config=config, job_id=job_id, document=document, version=version,
    )


async def row(pipeline, job_id):
    async with pipeline.database.session() as session:
        return await session.get(Job, job_id)


async def run_extraction(pipeline):
    registry = create_handler_registry(pipeline.database, pipeline.settings,
                                       ExtractionSettings(_env_file=None))
    worker = Worker(pipeline.repository, registry, pipeline.config)
    claim = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)
    assert claim is not None and claim.type == "syllabus_ingestion"
    await worker.execute(claim)
    result = await row(pipeline, pipeline.job_id)
    assert result.status == "SUCCEEDED"
    return worker


async def run_draft(pipeline):
    worker = Worker(pipeline.repository, create_handler_registry(
        pipeline.database, pipeline.settings,
        ExtractionSettings(_env_file=None),
    ), pipeline.config)
    async with pipeline.database.session() as session:
        draft_job = (await session.scalars(select(Job).where(
            Job.job_type == "curriculum_draft", Job.parent_job_id == pipeline.job_id,
        ))).one()
    claim = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)
    assert claim is not None and claim.id == draft_job.id
    await worker.execute(claim)
    return await row(pipeline, draft_job.id)


async def test_upload_extraction_and_draft_are_durable_and_api_readable(pipeline):
    await run_extraction(pipeline)
    draft_job = await run_draft(pipeline)
    assert draft_job.status == "SUCCEEDED"
    assert draft_job.result_ref
    settings = pipeline.settings
    storage = bounded_storage(settings.minio_endpoint, settings.minio_access_key,
                              settings.minio_secret_key.get_secret_value(),
                              settings.minio_bucket, settings.minio_secure)
    try:
        from packages.persistence.drafts import extraction_source

        source, extraction_ref = await extraction_source(pipeline.database, pipeline.job_id)
        draft = await asyncio.to_thread(
            load_draft, storage, draft_job.result_ref, draft_job.id, pipeline.job_id,
            extraction_ref, source, 4 * 1024 * 1024,
        )
    finally:
        await storage.close()
    assert draft.status == "DRAFT"
    assert draft.extraction_job_id == pipeline.job_id
    assert draft.source.version_id == pipeline.version.id
    assert draft.elements and any(node.origin == "GENERATED" for node in draft.elements)
    assert all(node.sources for node in draft.elements)
    response = await pipeline.client.get(
        f"/api/v3/curriculum/{draft_job.id}/draft", headers=pipeline.auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["draft"]["status"] == "DRAFT"
    manual = await pipeline.client.post(
        f"/api/v3/courses/{pipeline.course_id}/curriculum/drafts",
        headers=pipeline.auth_headers, json={"extraction_job_id": str(pipeline.job_id)},
    )
    assert manual.status_code == 202, manual.text
    assert manual.json()["job_id"] == str(draft_job.id)


async def test_draft_retry_reuses_artifact_and_checkpoint(pipeline):
    await run_extraction(pipeline)
    first = await run_draft(pipeline)
    first_ref = first.result_ref
    async with pipeline.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == first.id).values(
            status="RETRYING", run_after=func.clock_timestamp(),
        ))
    second_worker = Worker(pipeline.repository, create_handler_registry(
        pipeline.database, pipeline.settings,
        ExtractionSettings(_env_file=None),
    ), pipeline.config)
    claim = await pipeline.repository.claim(second_worker.worker_id, pipeline.config.lanes, 30)
    assert claim is not None
    await second_worker.execute(claim)
    second = await row(pipeline, first.id)
    assert second.status == "SUCCEEDED" and second.result_ref == first_ref


async def test_provider_failure_is_retryable_and_does_not_persist_draft(pipeline):
    await run_extraction(pipeline)

    class FailingProvider(FakeProvider):
        async def generate(self, request):
            raise ProviderError(retryable=True)

    async with pipeline.database.session() as session:
        draft_job = (await session.scalars(select(Job).where(
            Job.job_type == "curriculum_draft", Job.parent_job_id == pipeline.job_id,
        ))).one()
    claim = await pipeline.repository.claim("failing-provider", pipeline.config.lanes, 30)
    assert claim is not None
    handler = DraftHandler(pipeline.database, pipeline.settings, provider=FailingProvider(),
                           limits=DraftSettings(_env_file=None, timeout_seconds=10))
    worker = Worker(pipeline.repository, {"curriculum_draft": handler}, pipeline.config)
    await worker.execute(claim)
    result = await row(pipeline, draft_job.id)
    assert result.status == "RETRYING" and result.error_code == "PROVIDER_UNAVAILABLE"
    assert result.result_ref is None


async def test_stale_draft_attempt_cannot_complete_after_lease_recovery(pipeline):
    await run_extraction(pipeline)
    async with pipeline.database.session() as session:
        draft_job = (await session.scalars(select(Job).where(
            Job.job_type == "curriculum_draft", Job.parent_job_id == pipeline.job_id,
        ))).one()
    old = await pipeline.repository.claim("old-attempt", pipeline.config.lanes, 30)
    assert old is not None
    async with pipeline.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == old.id).values(
            lease_expires_at=func.clock_timestamp() - text("interval '1 second'"),
        ))
    assert await pipeline.repository.reap() == 1
    async with pipeline.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == old.id).values(
            run_after=func.clock_timestamp(),
        ))
    current = await pipeline.repository.claim("new-attempt", pipeline.config.lanes, 30)
    assert current is not None and current.attempts == old.attempts + 1
    assert await pipeline.repository.finish(old, "SUCCEEDED", result_ref="stale") is False
    assert (await row(pipeline, draft_job.id)).status == "RUNNING"
