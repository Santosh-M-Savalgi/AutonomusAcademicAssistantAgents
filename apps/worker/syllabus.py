"""Production syllabus handler: trusted DB references, isolated processing, fenced completion."""

import asyncio
import os
import signal
import sys
from uuid import UUID

import structlog
from pydantic import Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from apps.api.config import Settings
from apps.worker.extraction_config import ExtractionSettings
from apps.worker.extraction_process import ExtractionOutcome, ExtractionRequest
from apps.worker.handlers import HandlerContext, HandlerFailure, HandlerResult, JobHandler
from packages.domain.jobs import ClaimedJob, JobErrorCode
from packages.domain.models import DomainModel
from packages.persistence.database import Database
from packages.persistence.drafts import enqueue_draft_for_source
from packages.persistence.extractions import SourceResolutionError, resolve_source
from packages.persistence.object_storage import ObjectStorageSettings

logger = structlog.get_logger("aaa.extraction")


class SyllabusPayload(DomainModel):
    course_id: UUID
    document_id: UUID
    document_version_id: UUID | None = None
    # Retained only for old jobs; this value is never used to access storage.
    storage_key: str | None = Field(default=None, max_length=512)


async def run_extraction(request: ExtractionRequest) -> ExtractionOutcome:
    launch = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, "-m", "apps.worker.extraction_process",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    ))
    try:
        process = await asyncio.shield(launch)
    except asyncio.CancelledError:
        # Cancellation can race process creation; retain the handle and reap it either way.
        process = await launch
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    try:
        async with asyncio.timeout(request.limits.timeout_seconds):
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(request.model_dump_json().encode())
            await process.stdin.drain()
            process.stdin.close()
            output = await process.stdout.read(4097)
            await process.wait()
            if len(output) > 4096:
                raise HandlerFailure(JobErrorCode.EXTRACTION_OUTPUT_LIMIT)
            if process.returncode in {-signal.SIGKILL, -signal.SIGXCPU, -signal.SIGXFSZ}:
                raise HandlerFailure(JobErrorCode.EXTRACTION_RESOURCE_LIMIT)
            if process.returncode != 0:
                raise HandlerFailure(JobErrorCode.HANDLER_EXCEPTION, retryable=True)
            return ExtractionOutcome.model_validate_json(output)
    except TimeoutError:
        raise HandlerFailure(JobErrorCode.EXTRACTION_TIMEOUT) from None
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


class SyllabusHandler:
    def __init__(self, database: Database, settings: Settings, limits: ExtractionSettings):
        self.database, self.settings, self.limits = database, settings, limits

    async def __call__(self, job: ClaimedJob, context: HandlerContext) -> HandlerResult:
        try:
            payload = SyllabusPayload.model_validate(job.payload)
        except ValidationError:
            raise HandlerFailure(JobErrorCode.INVALID_DOCUMENT) from None
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                await context.progress.stage_started(
                    "source_validation", message="Validating source",
                )
                source, key = await resolve_source(self.database, payload.document_id,
                                                   payload.course_id, payload.document_version_id)
                if context.cancelled.is_set() or context.shutdown.is_set():
                    raise asyncio.CancelledError
                await context.progress.stage_started(
                    "extraction", progress_percent=10, message="Extracting syllabus text",
                )
                outcome = await run_extraction(ExtractionRequest(
                    source=source, object_key=key,
                    storage=ObjectStorageSettings(
                        endpoint=self.settings.minio_endpoint,
                        access_key=self.settings.minio_access_key,
                        secret_key=self.settings.minio_secret_key.get_secret_value(),
                        bucket=self.settings.minio_bucket, secure=self.settings.minio_secure,
                        io_timeout_seconds=min(10, self.limits.timeout_seconds),
                    ),
                    limits=self.limits, max_pdf_bytes=self.settings.max_upload_size_bytes,
                    max_pdf_pages=self.settings.max_pdf_pages, parent_pid=os.getpid(),
                ))
        except SourceResolutionError as error:
            raise HandlerFailure(error.code) from None
        except SQLAlchemyError:
            raise HandlerFailure(JobErrorCode.DATABASE_UNAVAILABLE, retryable=True) from None
        except TimeoutError:
            raise HandlerFailure(JobErrorCode.EXTRACTION_TIMEOUT) from None
        if outcome.error_code is not None:
            logger.warning("syllabus_extraction_failed", job_id=str(job.id),
                           reason=outcome.error_code.value)
            raise HandlerFailure(outcome.error_code, retryable=outcome.retryable)
        if outcome.result_ref is None:
            raise HandlerFailure(JobErrorCode.HANDLER_EXCEPTION, retryable=True)
        try:
            await context.progress.stage_started(
                "persisting_extraction", progress_percent=80,
                message="Persisting extracted result",
            )
            await context.progress.partial_result("extraction")
            await enqueue_draft_for_source(
                self.database, payload.course_id, job.id, source, outcome.result_ref,
            )
            await context.progress.progress(
                "enqueueing_draft", 100, message="Extraction complete",
            )
        except SQLAlchemyError:
            raise HandlerFailure(JobErrorCode.DATABASE_UNAVAILABLE, retryable=True) from None
        logger.info("syllabus_extraction_persisted", job_id=str(job.id))
        return HandlerResult(result_ref=outcome.result_ref)


def create_handler_registry(
    database: Database, settings: Settings, limits: ExtractionSettings,
) -> dict[str, JobHandler]:
    from apps.worker.draft import DraftHandler
    from apps.worker.graph import GraphHandler

    return {"syllabus_ingestion": SyllabusHandler(database, settings, limits),
            "curriculum_draft": DraftHandler(database, settings),
            "graph_build": GraphHandler(database, settings)}
