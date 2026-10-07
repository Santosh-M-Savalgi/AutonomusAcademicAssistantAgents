"""Stage 2 storage definitions, separate from runtime repository operations."""

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.domain.enums import PlannerAction
from packages.domain.runtime import (
    SESSION_TRANSITIONS,
    DiagnosticRunState,
    ExecutionState,
    FrameState,
    ReservationState,
    SessionState,
    SourceKind,
)
from packages.persistence.database import Base
from packages.persistence.models import utc_now


def _choices(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(repr(str(value)) for value in sorted(values))})"


class LearningSessionRecord(Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        UniqueConstraint("id", "learner_identity_id", "course_id", name="uq_sessions_scope"),
        CheckConstraint(_choices("state", SessionState), name="ck_sessions_state"),
        CheckConstraint("version >= 1", name="ck_sessions_version"),
        CheckConstraint("updated_at >= created_at", name="ck_sessions_times"),
        CheckConstraint(
            "(state = 'COMPLETE') = (completed_at IS NOT NULL) AND "
            "(completed_at IS NULL OR completed_at BETWEEN created_at AND updated_at)",
            name="ck_sessions_completion",
        ),
        CheckConstraint(
            "current_topic_id IS NULL OR graph_version_id IS NOT NULL",
            name="ck_sessions_position",
        ),
        ForeignKeyConstraint(
            ["graph_version_id", "current_topic_id"],
            ["curriculum_graph_nodes.graph_id", "curriculum_graph_nodes.stable_node_id"],
            ondelete="RESTRICT", name="fk_sessions_topic",
        ),
        ForeignKeyConstraint(
            ["current_plan_version_id", "id"],
            ["learning_plan_versions.id", "learning_plan_versions.session_id"],
            ondelete="RESTRICT", use_alter=True, name="fk_sessions_plan_head",
        ),
        ForeignKeyConstraint(
            ["active_frame_id", "id"], ["remediation_frames.id", "remediation_frames.session_id"],
            ondelete="RESTRICT", use_alter=True, name="fk_sessions_frame_head",
        ),
        Index("ix_sessions_learner_course_state", "learner_identity_id", "course_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    learner_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_identities.id", ondelete="RESTRICT"), nullable=False,
    )
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"), nullable=True,
    )
    current_topic_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    current_plan_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True,
    )
    active_frame_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    last_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionTransitionRecord(Base):
    __tablename__ = "learning_session_transitions"
    __table_args__ = (
        UniqueConstraint("session_id", "to_version", name="uq_session_transitions_version"),
        CheckConstraint(
            "from_version >= 1 AND to_version = from_version + 1",
            name="ck_session_transitions_version",
        ),
        CheckConstraint(
            " OR ".join(
                f"(from_state = '{state}' AND {_choices('to_state', successors)})"
                for state, successors in SESSION_TRANSITIONS.items() if successors
            ), name="ck_session_transitions_legal",
        ),
        CheckConstraint(
            "execution_id IS NULL OR plan_version_id IS NOT NULL",
            name="ck_session_transitions_execution_plan",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"), primary_key=True,
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), primary_key=True,
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plan_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_plan_versions.id", ondelete="RESTRICT"), nullable=True,
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_execution_receipts.id", ondelete="RESTRICT"), nullable=True,
    )


class LearningPlanRecord(Base):
    __tablename__ = "learning_plans"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_plans_session"),
        UniqueConstraint("id", "session_id", name="uq_plans_scope"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningPlanVersionRecord(Base):
    __tablename__ = "learning_plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", name="uq_plan_versions_number"),
        UniqueConstraint("session_id", "trigger_id", name="uq_plan_versions_trigger"),
        UniqueConstraint("id", "session_id", name="uq_plan_versions_session"),
        UniqueConstraint("id", "plan_id", name="uq_plan_versions_plan"),
        UniqueConstraint(
            "id", "session_id", "action", "target_id", "policy_outcome", "session_version",
            name="uq_plan_versions_execution_context",
        ),
        ForeignKeyConstraint(
            ["plan_id", "session_id"], ["learning_plans.id", "learning_plans.session_id"],
            name="fk_plan_versions_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_version_id", "plan_id"],
            ["learning_plan_versions.id", "learning_plan_versions.plan_id"],
            name="fk_plan_versions_predecessor", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["frame_id", "session_id"], ["remediation_frames.id", "remediation_frames.session_id"],
            name="fk_plan_versions_frame", ondelete="RESTRICT", use_alter=True,
        ),
        CheckConstraint("version >= 1 AND session_version >= 1", name="ck_plan_versions_versions"),
        CheckConstraint(
            "(version = 1) = (supersedes_version_id IS NULL) AND "
            "(supersedes_version_id IS NULL OR supersedes_version_id <> id)",
            name="ck_plan_versions_predecessor",
        ),
        CheckConstraint(
            "(frame_id IS NULL) = (frame_version IS NULL) AND "
            "(frame_version IS NULL OR frame_version >= 1)", name="ck_plan_versions_frame",
        ),
        CheckConstraint(
            "(graph_version_id IS NULL) = (curriculum_revision_id IS NULL)",
            name="ck_plan_versions_graph",
        ),
        CheckConstraint(_choices("source_kind", SourceKind), name="ck_plan_versions_source"),
        CheckConstraint(_choices("action", PlannerAction), name="ck_plan_versions_action"),
        CheckConstraint(
            "policy_outcome IN ('ALLOW','REQUIRE_CONFIRMATION','BLOCK')",
            name="ck_plan_versions_policy_outcome",
        ),
        CheckConstraint(
            "encode(sha256(snapshot_bytes), 'hex') = snapshot_digest AND "
            "encode(sha256(decision_bytes), 'hex') = decision_digest",
            name="ck_plan_versions_digests",
        ),
        CheckConstraint(
            "((convert_from(decision_bytes, 'UTF8')::jsonb ->> 'action') = action AND "
            "(convert_from(decision_bytes, 'UTF8')::jsonb ->> 'target_id') = target_id AND "
            "(convert_from(decision_bytes, 'UTF8')::jsonb ->> 'policy_outcome') = "
            "policy_outcome AND "
            "(convert_from(decision_bytes, 'UTF8')::jsonb ->> 'plan_version') = version::text AND "
            "(convert_from(decision_bytes, 'UTF8')::jsonb ->> 'planner_policy_version') = "
            "planner_policy_version) IS TRUE", name="ck_plan_versions_decision_context",
        ),
        CheckConstraint(
            "length(mastery_policy_version) > 0 AND length(planner_policy_version) > 0 "
            "AND schema_version = 'runtime-v1'", name="ck_plan_versions_policy_versions",
        ),
        Index("ix_plan_versions_session_created", "session_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=False,
    )
    session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    frame_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"), nullable=True,
    )
    curriculum_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("curriculum_revisions.id", ondelete="RESTRICT"), nullable=True,
    )
    snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    snapshot_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    mastery_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    planner_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source_snapshot_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExecutionReceiptRecord(Base):
    __tablename__ = "learning_execution_receipts"
    __table_args__ = (
        UniqueConstraint("plan_version_id", name="uq_execution_receipts_plan_version"),
        UniqueConstraint("id", "session_id", name="uq_execution_receipts_session"),
        ForeignKeyConstraint(
            ["plan_version_id", "session_id", "action", "target_id", "policy_outcome",
             "session_version"],
            [f"learning_plan_versions.{column}" for column in (
                "id", "session_id", "action", "target_id", "policy_outcome", "session_version",
            )], name="fk_execution_receipts_plan_context", ondelete="RESTRICT",
        ),
        CheckConstraint(_choices("state", ExecutionState), name="ck_execution_receipts_state"),
        CheckConstraint("version >= 1", name="ck_execution_receipts_version"),
        CheckConstraint(
            "(state IN ('COMPLETED','BLOCKED','STALE','SUPERSEDED','FAILED')) = "
            "(completed_at IS NOT NULL) AND (completed_at IS NOT NULL) = "
            "(result_bytes IS NOT NULL) AND (completed_at IS NULL OR completed_at >= created_at)",
            name="ck_execution_receipts_completion",
        ),
        CheckConstraint(
            "jsonb_typeof(child_job_ids) = 'array' AND jsonb_typeof(emitted_event_ids) = 'array'",
            name="ck_execution_receipts_children",
        ),
        CheckConstraint(
            "policy_outcome <> 'BLOCK' OR (state IN ('BLOCKED','STALE','SUPERSEDED') "
            "AND child_job_ids = '[]'::jsonb)", name="ck_execution_receipts_block",
        ),
        CheckConstraint(
            "policy_outcome <> 'REQUIRE_CONFIRMATION' OR confirmation_event_id IS NOT NULL "
            "OR (state IN ('AWAITING_CONFIRMATION','BLOCKED','STALE','SUPERSEDED','FAILED') "
            "AND child_job_ids = '[]'::jsonb)", name="ck_execution_receipts_confirmation",
        ),
        Index("ix_execution_receipts_session_state", "session_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    plan_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmation_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=True,
    )
    child_job_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    emitted_event_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RemediationFrameRecord(Base):
    __tablename__ = "remediation_frames"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_remediation_frames_session"),
        UniqueConstraint("created_by_execution_id", name="uq_remediation_frames_execution"),
        UniqueConstraint("returned_by_execution_id", name="uq_remediation_frames_return_execution"),
        ForeignKeyConstraint(
            ["created_by_execution_id", "session_id"],
            ["learning_execution_receipts.id", "learning_execution_receipts.session_id"],
            name="fk_remediation_frames_execution", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_frame_id", "session_id"],
            ["remediation_frames.id", "remediation_frames.session_id"],
            name="fk_remediation_frames_parent", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["returned_by_execution_id", "session_id"],
            ["learning_execution_receipts.id", "learning_execution_receipts.session_id"],
            name="fk_remediation_frames_return_execution", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["graph_version_id", "target_concept_id"],
            ["curriculum_graph_concepts.graph_id", "curriculum_graph_concepts.stable_concept_id"],
            name="fk_remediation_frames_target", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["graph_version_id", "return_to_topic_id"],
            ["curriculum_graph_nodes.graph_id", "curriculum_graph_nodes.stable_node_id"],
            name="fk_remediation_frames_return", ondelete="RESTRICT",
        ),
        CheckConstraint(_choices("state", FrameState), name="ck_remediation_frames_state"),
        CheckConstraint(
            "version >= 1 AND depth >= 1 AND rung >= 0 AND attempt_count >= 0 AND "
            "max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_remediation_frames_bounds",
        ),
        CheckConstraint(
            "baseline_mastery BETWEEN 0 AND 1 AND latest_mastery BETWEEN 0 AND 1 AND "
            "min_progress_delta BETWEEN 0 AND 1", name="ck_remediation_frames_progress",
        ),
        CheckConstraint(
            "(depth = 1) = (parent_frame_id IS NULL) AND "
            "(parent_frame_id IS NULL OR parent_frame_id <> id)",
            name="ck_remediation_frames_parent",
        ),
        CheckConstraint(
            "(state = 'RETURNED') = (returned_at IS NOT NULL) AND "
            "(returned_at IS NOT NULL) = (returned_by_execution_id IS NOT NULL)",
            name="ck_remediation_frames_return",
        ),
        Index(
            "uq_remediation_frames_active_depth", "session_id", "depth", unique=True,
            postgresql_where=text("state IN ('ACTIVE', 'COMPLETE')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="RESTRICT"),
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    target_concept_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    return_to_topic_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_by_execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    parent_frame_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rung: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    guard_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    min_progress_delta: Mapped[float] = mapped_column(nullable=False)
    baseline_mastery: Mapped[float] = mapped_column(nullable=False)
    latest_mastery: Mapped[float] = mapped_column(nullable=False)
    last_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    returned_by_execution_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True,
    )
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FrameAttemptRecord(Base):
    __tablename__ = "remediation_frame_attempts"
    __table_args__ = (
        UniqueConstraint("source_attempt_id", name="uq_frame_attempts_source"),
        UniqueConstraint("frame_id", "event_id", name="uq_frame_attempts_event"),
        CheckConstraint(
            "rung >= 0 AND observed_mastery BETWEEN 0 AND 1", name="ck_frame_attempts_bounds",
        ),
    )

    frame_id: Mapped[UUID] = mapped_column(
        ForeignKey("remediation_frames.id", ondelete="RESTRICT"), primary_key=True,
    )
    source_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("mastery_attempts.id", ondelete="RESTRICT"), primary_key=True,
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    rung: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_mastery: Mapped[float] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiagnosticRunRecord(Base):
    __tablename__ = "diagnostic_runs"
    __table_args__ = (
        UniqueConstraint(
            "id", "session_id", "graph_version_id", "item_budget",
            name="uq_diagnostic_runs_context",
        ),
        UniqueConstraint(
            "session_id", "source_kind", "source_id", name="uq_diagnostic_runs_source",
        ),
        ForeignKeyConstraint(
            ["session_id", "learner_identity_id", "course_id"],
            ["learning_sessions.id", "learning_sessions.learner_identity_id",
             "learning_sessions.course_id"], name="fk_diagnostic_runs_session", ondelete="RESTRICT",
        ),
        CheckConstraint(_choices("state", DiagnosticRunState), name="ck_diagnostic_runs_state"),
        CheckConstraint(_choices("source_kind", SourceKind), name="ck_diagnostic_runs_source"),
        CheckConstraint(
            "version >= 1 AND item_budget BETWEEN 0 AND 12", name="ck_diagnostic_runs_bounds",
        ),
        CheckConstraint(
            "(state <> 'OPEN') = (completed_at IS NOT NULL) AND "
            "(completed_at IS NOT NULL) = (completion_event_id IS NOT NULL) AND "
            "(completed_at IS NULL OR completed_at >= created_at)",
            name="ck_diagnostic_runs_completion",
        ),
        Index("ix_diagnostic_runs_learner_state", "learner_identity_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    learner_identity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    course_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_graph_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    diagnostic_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    item_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"),
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=True,
    )


class DiagnosticReservationRecord(Base):
    __tablename__ = "diagnostic_reservations"
    __table_args__ = (
        UniqueConstraint("diagnostic_run_id", "slot", name="uq_diagnostic_reservations_slot"),
        UniqueConstraint(
            "diagnostic_run_id", "question_version_id", name="uq_diagnostic_reservations_question",
        ),
        UniqueConstraint("source_attempt_id", name="uq_diagnostic_reservations_attempt"),
        UniqueConstraint("source_evidence_id", name="uq_diagnostic_reservations_evidence"),
        ForeignKeyConstraint(
            ["diagnostic_run_id", "session_id", "graph_version_id", "item_budget"],
            [f"diagnostic_runs.{column}" for column in (
                "id", "session_id", "graph_version_id", "item_budget",
            )], name="fk_diagnostic_reservations_run", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["execution_id", "session_id"],
            ["learning_execution_receipts.id", "learning_execution_receipts.session_id"],
            name="fk_diagnostic_reservations_execution", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["graph_version_id", "target_concept_id"],
            ["curriculum_graph_concepts.graph_id", "curriculum_graph_concepts.stable_concept_id"],
            name="fk_diagnostic_reservations_target", ondelete="RESTRICT",
        ),
        CheckConstraint(
            _choices("state", ReservationState), name="ck_diagnostic_reservations_state",
        ),
        CheckConstraint(
            "version >= 1 AND slot BETWEEN 1 AND item_budget",
            name="ck_diagnostic_reservations_bounds",
        ),
        CheckConstraint(
            "(state <> 'RESERVED') = (source_attempt_id IS NOT NULL) AND "
            "(source_attempt_id IS NOT NULL) = (attempted_at IS NOT NULL) AND "
            "(attempted_at IS NULL OR attempted_at >= reserved_at)",
            name="ck_diagnostic_reservations_attempt",
        ),
        CheckConstraint(
            "(state = 'ASSESSED') = (source_evidence_id IS NOT NULL) AND "
            "(source_evidence_id IS NOT NULL) = (completion_event_id IS NOT NULL) AND "
            "(completion_event_id IS NOT NULL) = (assessed_at IS NOT NULL) AND "
            "jsonb_typeof(assessed_concept_ids) = 'array' AND "
            "(state = 'ASSESSED') = (jsonb_array_length(assessed_concept_ids) > 0) AND "
            "(assessed_at IS NULL OR assessed_at >= attempted_at)",
            name="ck_diagnostic_reservations_assessment",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    diagnostic_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    graph_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    item_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("mastery_question_versions.id", ondelete="RESTRICT"),
    )
    target_concept_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mastery_attempts.id", ondelete="RESTRICT"), nullable=True,
    )
    source_evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("mastery_evidence.id", ondelete="RESTRICT"), nullable=True,
    )
    completion_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("learning_events.event_id", ondelete="RESTRICT"), nullable=True,
    )
    assessed_concept_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiagnosticInferenceLinkRecord(Base):
    """Bind an existing immutable inferred ledger identity to its reservation."""

    __tablename__ = "diagnostic_inference_links"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id", "target_concept_id", name="uq_diagnostic_inference_links_target",
        ),
    )

    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("mastery_evidence.id", ondelete="RESTRICT"), primary_key=True,
    )
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("diagnostic_reservations.id", ondelete="RESTRICT"), nullable=False,
    )
    target_concept_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


RUNTIME_TABLES: tuple[type[Base], ...] = (
    LearningSessionRecord, SessionTransitionRecord, LearningPlanRecord,
    LearningPlanVersionRecord, ExecutionReceiptRecord, RemediationFrameRecord,
    FrameAttemptRecord, DiagnosticRunRecord, DiagnosticReservationRecord,
    DiagnosticInferenceLinkRecord,
)
