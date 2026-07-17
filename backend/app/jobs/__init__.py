"""Background Jobs & Asynchronous Processing (Sprint 9).

Provides durable background job execution with configurable retries,
progress tracking, scheduling, and monitoring.

Architecture:
    models.py    — domain dataclasses (Job, JobStatus, etc.)
    schemas.py   — Pydantic API schemas
    queue.py     — Redis-based durable job queue
    worker.py    — background worker process with heartbeat and lifecycle
    scheduler.py — scheduled job manager for recurring tasks
    tasks.py     — task implementations (moved from HTTP path)
    service.py   — high-level orchestration for API layer

Integrates with existing Redis and Postgres infrastructure.
"""

from __future__ import annotations

from app.jobs.models import (
    Job,
    JobPriority,
    JobProgress,
    JobStatus,
    JobType,
    RetryPolicy,
)
from app.jobs.queue import JobQueue
from app.jobs.scheduler import JobScheduler
from app.jobs.service import JobService
from app.jobs.tasks import (
    compute_analytics_task,
    expire_sessions_task,
    parse_syllabus_task,
    rebuild_adaptive_data_task,
    rebuild_knowledge_graph_task,
    recompute_embeddings_task,
    refresh_recommendations_task,
    cleanup_checkpoints_task,
    index_documents_task,
    run_adaptive_recalculation_task,
    run_session_persistence_task,
)
from app.jobs.worker import WorkerPool

__all__ = [
    # Domain
    "Job",
    "JobStatus",
    "JobType",
    "JobPriority",
    "JobProgress",
    "RetryPolicy",
    # Queue
    "JobQueue",
    # Worker
    "WorkerPool",
    # Scheduler
    "JobScheduler",
    # Service
    "JobService",
    # Tasks
    "parse_syllabus_task",
    "recompute_embeddings_task",
    "rebuild_knowledge_graph_task",
    "index_documents_task",
    "compute_analytics_task",
    "compute_recommendations_task",
    "expire_sessions_task",
    "cleanup_checkpoints_task",
    "refresh_recommendations_task",
    "rebuild_adaptive_data_task",
    "run_adaptive_recalculation_task",
    "run_session_persistence_task",
]
