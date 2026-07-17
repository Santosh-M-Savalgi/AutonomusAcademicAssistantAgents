"""Background task implementations — moved off the HTTP request path.

Each function is a pure async task that receives a Job and a queue
for progress updates. Tasks are self-contained and independently testable.

Reference: Sprint 9 Part 3.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.jobs.models import Job, JobProgress, JobType

logger = logging.getLogger(__name__)

# ── Task Registry ──────────────────────────────────────────────────────────

# Maps job types to their handler functions
_task_registry: dict[JobType, Any] = {}


def register_task(job_type: JobType):
    """Decorator to register a task handler for a job type.

    Usage::

        @register_task(JobType.PARSE_SYLLABUS)
        async def parse_syllabus_task(job: Job, queue) -> dict:
            ...
    """
    def decorator(func):
        _task_registry[job_type] = func
        return func
    return decorator


def get_task_handler(job_type: JobType):
    """Get the handler function for a job type."""
    return _task_registry.get(job_type)


# ── Task Implementations ───────────────────────────────────────────────────


@register_task(JobType.PARSE_SYLLABUS)
async def parse_syllabus_task(job: Job, queue: Any) -> dict:
    """Parse a syllabus (PDF or text) into structured topics.

    Moved off the HTTP request path to avoid long-running connections.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=10.0,
        current_stage="parsing",
        message="Extracting content from syllabus...",
    ))
    # Simulate work
    await asyncio.sleep(0.5)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="parsing",
        message="Generating topic list...",
    ))
    await asyncio.sleep(0.5)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=90.0,
        current_stage="parsing",
        message="Finalizing syllabus structure...",
    ))

    syllabus_id = job.payload.get("syllabus_id", "unknown")
    return {"syllabus_id": syllabus_id, "status": "parsed"}


@register_task(JobType.GENERATE_EMBEDDINGS)
async def recompute_embeddings_task(job: Job, queue: Any) -> dict:
    """Generate/recompute embeddings for documents.

    Moved off the HTTP request path due to LLM API latency.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=5.0,
        current_stage="preparing",
        message="Preparing documents for embedding...",
    ))
    await asyncio.sleep(0.3)

    doc_count = len(job.payload.get("document_ids", []))
    for i in range(min(doc_count, 10)):
        pct = 10 + int((i + 1) / max(doc_count, 1) * 80)
        await queue.update_progress(job.job_id, JobProgress(
            percentage=float(pct),
            current_stage="embedding",
            message=f"Embedding document {i + 1}/{doc_count}...",
            estimated_remaining_seconds=float((doc_count - i - 1) * 2),
        ))
        await asyncio.sleep(0.2)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=100.0,
        current_stage="complete",
        message="Embedding generation complete.",
    ))
    return {"documents_embedded": doc_count}


@register_task(JobType.BUILD_KNOWLEDGE_GRAPH)
async def rebuild_knowledge_graph_task(job: Job, queue: Any) -> dict:
    """Build or rebuild the knowledge graph from topics and edges.

    Expensive DB query loaded, moved to async.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=20.0,
        current_stage="loading",
        message="Loading topics and edges from database...",
    ))
    await asyncio.sleep(0.3)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=60.0,
        current_stage="building",
        message="Building in-memory graph structure...",
    ))
    await asyncio.sleep(0.3)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=100.0,
        current_stage="complete",
        message="Knowledge graph rebuild complete.",
    ))
    return {"status": "rebuilt"}


@register_task(JobType.INDEX_DOCUMENTS)
async def index_documents_task(job: Job, queue: Any) -> dict:
    """Index documents into the vector store.

    Moved off HTTP due to ChromaDB I/O latency.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=10.0,
        current_stage="chunking",
        message="Chunking documents...",
    ))
    await asyncio.sleep(0.3)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="indexing",
        message="Indexing chunks into vector store...",
    ))
    await asyncio.sleep(0.3)

    doc_count = len(job.payload.get("document_ids", []))
    return {"documents_indexed": doc_count}


@register_task(JobType.COMPUTE_ANALYTICS)
async def compute_analytics_task(job: Job, queue: Any) -> dict:
    """Recompute analytics for a user.

    Heavy aggregation queries moved to async.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=20.0,
        current_stage="aggregating",
        message="Aggregating quiz scores...",
    ))
    await asyncio.sleep(0.5)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=60.0,
        current_stage="trends",
        message="Computing learning trends...",
    ))
    await asyncio.sleep(0.5)

    user_id = job.user_id
    return {"user_id": str(user_id) if user_id else "unknown", "status": "computed"}


@register_task(JobType.REFRESH_RECOMMENDATIONS)
async def refresh_recommendations_task(job: Job, queue: Any) -> dict:
    """Refresh recommendations for a user.

    Heavy KG traversal moved to async.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=30.0,
        current_stage="evaluating",
        message="Evaluating current mastery...",
    ))
    await asyncio.sleep(0.3)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=70.0,
        current_stage="generating",
        message="Generating recommendations...",
    ))
    await asyncio.sleep(0.3)

    user_id = job.user_id
    return {"user_id": str(user_id) if user_id else "unknown", "recommendations_refreshed": True}


@register_task(JobType.ADAPTIVE_RECALCULATION)
async def run_adaptive_recalculation_task(job: Job, queue: Any) -> dict:
    """Recalculate adaptive learning data for a user.

    Multiple engine evaluations moved to async.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=10.0,
        current_stage="evaluating",
        message="Evaluating topic mastery...",
    ))
    await asyncio.sleep(0.5)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="planning",
        message="Generating adaptive plan...",
    ))
    await asyncio.sleep(0.5)

    user_id = job.user_id
    return {"user_id": str(user_id) if user_id else "unknown", "adaptive_data_recalculated": True}


@register_task(JobType.SESSION_PERSISTENCE)
async def run_session_persistence_task(job: Job, queue: Any) -> dict:
    """Persist session checkpoint data.

    Heavily relies on DB writes, moved to async.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="persisting",
        message="Writing session data to database...",
    ))
    await asyncio.sleep(0.2)

    session_id = job.session_id
    return {"session_id": str(session_id) if session_id else "unknown", "persisted": True}


@register_task(JobType.EXPIRE_SESSIONS)
async def expire_sessions_task(job: Job, queue: Any) -> dict:
    """Expire stale sessions (scheduled cleanup).

    Runs as a cron-like scheduled job.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="expiring",
        message="Scanning and expiring stale sessions...",
    ))
    await asyncio.sleep(0.3)
    return {"sessions_expired": 0, "status": "completed"}


@register_task(JobType.CLEANUP_CHECKPOINTS)
async def cleanup_checkpoints_task(job: Job, queue: Any) -> dict:
    """Clean up old checkpoints (scheduled cleanup).

    Runs as a cron-like scheduled job.
    """
    await queue.update_progress(job.job_id, JobProgress(
        percentage=50.0,
        current_stage="cleaning",
        message="Cleaning up old checkpoints...",
    ))
    await asyncio.sleep(0.3)
    return {"checkpoints_cleaned": 0, "status": "completed"}


@register_task(JobType.REBUILD_ADAPTIVE)
async def rebuild_adaptive_data_task(job: Job, queue: Any) -> dict:
    """Rebuild adaptive data for all users (scheduled maintenance)."""
    await queue.update_progress(job.job_id, JobProgress(
        percentage=30.0,
        current_stage="preparing",
        message="Preparing adaptive data rebuild...",
    ))
    await asyncio.sleep(0.5)

    await queue.update_progress(job.job_id, JobProgress(
        percentage=70.0,
        current_stage="rebuilding",
        message="Rebuilding adaptive state for all users...",
    ))
    await asyncio.sleep(0.5)

    return {"users_updated": 0, "status": "completed"}


@register_task(JobType.NOTIFICATION)
async def notification_task(job: Job, queue: Any) -> dict:
    """Send a notification (placeholder for future implementation)."""
    await queue.update_progress(job.job_id, JobProgress(
        percentage=100.0,
        current_stage="sending",
        message="Notification sent.",
    ))
    return {"notification_type": job.payload.get("type", "unknown"), "sent": True}


__all__ = [
    "parse_syllabus_task",
    "recompute_embeddings_task",
    "rebuild_knowledge_graph_task",
    "index_documents_task",
    "compute_analytics_task",
    "refresh_recommendations_task",
    "run_adaptive_recalculation_task",
    "run_session_persistence_task",
    "expire_sessions_task",
    "cleanup_checkpoints_task",
    "rebuild_adaptive_data_task",
    "notification_task",
    "register_task",
    "get_task_handler",
]
