"""Add immutable Sprint 3.4 mastery evidence and projection history."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_mastery_evidence"
down_revision: str | None = "0007_learning_graph_versions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    timestamp = postgresql.TIMESTAMP(timezone=True, precision=6)

    op.create_table(
        "mastery_question_versions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("question_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("graph_version_id", uuid, nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("n_options", sa.Integer(), nullable=True),
        sa.Column("tag_confidence", sa.Float(), nullable=False),
        sa.Column("is_review", sa.Boolean(), nullable=False),
        sa.Column("available_at", timestamp, nullable=False),
        sa.Column("concept_roles", jsonb, nullable=False),
        sa.Column(
            "created_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mastery_question_versions_course", "mastery_question_versions",
        ["course_id", "created_at"],
    )

    op.create_table(
        "mastery_attempts",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("actor_identity_id", uuid, nullable=True),
        sa.Column("question_version_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("graph_version_id", uuid, nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("is_review", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["question_version_id"], ["mastery_question_versions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mastery_attempts_learner_occurred", "mastery_attempts",
        ["learner_identity_id", "occurred_at"],
    )

    op.create_table(
        "mastery_evidence",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("actor_identity_id", uuid, nullable=True),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("question_id", uuid, nullable=False),
        sa.Column("question_version_id", uuid, nullable=False),
        sa.Column("attempt_id", uuid, nullable=False),
        sa.Column("graph_version_id", uuid, nullable=False),
        sa.Column("correct", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("n_options", sa.Integer(), nullable=True),
        sa.Column("hints_used", sa.Integer(), nullable=False),
        sa.Column("grader_level", sa.String(length=32), nullable=False),
        sa.Column("grader_confidence", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("recorded_at", timestamp, nullable=False),
        sa.Column("applied_at", timestamp, nullable=True),
        sa.Column("is_review", sa.Boolean(), nullable=False),
        sa.Column("tag_confidence", sa.Float(), nullable=False),
        sa.Column("concept_roles", jsonb, nullable=False),
        sa.Column("weight_snapshot", jsonb, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["question_version_id"], ["mastery_question_versions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["mastery_attempts.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_mastery_evidence_idempotency"),
    )
    op.create_index(
        "ix_mastery_evidence_learner_occurred", "mastery_evidence",
        ["learner_identity_id", "occurred_at"],
    )
    op.create_index(
        "ix_mastery_evidence_course_concept", "mastery_evidence", ["course_id", "occurred_at"],
    )

    op.create_table(
        "mastery_projection_revisions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("as_of", timestamp, nullable=False),
        sa.Column("replayed_at", timestamp, nullable=False),
        sa.Column("evidence_set_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("max_occurred_at", timestamp, nullable=True),
        sa.Column("max_evidence_id", uuid, nullable=True),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("n_eff", sa.Float(), nullable=False),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("n_direct", sa.Integer(), nullable=False),
        sa.Column("distinct_direct_question_ids", jsonb, nullable=False),
        sa.Column("review_successes", sa.Integer(), nullable=False),
        sa.Column("review_rung", sa.Integer(), nullable=False),
        sa.Column("rebuild_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id", "projection_version",
            name="uq_mastery_projection_revision_version",
        ),
    )
    op.create_index(
        "ix_mastery_projection_revisions_key_created", "mastery_projection_revisions",
        ["learner_identity_id", "course_id", "stable_concept_id", "created_at"],
    )

    op.create_table(
        "mastery_contributions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("projection_id", uuid, nullable=True),
        sa.Column("evidence_id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("alpha_delta", sa.Float(), nullable=False),
        sa.Column("beta_delta", sa.Float(), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["projection_id"], ["mastery_projection_revisions.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["mastery_evidence.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "projection_id", "evidence_id", "stable_concept_id",
            name="uq_mastery_contribution_projection_concept",
        ),
    )
    op.create_index(
        "ix_mastery_contributions_concept", "mastery_contributions",
        ["learner_identity_id", "stable_concept_id"],
    )

    op.create_table(
        "mastery_projection_heads",
        sa.Column("id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("current_projection_id", uuid, nullable=False),
        sa.Column("current_projection_version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", timestamp, nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["current_projection_id"], ["mastery_projection_revisions.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_identity_id", "course_id", "stable_concept_id",
            name="uq_mastery_projection_head_key",
        ),
    )

    op.create_table(
        "learning_event_concepts",
        sa.Column("event_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("learner_identity_id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=True),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("concept_impact", sa.String(length=32), nullable=False),
        sa.Column("source_evidence_id", uuid, nullable=True),
        sa.Column("source_attempt_id", uuid, nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"], ["learning_events.event_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["learner_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("event_id", "stable_concept_id"),
    )
    op.create_index(
        "ix_learning_event_concepts_learner_concept_occurred", "learning_event_concepts",
        ["learner_identity_id", "stable_concept_id", "occurred_at", "event_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM mastery_question_versions) "
        "OR EXISTS (SELECT 1 FROM mastery_attempts) "
        "OR EXISTS (SELECT 1 FROM mastery_evidence) "
        "OR EXISTS (SELECT 1 FROM mastery_contributions) "
        "OR EXISTS (SELECT 1 FROM mastery_projection_revisions) "
        "OR EXISTS (SELECT 1 FROM mastery_projection_heads) "
        "OR EXISTS (SELECT 1 FROM learning_event_concepts)"
    )).scalar_one()
    if populated:
        raise RuntimeError(
            "0008 downgrade refused: mastery evidence or projections would be discarded"
        )
    op.drop_index(
        "ix_learning_event_concepts_learner_concept_occurred",
        table_name="learning_event_concepts",
    )
    op.drop_table("learning_event_concepts")
    op.drop_table("mastery_projection_heads")
    op.drop_index("ix_mastery_contributions_concept", table_name="mastery_contributions")
    op.drop_table("mastery_contributions")
    op.drop_index(
        "ix_mastery_projection_revisions_key_created",
        table_name="mastery_projection_revisions",
    )
    op.drop_table("mastery_projection_revisions")
    op.drop_index("ix_mastery_evidence_course_concept", table_name="mastery_evidence")
    op.drop_index("ix_mastery_evidence_learner_occurred", table_name="mastery_evidence")
    op.drop_table("mastery_evidence")
    op.drop_index("ix_mastery_attempts_learner_occurred", table_name="mastery_attempts")
    op.drop_table("mastery_attempts")
    op.drop_index(
        "ix_mastery_question_versions_course", table_name="mastery_question_versions",
    )
    op.drop_table("mastery_question_versions")
