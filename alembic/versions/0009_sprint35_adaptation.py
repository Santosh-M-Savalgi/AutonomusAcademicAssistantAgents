"""Add Sprint 3.5 review schedules, self-report priors, and provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_sprint35_adaptation"
down_revision: str | None = "0008_mastery_evidence"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    timestamp = postgresql.TIMESTAMP(timezone=True, precision=6)

    op.add_column(
        "mastery_evidence",
        sa.Column("diagnostic_provenance", jsonb, nullable=True),
    )
    op.add_column(
        "mastery_projection_revisions",
        sa.Column("last_successful_review_at", timestamp, nullable=True),
    )
    op.add_column(
        "mastery_projection_revisions",
        sa.Column("last_successful_review_evidence_id", uuid, nullable=True),
    )
    op.add_column(
        "mastery_projection_revisions",
        sa.Column("last_successful_review_event_id", uuid, nullable=True),
    )

    op.create_table(
        "self_report_assertions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("actor_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("graph_version_id", uuid, nullable=True),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("alpha_delta", sa.Float(), nullable=False),
        sa.Column("beta_delta", sa.Float(), nullable=False),
        sa.Column(
            "created_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_self_report_assertions_idempotency"),
        sa.UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_self_report_assertions_concept",
        ),
    )
    op.create_index(
        "ix_self_report_assertions_learner_concept",
        "self_report_assertions",
        ["learner_identity_id", "stable_concept_id"],
    )

    op.create_table(
        "review_schedule",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("graph_version_id", uuid, nullable=True),
        sa.Column("review_policy_version", sa.String(length=64), nullable=False),
        sa.Column("review_rung", sa.Integer(), nullable=False),
        sa.Column("review_successes", sa.Integer(), nullable=False),
        sa.Column("first_concept_event_id", uuid, nullable=True),
        sa.Column("first_concept_event_at", timestamp, nullable=True),
        sa.Column("last_successful_review_at", timestamp, nullable=True),
        sa.Column("last_successful_review_evidence_id", uuid, nullable=True),
        sa.Column("last_successful_review_event_id", uuid, nullable=True),
        sa.Column("due_at", timestamp, nullable=True),
        sa.Column("projection_revision_id", uuid, nullable=True),
        sa.Column("evidence_set_digest", sa.String(length=64), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("schedule_cycle", sa.String(length=64), nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("supporting_evidence_ids", jsonb, nullable=False),
        sa.Column("supporting_event_ids", jsonb, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "updated_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["projection_revision_id"], ["mastery_projection_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_review_schedule_concept",
        ),
        sa.UniqueConstraint("schedule_cycle", name="uq_review_schedule_cycle"),
    )
    op.create_index(
        "ix_review_schedule_due",
        "review_schedule",
        ["learner_identity_id", "course_id", "status", "due_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM self_report_assertions) "
        "OR EXISTS (SELECT 1 FROM review_schedule) "
        "OR EXISTS (SELECT 1 FROM mastery_evidence WHERE diagnostic_provenance IS NOT NULL) "
        "OR EXISTS (SELECT 1 FROM mastery_projection_revisions "
        "WHERE last_successful_review_at IS NOT NULL "
        "OR last_successful_review_evidence_id IS NOT NULL "
        "OR last_successful_review_event_id IS NOT NULL)"
    )).scalar_one()
    if populated:
        raise RuntimeError("0009 downgrade refused: Sprint 3.5 data would be discarded")
    op.drop_index("ix_review_schedule_due", table_name="review_schedule")
    op.drop_table("review_schedule")
    op.drop_index(
        "ix_self_report_assertions_learner_concept", table_name="self_report_assertions",
    )
    op.drop_table("self_report_assertions")
    op.drop_column("mastery_projection_revisions", "last_successful_review_event_id")
    op.drop_column("mastery_projection_revisions", "last_successful_review_evidence_id")
    op.drop_column("mastery_projection_revisions", "last_successful_review_at")
    op.drop_column("mastery_evidence", "diagnostic_provenance")
