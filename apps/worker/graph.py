"""Deterministic graph publication handler with attempt-fenced persistence."""

import asyncio
from hashlib import sha256

from minio.error import S3Error
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from apps.api.config import Settings
from apps.worker.handlers import HandlerContext, HandlerFailure, HandlerResult
from packages.curriculum.graph import graph_from_confirmed_revision
from packages.domain.graph import GraphBuildJobPayload
from packages.domain.jobs import ClaimedJob, JobErrorCode
from packages.persistence.artifacts import persist_json
from packages.persistence.database import Database
from packages.persistence.graphs import (
    GraphLeaseExpiredError,
    GraphPublicationConflictError,
    publish_graph_for_job,
)
from packages.persistence.models import CurriculumRevision as RevisionRow
from packages.persistence.review import get_review
from packages.persistence.worker_storage import bounded_storage, storage_call


class GraphHandler:
    """Build one deterministic graph from one exact confirmed revision."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def __call__(self, job: ClaimedJob, context: HandlerContext) -> HandlerResult:
        try:
            payload = GraphBuildJobPayload.model_validate(job.payload)
        except ValidationError:
            raise HandlerFailure(JobErrorCode.GRAPH_REVISION_MISMATCH) from None

        storage = bounded_storage(
            self.settings.minio_endpoint,
            self.settings.minio_access_key,
            self.settings.minio_secret_key.get_secret_value(),
            self.settings.minio_bucket,
            self.settings.minio_secure,
        )
        try:
            async with asyncio.timeout(30):
                await context.progress.stage_started(
                    "loading_confirmed_revision", progress_percent=5,
                    message="Loading confirmed curriculum revision",
                )
                async with self.database.session() as session:
                    revision_row = await session.get(RevisionRow, payload.curriculum_revision_id)
                if (
                    revision_row is None
                    or revision_row.artifact_ref != payload.revision_artifact_ref
                ):
                    raise HandlerFailure(JobErrorCode.GRAPH_REVISION_MISMATCH)
                if revision_row.artifact_sha256 != payload.revision_artifact_sha256:
                    raise HandlerFailure(JobErrorCode.GRAPH_CHECKSUM_MISMATCH)
                review, revision = await get_review(self.database, storage, payload.review_id)
                if (
                    review.course_id != payload.course_id
                    or review.confirmed_revision_id != payload.curriculum_revision_id
                    or review.status.value != "CONFIRMED"
                    or revision.id != payload.curriculum_revision_id
                ):
                    raise HandlerFailure(JobErrorCode.GRAPH_REVISION_MISMATCH)
                await context.progress.stage_started(
                    "building_graph", progress_percent=30,
                    message="Constructing deterministic graph",
                )
                snapshot = graph_from_confirmed_revision(
                    review, revision, infer_unmapped_leaves=True,
                    graph_version=payload.graph_version,
                )
                content = snapshot.canonical_bytes()
                digest = sha256(content).hexdigest()
                key = (
                    f"courses/{payload.course_id}/graphs/"
                    f"{payload.curriculum_revision_id}/v{payload.graph_version}/{digest}.json"
                )
                await context.progress.stage_started(
                    "persisting_graph_artifact", progress_percent=70,
                    message="Persisting immutable graph artifact",
                )
                artifact_ref = await storage_call(
                    persist_json, storage, key, content, 4 * 1024 * 1024,
                )
                await context.progress.progress(
                    "publishing_graph", 85, message="Publishing relational graph snapshot",
                )
                async with self.database.session() as session, session.begin():
                    published = await publish_graph_for_job(
                        session, job, snapshot, artifact_ref=artifact_ref,
                        artifact_sha256=digest, artifact_bytes=len(content),
                        actor_identity_id=payload.actor_identity_id,
                        actor_subject=payload.actor_subject,
                    )
                    if not published:
                        raise HandlerFailure(JobErrorCode.LEASE_EXPIRED)
                await context.progress.progress(
                    "publishing_graph", 100, message="Graph publication complete",
                )
                return HandlerResult(result_ref=artifact_ref)
        except HandlerFailure:
            raise
        except SQLAlchemyError:
            raise HandlerFailure(JobErrorCode.DATABASE_UNAVAILABLE, retryable=True) from None
        except (S3Error, OSError, TimeoutError):
            raise HandlerFailure(JobErrorCode.STORAGE_UNAVAILABLE, retryable=True) from None
        except GraphLeaseExpiredError:
            raise HandlerFailure(JobErrorCode.LEASE_EXPIRED) from None
        except GraphPublicationConflictError:
            raise HandlerFailure(JobErrorCode.GRAPH_PUBLICATION_CONFLICT) from None
        except ValueError:
            raise HandlerFailure(JobErrorCode.GRAPH_DAG_INVALID) from None
        finally:
            await storage.close()
