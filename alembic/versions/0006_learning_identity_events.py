"""Add internal identities and additive v1 learning-event metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_learning_identity_events"
down_revision: str | None = "0005_job_progress_events"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add identity/event columns without rewriting legacy event payloads."""

    uuid = postgresql.UUID(as_uuid=True)
    timestamp = sa.DateTime(timezone=True)
    op.create_table(
        "student_identities",
        sa.Column("id", uuid, nullable=False),
        sa.Column("provider_namespace", sa.String(length=255), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_namespace", "external_subject",
            name="uq_student_identities_provider_subject",
        ),
    )
    op.create_index(
        "ix_student_identities_external_subject", "student_identities", ["external_subject"],
    )

    op.add_column(
        "learning_events",
        sa.Column("actor_identity_id", uuid, nullable=True),
    )
    op.add_column(
        "learning_events",
        sa.Column("learner_identity_id", uuid, nullable=True),
    )
    op.add_column(
        "learning_events",
        sa.Column("event_schema_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "learning_events",
        sa.Column("occurred_at", timestamp, nullable=True),
    )
    op.add_column(
        "learning_events",
        sa.Column("recorded_at", timestamp, nullable=True),
    )
    op.add_column(
        "learning_events",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "learning_events", sa.Column("versions", postgresql.JSONB(), nullable=True),
    )
    op.alter_column("learning_events", "course_id", existing_type=uuid, nullable=True)
    op.execute(
        sa.text(
            "UPDATE learning_events "
            "SET recorded_at = created_at, event_schema_version = 'legacy-phase2-v1' "
            "WHERE recorded_at IS NULL"
        )
    )
    op.alter_column(
        "learning_events", "recorded_at", existing_type=timestamp, nullable=False,
    )
    op.create_foreign_key(
        "fk_learning_events_actor_identity", "learning_events", "student_identities",
        ["actor_identity_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_learning_events_learner_identity", "learning_events", "student_identities",
        ["learner_identity_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_learning_events_idempotency_key", "learning_events", ["idempotency_key"],
    )
    op.create_index(
        "ix_learning_events_learner_occurred", "learning_events",
        ["learner_identity_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_learning_events_course_type_recorded", "learning_events",
        ["course_id", "type", "recorded_at", "event_id"],
    )
    op.create_index(
        "ix_learning_events_type_recorded", "learning_events",
        ["type", "recorded_at", "event_id"],
    )
    op.create_index(
        "ix_learning_events_actor_recorded", "learning_events",
        ["actor_identity_id", "recorded_at", "event_id"],
    )


def downgrade() -> None:
    """Refuse a populated downgrade rather than discard event or identity data."""

    connection = op.get_bind()
    event_count = connection.execute(
        sa.text("SELECT count(*) FROM learning_events")
    ).scalar_one()
    identity_count = connection.execute(
        sa.text("SELECT count(*) FROM student_identities")
    ).scalar_one()
    if event_count or identity_count:
        raise RuntimeError(
            "0006 downgrade refused: populated learning events or identities would be discarded"
        )

    op.drop_index("ix_learning_events_actor_recorded", table_name="learning_events")
    op.drop_index("ix_learning_events_type_recorded", table_name="learning_events")
    op.drop_index("ix_learning_events_course_type_recorded", table_name="learning_events")
    op.drop_index("ix_learning_events_learner_occurred", table_name="learning_events")
    op.drop_constraint(
        "uq_learning_events_idempotency_key", "learning_events", type_="unique",
    )
    op.drop_constraint(
        "fk_learning_events_learner_identity", "learning_events", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_learning_events_actor_identity", "learning_events", type_="foreignkey",
    )
    op.alter_column("learning_events", "course_id", existing_type=postgresql.UUID(as_uuid=True),
                    nullable=False)
    for column in (
        "idempotency_key", "recorded_at", "occurred_at", "event_schema_version",
        "versions", "learner_identity_id", "actor_identity_id",
    ):
        op.drop_column("learning_events", column)
    op.drop_index("ix_student_identities_external_subject", table_name="student_identities")
    op.drop_table("student_identities")
