"""Additive Block A source facts and retry journals; no hidden transaction owner."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.persistence.database import Base


class RuntimeOperationRecord(Base):
    __tablename__ = "runtime_operation_receipts"
    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_identities.id", ondelete="RESTRICT"),
    )
    request_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    result_bytes: Mapped[bytes] = mapped_column(LargeBinary)


class TopicWindowRecord(Base):
    __tablename__ = "runtime_topic_windows"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_runtime_windows_version"),
        Index("uq_runtime_windows_open", "session_id", unique=True,
              postgresql_where=text("closed_at IS NULL")),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"),
    )
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value_bytes: Mapped[bytes] = mapped_column(LargeBinary)


class RuntimeDirectiveRecord(Base):
    __tablename__ = "runtime_directives"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_runtime_directives_version"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"),
    )
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    value_bytes: Mapped[bytes] = mapped_column(LargeBinary)


class AssessmentBatchRecord(Base):
    __tablename__ = "runtime_assessment_batches"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_id: Mapped[UUID] = mapped_column(
        ForeignKey("runtime_topic_windows.id", ondelete="RESTRICT"),
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), unique=True,
    )
    value_bytes: Mapped[bytes] = mapped_column(LargeBinary)


class WindowEvidenceRecord(Base):
    __tablename__ = "runtime_window_evidence"
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("mastery_evidence.id", ondelete="RESTRICT"), primary_key=True,
    )
    window_id: Mapped[UUID] = mapped_column(
        ForeignKey("runtime_topic_windows.id", ondelete="RESTRICT"),
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("mastery_attempts.id", ondelete="RESTRICT"), unique=True,
    )
    value_bytes: Mapped[bytes] = mapped_column(LargeBinary)


class WorkerExecutionLinkRecord(Base):
    __tablename__ = "runtime_worker_execution_links"
    __table_args__ = (CheckConstraint("attempt >= 1", name="ck_runtime_worker_link_attempt"),)
    worker_attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_execution_receipts.id", ondelete="RESTRICT"), primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    attempt: Mapped[int] = mapped_column(Integer)


class RuntimeTriggerRecord(Base):
    __tablename__ = "runtime_triggers"
    __table_args__ = (
        CheckConstraint("status IN ('EVIDENCE_ONLY','REJECTED','BLOCKED','DEFERRED','ADMITTED')",
                        name="ck_runtime_triggers_status"),
        Index("ix_runtime_triggers_learner_status", "learner_id", "status", "eligible_after"),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_identities.id", ondelete="RESTRICT"),
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"),
    )
    kind: Mapped[str] = mapped_column(String(64))
    source_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    request_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    original_result_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(32))
    eligible_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeTriggerPlanLinkRecord(Base):
    """Immutable association proving which plan consumed an admitted trigger."""

    __tablename__ = "runtime_trigger_plan_links"
    trigger_id: Mapped[UUID] = mapped_column(
        ForeignKey("runtime_triggers.id", ondelete="RESTRICT"), primary_key=True,
    )
    plan_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_plan_versions.id", ondelete="RESTRICT"), unique=True,
    )


BLOCK_A_TABLES = (
    RuntimeOperationRecord, TopicWindowRecord, RuntimeDirectiveRecord, AssessmentBatchRecord,
    WindowEvidenceRecord, WorkerExecutionLinkRecord, RuntimeTriggerRecord,
)

BLOCK_B_TABLES = (RuntimeTriggerPlanLinkRecord,)
