"""Bounded, checkpointed curriculum generation; generic worker owns fenced completion."""

import asyncio

import psycopg
import structlog
from minio.error import S3Error
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from urllib3.exceptions import HTTPError

from apps.api.config import Settings
from apps.worker.handlers import HandlerContext, HandlerFailure, HandlerResult
from packages.agents.curriculum import generate_sections
from packages.curriculum.config import DraftSettings
from packages.curriculum.drafts import assemble_draft, generation_inputs
from packages.domain.curriculum import DraftJobPayload, draft_identity
from packages.domain.jobs import ClaimedJob, JobErrorCode
from packages.model_client.curriculum import CurriculumProvider, FakeProvider, ProviderError
from packages.persistence.checkpoints import draft_checkpointer
from packages.persistence.database import Database
from packages.persistence.drafts import extraction_source, persist_draft
from packages.persistence.extractions import SourceResolutionError, load_extraction
from packages.persistence.object_storage import ObjectIntegrityError, ObjectLimitError
from packages.persistence.worker_storage import bounded_storage, storage_call

logger = structlog.get_logger("aaa.curriculum")


class DraftHandler:
    def __init__(self, database: Database, settings: Settings,
                 *, provider: CurriculumProvider | None = None,
                 limits: DraftSettings | None = None):
        self.database, self.settings = database, settings
        self.provider = provider
        self.limits = limits or DraftSettings()

    async def __call__(self, job: ClaimedJob, context: HandlerContext) -> HandlerResult:
        try:
            payload = DraftJobPayload.model_validate(job.payload)
        except ValidationError:
            raise HandlerFailure(JobErrorCode.INVALID_DOCUMENT) from None
        if self.provider is None and self.settings.aaa_profile != "mock":
            raise HandlerFailure(JobErrorCode.PROVIDER_NOT_CONFIGURED)
        provider = self.provider or FakeProvider()
        storage = bounded_storage(
            self.settings.minio_endpoint, self.settings.minio_access_key,
            self.settings.minio_secret_key.get_secret_value(), self.settings.minio_bucket,
            self.settings.minio_secure,
        )
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                await context.progress.stage_started(
                    "loading_extraction", progress_percent=5,
                    message="Loading extracted syllabus",
                )
                source, reference = await extraction_source(
                    self.database, payload.extraction_job_id,
                )
                if (source.course_id != payload.course_id
                        or source.document_id != payload.document_id
                        or source.version_id != payload.document_version_id
                        or job.id != draft_identity(payload.extraction_job_id, reference)):
                    raise HandlerFailure(JobErrorCode.INVALID_EXTRACTION)
                extraction = await storage_call(
                    load_extraction, storage, reference, source, self.limits.artifact_max_bytes,
                )
                if extraction.summary.status == "NO_TEXT":
                    raise HandlerFailure(JobErrorCode.INSUFFICIENT_EXTRACTION)
                requests = generation_inputs(job.id, extraction)
                if len(requests) > self.limits.max_sections or any(
                    len(request.sections) > 64 for request in requests
                ):
                    raise HandlerFailure(JobErrorCode.DRAFT_LIMIT_EXCEEDED)
                if context.cancelled.is_set() or context.shutdown.is_set():
                    raise asyncio.CancelledError
                await context.progress.stage_started(
                    "generating_curriculum", progress_percent=20,
                    message="Generating curriculum draft",
                )
                async with draft_checkpointer(self.settings.database_url) as saver:
                    outputs = await generate_sections(
                        provider, extraction, job.id, job.attempts, saver,
                        max_sections=self.limits.max_sections,
                        max_output_bytes=self.limits.unit_output_max_bytes,
                    )
                await context.progress.progress(
                    "generating_curriculum", 75, message="Validating generated sections",
                )
                draft = assemble_draft(job.id, payload.extraction_job_id, reference,
                                       extraction, outputs, provider.versions)
                if len(draft.canonical_bytes()) > self.limits.artifact_max_bytes:
                    raise HandlerFailure(JobErrorCode.DRAFT_LIMIT_EXCEEDED)
                await context.progress.stage_started(
                    "persisting_draft", progress_percent=85, message="Persisting curriculum draft",
                )
                result_ref = await storage_call(
                    persist_draft, storage, draft, self.limits.artifact_max_bytes,
                    self.limits.artifact_max_bytes,
                )
                await context.progress.progress(
                    "persisting_draft", 100, message="Curriculum draft complete",
                )
        except HandlerFailure:
            raise
        except SourceResolutionError as error:
            raise HandlerFailure(error.code) from None
        except (SQLAlchemyError, psycopg.Error):
            raise HandlerFailure(JobErrorCode.DATABASE_UNAVAILABLE, retryable=True) from None
        except TimeoutError:
            raise HandlerFailure(JobErrorCode.DRAFT_TIMEOUT, retryable=True) from None
        except (S3Error, HTTPError, OSError):
            raise HandlerFailure(JobErrorCode.STORAGE_UNAVAILABLE, retryable=True) from None
        except ProviderError as error:
            raise HandlerFailure(JobErrorCode.PROVIDER_UNAVAILABLE,
                                 retryable=error.retryable) from None
        except (ObjectIntegrityError, ObjectLimitError):
            raise HandlerFailure(JobErrorCode.ARTIFACT_CONFLICT) from None
        except ValueError:
            raise HandlerFailure(JobErrorCode.INVALID_PROVIDER_OUTPUT) from None
        finally:
            await storage.close()
        logger.info("curriculum_draft_persisted", job_id=str(job.id))
        return HandlerResult(result_ref=result_ref)
