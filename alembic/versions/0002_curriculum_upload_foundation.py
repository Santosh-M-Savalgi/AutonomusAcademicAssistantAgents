"""Add course-scoped documents, learning events, and durable jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_curriculum_upload"
down_revision: str | None = "0001_runtime_foundation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create the non-destructive Phase 2 upload foundation tables."""

    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "courses",
        sa.Column("id", uuid, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "course_members",
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("course_id", "subject"),
    )
    op.create_table(
        "documents",
        sa.Column("id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
    )
    op.create_index("ix_documents_course_created", "documents", ["course_id", "created_at"])
    op.create_table(
        "document_versions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("document_id", uuid, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", uuid, nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", timestamp, nullable=True),
        sa.Column("heartbeat_at", timestamp, nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("parent_job_id", uuid, nullable=True),
        sa.Column("result_ref", sa.String(length=512), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["parent_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        ["status", sa.text("priority DESC"), "run_after", "created_at"],
    )
    op.create_index(
        "ix_jobs_pending",
        "jobs",
        ["run_after"],
        postgresql_where=sa.text("status IN ('PENDING', 'RETRYING')"),
    )
    op.create_table(
        "learning_events",
        sa.Column("event_id", uuid, nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("causation_id", uuid, nullable=True),
        sa.Column("correlation_id", uuid, nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    """Remove only the Sprint 2.1 tables when explicitly downgraded."""

    op.drop_table("learning_events")
    op.drop_index("ix_jobs_pending", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_course_created", table_name="documents")
    op.drop_table("documents")
    op.drop_table("course_members")
    op.drop_table("courses")
