"""Real process cancellation/deadlines with event synchronization and anonymous temp files."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

from apps.worker.extraction_config import ExtractionSettings
from apps.worker.extraction_process import ExtractionRequest
from apps.worker.handlers import HandlerFailure
from apps.worker.syllabus import run_extraction
from packages.persistence.object_storage import ObjectStorageSettings
from tests.pdf_fixtures import document_source


@pytest.mark.parametrize("mode", ["timeout", "cancel", "launch_cancel"])
async def test_deadline_or_cancellation_kills_process_and_closes_tempfile(monkeypatch, mode):
    import apps.worker.syllabus as module

    original = asyncio.create_subprocess_exec
    started, allow_return = asyncio.Event(), asyncio.Event()
    children = []
    # File is anonymous; read the ready marker before returning the process handle.
    code = ("import tempfile, sys, signal; "
            "f=tempfile.TemporaryFile(dir='.'); f.write(b'synthetic'); "
            "sys.stdout.write('READY'); sys.stdout.flush(); signal.pause()")

    async def spawn(*args, **kwargs):
        child = await original(sys.executable, "-c", code, **kwargs)
        children.append(child)
        assert await child.stdout.readexactly(5) == b"READY"
        started.set()
        if mode == "launch_cancel":
            await allow_return.wait()
        return child

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    request = ExtractionRequest(
        source=document_source(b"test", 1), object_key="source",
        storage=ObjectStorageSettings("127.0.0.1:1", "test", "test", "test", False),
        limits=ExtractionSettings(_env_file=None, timeout_seconds=0.05),
        max_pdf_bytes=10000, max_pdf_pages=10, parent_pid=os.getpid(),
    )
    task = asyncio.create_task(run_extraction(request))
    await asyncio.wait_for(started.wait(), 5)
    if mode != "timeout":
        task.cancel()
        allow_return.set()
    try:
        if mode == "timeout":
            with pytest.raises(HandlerFailure) as error:
                await asyncio.wait_for(task, 5)
            assert error.value.code == "EXTRACTION_TIMEOUT"
        else:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        assert children[0].returncode is not None
        # No child owns an open descriptor after it has been reaped.
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()


async def test_registry_rejects_bad_payload_before_any_retrieval(test_settings):
    from dataclasses import replace
    from datetime import UTC, datetime
    from uuid import uuid4

    from apps.worker.handlers import HandlerContext
    from apps.worker.syllabus import create_handler_registry
    from packages.domain.enums import JobLane
    from packages.domain.jobs import ClaimedJob

    database = AsyncMock()
    registry = create_handler_registry(database, test_settings, ExtractionSettings(_env_file=None))
    assert set(registry) == {"syllabus_ingestion", "curriculum_draft", "graph_build"}
    job = ClaimedJob(uuid4(), "syllabus_ingestion", {}, JobLane.BATCH, 0, 1, 3,
                     "worker", datetime.now(UTC))
    for payload in [{}, {"document_id": "bad", "course_id": str(uuid4())},
                    {"document_id": str(uuid4()), "course_id": str(uuid4()), "url": "untrusted"}]:
        with pytest.raises(HandlerFailure) as error:
            await registry["syllabus_ingestion"](
                replace(job, payload=payload), HandlerContext("worker", asyncio.Event()),
            )
        assert error.value.code == "INVALID_DOCUMENT"
    database.session.assert_not_called()
