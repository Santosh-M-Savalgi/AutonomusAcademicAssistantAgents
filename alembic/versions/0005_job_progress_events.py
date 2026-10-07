"""Add durable, replayable PostgreSQL-backed job progress events."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_job_progress_events"
down_revision = "0004_curriculum_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "jobs", sa.Column("latest_event_sequence", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("jobs", sa.Column("progress_stage", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("progress_percent", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("progress_message", sa.String(length=160), nullable=True))
    op.create_table(
        "job_progress_events",
        sa.Column("event_id", uuid, nullable=False),
        sa.Column("job_id", uuid, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_progress_events_sequence"),
        sa.UniqueConstraint("job_id", "idempotency_key", name="uq_job_progress_events_idempotency"),
    )
    op.create_index(
        "ix_job_progress_events_replay", "job_progress_events", ["job_id", "sequence"]
    )
    # Preserve a durable creation cursor for jobs that already existed before this migration.
    op.execute("""
        INSERT INTO job_progress_events
            (event_id, job_id, sequence, type, payload, attempt, idempotency_key, created_at)
        SELECT md5(j.id::text || chr(58) || 'created')::uuid, j.id, 1, 'job.created',
               jsonb_build_object(
                   'schema_version', 'job-event-v1', 'job_type', j.type, 'status', 'PENDING'
               ), 0, 'created', j.created_at
        FROM jobs AS j
    """)
    op.execute("UPDATE jobs SET latest_event_sequence = 1")


def downgrade() -> None:
    op.drop_index("ix_job_progress_events_replay", table_name="job_progress_events")
    op.drop_table("job_progress_events")
    op.drop_column("jobs", "progress_message")
    op.drop_column("jobs", "progress_percent")
    op.drop_column("jobs", "progress_stage")
    op.drop_column("jobs", "latest_event_sequence")
