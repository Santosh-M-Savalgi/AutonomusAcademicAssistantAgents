"""Add additive PostgreSQL metadata for curriculum review revisions and confirmation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_curriculum_review"
down_revision = "0003_curriculum_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "curriculum_reviews",
        sa.Column("id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("document_id", uuid, nullable=False),
        sa.Column("document_version_id", uuid, nullable=False),
        sa.Column("draft_job_id", uuid, nullable=False),
        sa.Column("original_draft_ref", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_revision_id", uuid, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("confirmed_revision_id", uuid, nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_job_id", name="uq_curriculum_reviews_draft_job"),
    )
    op.create_index("ix_curriculum_reviews_course", "curriculum_reviews", ["course_id", "created_at"])
    op.create_table(
        "curriculum_revisions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("review_id", uuid, nullable=False),
        sa.Column("parent_revision_id", uuid, nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["review_id"], ["curriculum_reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["curriculum_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "revision_number", name="uq_curriculum_revisions_number"),
        sa.UniqueConstraint("idempotency_key", name="uq_curriculum_revisions_idempotency"),
    )


def downgrade() -> None:
    op.drop_table("curriculum_revisions")
    op.drop_index("ix_curriculum_reviews_course", table_name="curriculum_reviews")
    op.drop_table("curriculum_reviews")
