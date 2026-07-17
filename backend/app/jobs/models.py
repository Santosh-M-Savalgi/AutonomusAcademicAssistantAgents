"""Background Jobs — domain dataclasses and enums.

All types are pure dataclasses used internally by the job system.
No I/O dependencies.

Reference: Sprint 9 Parts 1, 2, 4, 6.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime


class JobStatus(str, enum.Enum):
    """Durable job states (Part 2)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class JobType(str, enum.Enum):
    """Supported job types for async execution (Part 3)."""

    PARSE_SYLLABUS = "parse_syllabus"
    GENERATE_EMBEDDINGS = "generate_embeddings"
    BUILD_KNOWLEDGE_GRAPH = "build_knowledge_graph"
    INDEX_DOCUMENTS = "index_documents"
    COMPUTE_ANALYTICS = "compute_analytics"
    REFRESH_RECOMMENDATIONS = "refresh_recommendations"
    ADAPTIVE_RECALCULATION = "adaptive_recalculation"
    SESSION_PERSISTENCE = "session_persistence"
    EXPIRE_SESSIONS = "expire_sessions"
    CLEANUP_CHECKPOINTS = "cleanup_checkpoints"
    REBUILD_ADAPTIVE = "rebuild_adaptive"
    NOTIFICATION = "notification"


class JobPriority(str, enum.Enum):
    """Job priority levels.

    Higher-priority jobs are dequeued first.
    """

    CRITICAL = "critical"
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"

    def sort_order(self) -> int:
        return {
            "critical": 0,
            "high": 1,
            "default": 2,
            "low": 3,
        }[self.value]


@dataclass
class JobProgress:
    """Fine-grained progress for a running job (Part 6)."""

    percentage: float = 0.0            # 0.0–100.0
    current_stage: str = "initializing"
    message: str = ""
    estimated_remaining_seconds: float | None = None


@dataclass
class RetryPolicy:
    """Configurable retry policy (Part 4).

    Controls how many times a failed job is retried and with what backoff.
    """

    max_retries: int = 3
    base_delay_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 3600.0  # 1 hour cap
    permanent_failure_threshold: int = 5

    def delay_for_attempt(self, attempt: int) -> float:
        """Compute exponential backoff delay for a given attempt number.

        Args:
            attempt: 0-based retry attempt number.

        Returns:
            Delay in seconds.
        """
        delay = self.base_delay_seconds * (self.backoff_multiplier ** attempt)
        return min(delay, self.max_delay_seconds)


@dataclass
class Job:
    """A durable background job (Part 2).

    Every job has a unique ID, tracks its lifecycle state, and carries
    the metadata needed for execution, retry, and monitoring.
    """

    job_id: uuid.UUID = field(default_factory=uuid.uuid4)
    job_type: JobType = JobType.NOTIFICATION
    status: JobStatus = JobStatus.QUEUED
    priority: JobPriority = JobPriority.DEFAULT

    # Ownership
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    # Timeline
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Retry
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    backoff_until: datetime | None = None

    # Progress
    progress: JobProgress = field(default_factory=JobProgress)

    # Payload
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # Result
    result: dict | None = None

    # Worker
    worker_id: str | None = None
    heartbeat_at: datetime | None = None

    def is_terminal(self) -> bool:
        """Check if the job is in a terminal state."""
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )

    def should_retry(self) -> bool:
        """Check if the job should be retried based on current state.

        Returns:
            True if the job has failed but hasn't exceeded max retries.
        """
        if self.status == JobStatus.FAILED:
            return self.retry_count < self.max_retries
        return False
