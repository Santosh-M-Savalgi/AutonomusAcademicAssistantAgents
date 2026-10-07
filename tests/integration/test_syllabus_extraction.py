"""Actual registered handler with disposable PostgreSQL, Redis, MinIO and child processes."""

import asyncio
import hashlib
import sys
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from apps.worker.config import WorkerSettings
from apps.worker.extraction_config import ExtractionSettings
from apps.worker.handlers import HandlerContext
from apps.worker.runner import Worker
from apps.worker.syllabus import create_handler_registry
from packages.domain.extraction import ExtractionResult
from packages.persistence.jobs import JobRepository
from packages.persistence.models import Course, CourseMember, Document, DocumentVersion, Job
from tests.pdf_fixtures import syllabus_pdf

pytestmark = pytest.mark.live_integration


@pytest.fixture
async def pipeline(migrate_database, live_database, live_object_storage, minio_bucket,
                   async_http_client, auth_headers, service_settings):
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Synthetic syllabus extraction"))
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
    settings = WorkerSettings(_env_file=None, concurrency=1, lease_seconds=30,
                              heartbeat_seconds=1, io_timeout_seconds=1, poll_seconds=0.05,
                              reaper_seconds=1, shutdown_grace_seconds=0.05)
    yield SimpleNamespace(
        database=live_database, storage=live_object_storage, settings=service_settings,
        client=async_http_client, auth_headers=auth_headers, course_id=course_id,
        repository=JobRepository(live_database, retry_base=0.01, retry_max=0.04),
        config=settings, limits=ExtractionSettings(_env_file=None, timeout_seconds=15),
        job_id=job_id, document=document, version=version, pdf=pdf,
    )


def worker_for(pipeline, settings=None):
    registry = create_handler_registry(pipeline.database, settings or pipeline.settings,
                                        pipeline.limits)
    return Worker(pipeline.repository, registry, pipeline.config)


async def state(pipeline):
    async with pipeline.database.session() as session:
        return await session.get(Job, pipeline.job_id)


async def claim_and_execute(pipeline, worker=None):
    worker = worker or worker_for(pipeline)
    claim = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)
    assert claim is not None
    await worker.execute(claim)
    return claim, await state(pipeline)


async def artifact(pipeline, reference):
    prefix = f"minio://{pipeline.storage.bucket}/"
    assert reference.startswith(prefix)

    def read():
        response = pipeline.storage.client.get_object(pipeline.storage.bucket,
                                                     reference.removeprefix(prefix))
        try:
            data = response.read(pipeline.limits.max_output_bytes + 1)
            assert len(data) <= pipeline.limits.max_output_bytes
            return ExtractionResult.model_validate_json(data)
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(read)


async def artifact_keys(pipeline):
    return await asyncio.to_thread(lambda: [
        item.object_name for item in pipeline.storage.client.list_objects(
            pipeline.storage.bucket, recursive=True,
        ) if "/extractions/" in item.object_name
    ])


async def make_due(pipeline, *, expired=False):
    async with pipeline.database.session() as session, session.begin():
        values = {"lease_expires_at": func.clock_timestamp() - text("interval '1 second'")} if (
            expired
        ) else {"run_after": func.clock_timestamp() - text("interval '1 second'")}
        await session.execute(update(Job).where(Job.id == pipeline.job_id).values(**values))
    if expired:
        assert await pipeline.repository.reap() == 1
        await make_due(pipeline)


async def test_registered_handler_persists_page_aware_artifact_before_success(
    pipeline, monkeypatch, caplog,
):
    assert pipeline.document.size_bytes == len(pipeline.pdf)
    assert pipeline.version.sha256 == hashlib.sha256(pipeline.pdf).hexdigest()
    original_finish = pipeline.repository.finish

    async def finish(job, status, **kwargs):
        if status == "SUCCEEDED":
            assert (await state(pipeline)).status == "RUNNING"
            saved = await artifact(pipeline, kwargs["result_ref"])
            assert saved.source.document_id == pipeline.document.id
        return await original_finish(job, status, **kwargs)

    monkeypatch.setattr(pipeline.repository, "finish", finish)
    claim, row = await claim_and_execute(pipeline)
    assert row.status == "SUCCEEDED"
    result = await artifact(pipeline, row.result_ref)
    assert result.source.version_id == pipeline.version.id
    assert result.source.sha256 == pipeline.document.sha256
    assert result.schema_version == "extraction-v1"
    assert [p.number for p in result.pages] == [1, 2, 3]
    assert "Café α concepts" in result.pages[0].text
    assert result.pages[2].status == "OCR_CANDIDATE"
    assert [n.type for n in result.nodes[:5]] == ["MODULE", "UNIT", "CHAPTER", "SECTION", "TOPIC"]
    assert result.nodes[4].parent_id == result.nodes[3].id
    assert result.nodes[5].source.page == 2
    # At-least-once re-execution converges on the same object and never changes terminal state.
    handler = create_handler_registry(pipeline.database, pipeline.settings, pipeline.limits)[
        "syllabus_ingestion"
    ]
    repeated = await asyncio.gather(*[
        handler(claim, HandlerContext(claim.worker_id, asyncio.Event())) for _ in range(2)
    ])
    assert all(item.result_ref == row.result_ref for item in repeated)
    assert await artifact_keys(pipeline) == [result.artifact_key()]
    assert (await state(pipeline)).status == "SUCCEEDED"
    assert "Café" not in caplog.text and "Theory" not in caplog.text
    assert pipeline.settings.minio_secret_key.get_secret_value() not in caplog.text


async def test_payload_key_is_ignored_and_legacy_version_is_pinned(pipeline):
    async with pipeline.database.session() as session, session.begin():
        job = await session.get(Job, pipeline.job_id)
        job.payload = {"document_id": str(pipeline.document.id),
                       "course_id": str(pipeline.document.course_id),
                       "storage_key": "../../untrusted-source.pdf"}
        session.add(DocumentVersion(document_id=pipeline.document.id, version_number=2,
                                    storage_key="untrusted-newer", sha256="0" * 64,
                                    size_bytes=1, page_count=1))
    _, row = await claim_and_execute(pipeline)
    assert row.status == "SUCCEEDED"
    assert (await artifact(pipeline, row.result_ref)).source.version_id == pipeline.version.id


async def test_explicit_version_results_cannot_overwrite_original_version(pipeline):
    version_id = uuid4()
    content = syllabus_pdf(["Unit II: Replacement\n2.1 New Content"])
    key = (f"courses/{pipeline.document.course_id}/documents/{pipeline.document.id}/versions/2.pdf")
    await pipeline.storage.put_object(key, BytesIO(content), len(content),
                                      content_type="application/pdf")
    async with pipeline.database.session() as session, session.begin():
        session.add(DocumentVersion(id=version_id, document_id=pipeline.document.id,
                                    version_number=2, storage_key=key, size_bytes=len(content),
                                    sha256=hashlib.sha256(content).hexdigest(), page_count=1))
    claim, first = await claim_and_execute(pipeline)
    from dataclasses import replace

    handler = create_handler_registry(pipeline.database, pipeline.settings, pipeline.limits)[
        "syllabus_ingestion"
    ]
    second = await handler(
        replace(claim, payload={**claim.payload, "document_version_id": str(version_id)}),
        HandlerContext(claim.worker_id, asyncio.Event()),
    )
    first_result = await artifact(pipeline, first.result_ref)
    second_result = await artifact(pipeline, second.result_ref)
    assert first_result.source.version_id == pipeline.version.id
    assert second_result.source.version_id == version_id
    assert second_result.source.version_number == 2
    assert len(second_result.pages) == 1
    assert first.result_ref != second.result_ref
    assert len(await artifact_keys(pipeline)) == 2


@pytest.mark.parametrize("invalid", ["missing_document", "wrong_course", "wrong_version",
                                     "invalid_key", "metadata_mismatch"])
async def test_invalid_database_references_fail_permanently(pipeline, invalid):
    async with pipeline.database.session() as session, session.begin():
        job = await session.get(Job, pipeline.job_id)
        if invalid in {"missing_document", "wrong_course", "wrong_version"}:
            field = {"missing_document": "document_id", "wrong_course": "course_id",
                     "wrong_version": "document_version_id"}[invalid]
            job.payload = {**job.payload, field: str(uuid4())}
        elif invalid == "invalid_key":
            version = await session.get(DocumentVersion, pipeline.version.id)
            version.storage_key = "another/document.pdf"
        else:
            document = await session.get(Document, pipeline.document.id)
            document.sha256 = "0" * 64
    _, row = await claim_and_execute(pipeline)
    assert row.status == "FAILED"
    assert row.error_code == ("DOCUMENT_NOT_FOUND" if invalid == "missing_document" else
                              "SOURCE_MISMATCH" if invalid == "metadata_mismatch" else
                              "INVALID_DOCUMENT")
    assert row.result_ref is None and not await artifact_keys(pipeline)


@pytest.mark.parametrize("kind", ["missing", "malformed", "encrypted", "checksum", "size"])
async def test_source_object_failures_are_explicit_and_never_succeed(pipeline, kind):
    if kind == "missing":
        await pipeline.storage.delete_object(pipeline.document.storage_key)
    else:
        content = (syllabus_pdf(["private"], encrypted=True) if kind == "encrypted" else
                   b"%PDF-1.7\ninvalid" if kind == "malformed" else b"corrupt")
        await pipeline.storage.put_object(pipeline.document.storage_key, BytesIO(content),
                                          len(content), content_type="application/pdf")
        if kind in {"malformed", "encrypted", "size"}:
            async with pipeline.database.session() as session, session.begin():
                for model, identity in [(Document, pipeline.document.id),
                                        (DocumentVersion, pipeline.version.id)]:
                    obj = await session.get(model, identity)
                    obj.sha256 = hashlib.sha256(content).hexdigest()
                    obj.size_bytes = len(content) + (1 if kind == "size" else 0)
                    obj.page_count = 1
    _, row = await claim_and_execute(pipeline)
    assert row.status == "FAILED" and row.result_ref is None
    assert row.error_code == {"missing": "SOURCE_NOT_FOUND", "malformed": "INVALID_PDF",
                              "encrypted": "ENCRYPTED_PDF", "checksum": "SOURCE_MISMATCH",
                              "size": "SOURCE_MISMATCH"}[kind]
    assert not await artifact_keys(pipeline)


async def test_temporary_minio_outage_retries_then_recovers(pipeline):
    unavailable = pipeline.settings.model_copy(update={"minio_endpoint": "127.0.0.1:1"})
    _, row = await claim_and_execute(pipeline, worker_for(pipeline, unavailable))
    assert row.status == "RETRYING" and row.error_code == "STORAGE_UNAVAILABLE"
    assert row.result_ref is None
    await make_due(pipeline)
    _, recovered = await claim_and_execute(pipeline)
    assert recovered.status == "SUCCEEDED" and recovered.attempts == 2


async def test_database_completion_rollback_reuses_durable_artifact(pipeline):
    worker = worker_for(pipeline)
    claim = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)

    def abort_completion(session):
        session.connection().execute(text("SELECT 1 / 0"))

    event.listen(Session, "before_commit", abort_completion)
    try:
        await worker.execute(claim)
    finally:
        event.remove(Session, "before_commit", abort_completion)
    row = await state(pipeline)
    keys = await artifact_keys(pipeline)
    assert row.status == "RUNNING" and row.result_ref is None and len(keys) == 1
    await make_due(pipeline, expired=True)
    _, row = await claim_and_execute(pipeline)
    assert row.status == "SUCCEEDED" and row.attempts == 2
    assert await artifact_keys(pipeline) == keys
    assert row.result_ref.endswith(keys[0])


@pytest.mark.parametrize("interruption", ["shutdown", "timeout"])
async def test_interrupted_extraction_kills_child_and_recovers(pipeline, monkeypatch, interruption):
    import apps.worker.syllabus as module

    original_spawn = asyncio.create_subprocess_exec
    started = asyncio.Event()
    children = []
    code = (
        "import signal, sys\nimport apps.worker.extraction_process as m\n"
        "def blocked(*args, **kwargs):\n"
        "    sys.stdout.write('EXTRACTING\\n'); sys.stdout.flush(); signal.pause()\n"
        "m.extract_pdf=blocked\nm.main()"
    )

    async def spawn(*args, **kwargs):
        process = await original_spawn(sys.executable, "-c", code, **kwargs)
        children.append(process)
        original_read = process.stdout.read

        async def read(size):
            marker = await process.stdout.readline()
            assert marker == b"EXTRACTING\n"
            started.set()
            return await original_read(size)

        monkeypatch.setattr(process.stdout, "read", read)
        return process

    if interruption == "timeout":
        pipeline.limits.timeout_seconds = 3
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    worker = worker_for(pipeline)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(started.wait(), 10)
        if interruption == "shutdown":
            worker.stop()
        else:
            # Await the terminal deadline outcome without allowing another claim.
            async with asyncio.timeout(8):
                while (await state(pipeline)).status == "RUNNING":
                    await asyncio.sleep(0.01)
            worker.stop()
        await asyncio.wait_for(task, 10)
        if worker.unfinished_handlers:
            await asyncio.wait_for(asyncio.gather(*worker.unfinished_handlers,
                                                 return_exceptions=True), 5)
        assert children and all(p.returncode is not None for p in children)
        row = await state(pipeline)
        assert row.result_ref is None and not await artifact_keys(pipeline)
        if interruption == "shutdown":
            assert row.status == "RETRYING" and row.error_code == "WORKER_SHUTDOWN"
        else:
            assert row.status == "FAILED" and row.error_code == "EXTRACTION_TIMEOUT"
    finally:
        worker.stop()
        await asyncio.wait_for(task, 10)
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()
    if interruption == "shutdown":
        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", original_spawn)
        await make_due(pipeline)
        _, row = await claim_and_execute(pipeline)
        assert row.status == "SUCCEEDED"


async def test_production_registry_keeps_unknown_type_failure(pipeline):
    async with pipeline.database.session() as session, session.begin():
        await session.execute(update(Job).where(Job.id == pipeline.job_id)
                              .values(job_type="unsupported_type"))
    _, row = await claim_and_execute(pipeline)
    assert row.status == "FAILED" and row.error_code == "UNKNOWN_JOB_TYPE"
    assert not await artifact_keys(pipeline)


async def test_registered_handler_temporary_database_failure_is_retryable(pipeline, monkeypatch):
    import apps.worker.syllabus as module

    async def failing(*args):
        async with pipeline.database.session() as session:
            await session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(module, "resolve_source", failing)
    _, row = await claim_and_execute(pipeline)
    assert row.status == "RETRYING" and row.error_code == "DATABASE_UNAVAILABLE"
    assert row.result_ref is None
