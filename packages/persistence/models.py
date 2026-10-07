"""Phase 2 persistence models for curriculum upload and durable jobs."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.persistence.database import Base


def utc_now() -> datetime:
    """Return a timezone-aware timestamp suitable for a persistence default."""

    return datetime.now(UTC)


class Course(Base):
    """Minimal course aggregate needed to scope syllabus uploads."""

    __tablename__ = "courses"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StudentIdentity(Base):
    """Stable internal identity for an authenticated external subject."""

    __tablename__ = "student_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider_namespace", "external_subject",
            name="uq_student_identities_provider_subject",
        ),
        Index("ix_student_identities_external_subject", "external_subject"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    provider_namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CourseMember(Base):
    """Course membership used for upload authorization before user tables exist."""

    __tablename__ = "course_members"

    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="student")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Document(Base):
    """Validated uploaded document metadata; bytes live in MinIO."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        Index("ix_documents_course_created", "course_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DocumentVersion(Base):
    """Version metadata retained for later re-upload and parsing workflows."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    """Durable PostgreSQL-backed job record; Redis remains only a wake-up layer."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        Index(
            "ix_jobs_claim",
            "status",
            desc("priority"),
            "run_after",
            "created_at",
        ),
        Index(
            "ix_jobs_pending",
            "run_after",
            postgresql_where=text("status IN ('PENDING', 'RETRYING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lane: Mapped[str] = mapped_column(String(32), nullable=False, default="batch")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_job_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    result_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latest_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class JobProgressEvent(Base):
    """Append-only PostgreSQL event history for one durable job."""

    __tablename__ = "job_progress_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_progress_events_sequence"),
        UniqueConstraint("job_id", "idempotency_key", name="uq_job_progress_events_idempotency"),
        Index("ix_job_progress_events_replay", "job_id", "sequence"),
    )

    event_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningEventRecord(Base):
    """Append-only upload event record used for transactional traceability."""

    __tablename__ = "learning_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_learning_events_idempotency_key"),
        Index(
            "ix_learning_events_learner_occurred",
            "learner_identity_id", "occurred_at", "event_id",
        ),
        Index(
            "ix_learning_events_course_type_recorded",
            "course_id", "type", "recorded_at", "event_id",
        ),
        Index(
            "ix_learning_events_type_recorded",
            "type", "recorded_at", "event_id",
        ),
        Index(
            "ix_learning_events_actor_recorded",
            "actor_identity_id", "recorded_at", "event_id",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    learner_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    course_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    causation_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    event_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    versions: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
    )


class SelfReportAssertionRecord(Base):
    """Immutable, idempotent weak-prior assertion."""

    __tablename__ = "self_report_assertions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_self_report_assertions_idempotency"),
        UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_self_report_assertions_concept",
        ),
        Index(
            "ix_self_report_assertions_learner_concept",
            "learner_identity_id", "stable_concept_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    graph_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    alpha_delta: Mapped[float] = mapped_column(nullable=False, default=1.0)
    beta_delta: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MasteryQuestionVersion(Base):
    """Immutable question-version source context for mastery evidence."""

    __tablename__ = "mastery_question_versions"
    __table_args__ = (
        Index("ix_mastery_question_versions_course", "course_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    question_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    n_options: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tag_confidence: Mapped[float] = mapped_column(nullable=False)
    is_review: Mapped[bool] = mapped_column(nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    concept_roles: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MasteryAttempt(Base):
    """Immutable answer-attempt context copied into mastery evidence."""

    __tablename__ = "mastery_attempts"
    __table_args__ = (
        Index("ix_mastery_attempts_learner_occurred", "learner_identity_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    question_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("mastery_question_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_review: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MasteryEvidenceRecord(Base):
    """Immutable evidence ledger row with original snapshots and receipts."""

    __tablename__ = "mastery_evidence"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_mastery_evidence_idempotency"),
        Index(
            "uq_mastery_evidence_inferred_source_target",
            "inferred_source_attempt_id", "inferred_target_concept_id",
            unique=True, postgresql_where=text("kind = 'INFERRED'"),
        ),
        CheckConstraint(
            "(inferred_source_attempt_id IS NULL AND inferred_target_concept_id IS NULL "
            "AND inferred_source_evidence_id IS NULL) OR "
            "(kind = 'INFERRED' AND inferred_source_attempt_id IS NOT NULL "
            "AND inferred_target_concept_id IS NOT NULL "
            "AND inferred_source_evidence_id IS NOT NULL AND diagnostic_provenance IS NOT NULL)",
            name="ck_mastery_evidence_inference_source",
        ),
        Index("ix_mastery_evidence_learner_occurred", "learner_identity_id", "occurred_at"),
        Index("ix_mastery_evidence_course_concept", "course_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    question_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    question_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("mastery_question_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("mastery_attempts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    correct: Mapped[float] = mapped_column(nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    n_options: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False)
    grader_level: Mapped[str] = mapped_column(String(32), nullable=False)
    grader_confidence: Mapped[float] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_review: Mapped[bool] = mapped_column(nullable=False)
    tag_confidence: Mapped[float] = mapped_column(nullable=False)
    concept_roles: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
    )
    weight_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
    )
    diagnostic_provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    inferred_source_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("mastery_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    inferred_target_concept_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    inferred_source_evidence_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("mastery_evidence.id", ondelete="RESTRICT"),
        nullable=True,
    )


class MasteryContributionRecord(Base):
    """Immutable per-concept contribution ledger for one evidence item."""

    __tablename__ = "mastery_contributions"
    __table_args__ = (
        UniqueConstraint(
            "projection_id", "evidence_id", "stable_concept_id",
            name="uq_mastery_contribution_projection_concept",
        ),
        Index("ix_mastery_contributions_concept", "learner_identity_id", "stable_concept_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    projection_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("mastery_projection_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("mastery_evidence.id", ondelete="CASCADE"),
        nullable=False,
    )
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    alpha_delta: Mapped[float] = mapped_column(nullable=False)
    beta_delta: Mapped[float] = mapped_column(nullable=False)
    applied: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
class MasteryProjectionRevision(Base):
    """Immutable materialized projection revision for one concept."""

    __tablename__ = "mastery_projection_revisions"
    __table_args__ = (
        UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id", "projection_version",
            name="uq_mastery_projection_revision_version",
        ),
        Index(
            "ix_mastery_projection_revisions_key_created",
            "learner_identity_id", "course_id", "stable_concept_id", "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replayed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_set_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_evidence_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    alpha: Mapped[float] = mapped_column(nullable=False)
    beta: Mapped[float] = mapped_column(nullable=False)
    n_eff: Mapped[float] = mapped_column(nullable=False)
    mastery: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    n_direct: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_direct_question_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
    )
    review_successes: Mapped[int] = mapped_column(Integer, nullable=False)
    review_rung: Mapped[int] = mapped_column(Integer, nullable=False)
    last_successful_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_successful_review_evidence_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    last_successful_review_event_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    rebuild_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MasteryProjectionHead(Base):
    """Current projection pointer; immutable revisions remain the history."""

    __tablename__ = "mastery_projection_heads"
    __table_args__ = (
        UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_mastery_projection_head_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    current_projection_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey(
            "mastery_projection_revisions.id", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    current_projection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReviewSchedule(Base):
    """Current durable review schedule; history is retained by projections/events."""

    __tablename__ = "review_schedule"
    __table_args__ = (
        UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_review_schedule_concept",
        ),
        UniqueConstraint("schedule_cycle", name="uq_review_schedule_cycle"),
        Index(
            "ix_review_schedule_due",
            "learner_identity_id", "course_id", "status", "due_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    graph_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    review_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    review_rung: Mapped[int] = mapped_column(Integer, nullable=False)
    review_successes: Mapped[int] = mapped_column(Integer, nullable=False)
    first_concept_event_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    first_concept_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_successful_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_successful_review_evidence_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    last_successful_review_event_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    projection_revision_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey(
            "mastery_projection_revisions.id", ondelete="RESTRICT",
        ), nullable=True,
    )
    evidence_set_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schedule_cycle: Mapped[str] = mapped_column(String(64), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list,
    )
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list,
    )
    supporting_event_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
    )


class LearningEventConceptAssociation(Base):
    """Normalized concept association for a v2 concept-impact event."""

    __tablename__ = "learning_event_concepts"
    __table_args__ = (
        Index(
            "ix_learning_event_concepts_learner_concept_occurred",
            "learner_identity_id", "stable_concept_id", "occurred_at", "event_id",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("learning_events.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True,
    )
    learner_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    concept_impact: Mapped[str] = mapped_column(String(32), nullable=False)
    source_evidence_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    source_attempt_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )


class CurriculumReview(Base):
    """PostgreSQL source-of-truth lifecycle pointer for one immutable generated draft."""

    __tablename__ = "curriculum_reviews"
    __table_args__ = (
        UniqueConstraint("draft_job_id", name="uq_curriculum_reviews_draft_job"),
        Index("ix_curriculum_reviews_course", "course_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("courses.id"))
    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("documents.id"),
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("document_versions.id"),
    )
    draft_job_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("jobs.id"))
    original_draft_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_revision_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_revision_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CurriculumRevision(Base):
    """Immutable revision metadata; content is in a separate MinIO JSON artifact."""

    __tablename__ = "curriculum_revisions"
    __table_args__ = (
        UniqueConstraint("review_id", "revision_number", name="uq_curriculum_revisions_number"),
        UniqueConstraint("idempotency_key", name="uq_curriculum_revisions_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    review_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_reviews.id", ondelete="CASCADE"),
    )
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_revisions.id", ondelete="SET NULL"),
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CurriculumGraphVersion(Base):
    """Immutable operational graph snapshot metadata."""

    __tablename__ = "curriculum_graph_versions"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_revision_id", "version_number",
            name="uq_curriculum_graph_versions_revision_number",
        ),
        Index(
            "ix_curriculum_graph_versions_course_created",
            "course_id", "created_at", "id",
        ),
        Index(
            "ix_curriculum_graph_versions_revision_status",
            "curriculum_revision_id", "status", "version_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False,
    )
    curriculum_revision_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_graph_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    build_job_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    graph_source: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    curriculum_source: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
    )
    created_by_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_by_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CurriculumGraphNode(Base):
    """Normalized graph node row; stable_node_id survives graph versions."""

    __tablename__ = "curriculum_graph_nodes"
    __table_args__ = (
        UniqueConstraint("graph_id", "stable_node_id", name="uq_graph_nodes_stable_id"),
        Index("ix_graph_nodes_graph_type", "graph_id", "node_type"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    graph_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stable_node_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_stable_node_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    curriculum_element_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True,
    )
    curriculum_element: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)


class CurriculumGraphConcept(Base):
    """Normalized concept definition for one immutable graph version."""

    __tablename__ = "curriculum_graph_concepts"
    __table_args__ = (
        UniqueConstraint("graph_id", "stable_concept_id", name="uq_graph_concepts_stable_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    graph_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stable_concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    derived_from_topic_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))


class CurriculumGraphMapping(Base):
    """Normalized topic-to-concept mapping for one graph version."""

    __tablename__ = "curriculum_graph_mappings"
    __table_args__ = (
        UniqueConstraint("graph_id", "mapping_id", name="uq_graph_mappings_id"),
        UniqueConstraint("graph_id", "topic_id", "concept_id", name="uq_graph_mapping_pair"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    graph_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mapping_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    topic_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    concept_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    mapping_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)


class CurriculumGraphEdge(Base):
    """Normalized directed relationship with independent review metadata."""

    __tablename__ = "curriculum_graph_edges"
    __table_args__ = (
        UniqueConstraint("graph_id", "edge_id", name="uq_graph_edges_id"),
        Index(
            "ix_graph_edges_confirmed_prerequisites",
            "graph_id", "source_node_id", "target_node_id",
            postgresql_where=text("edge_type = 'PREREQUISITE_OF' AND status = 'CONFIRMED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    graph_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_graph_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_node_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    target_node_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed_by_identity_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CurriculumSuccessorVersion(Base):
    """Explicit link between immutable parent and successor review revisions."""

    __tablename__ = "curriculum_successor_versions"
    __table_args__ = (
        UniqueConstraint(
            "parent_revision_id", "successor_review_id", "successor_revision_id",
            name="uq_curriculum_successors_parent_successor",
        ),
        Index("ix_curriculum_successors_course", "course_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False,
    )
    parent_review_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_reviews.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_revision_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    successor_review_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_reviews.id", ondelete="RESTRICT"),
        nullable=False,
    )
    successor_revision_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("curriculum_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DECLARED")
    created_by_identity_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("student_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lineage: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
