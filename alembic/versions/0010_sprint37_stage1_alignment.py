"""Align Sprint 3.7 Stage 1 replay and diagnostic provenance boundaries."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_sprint37_stage1_alignment"
down_revision: str | None = "0009_sprint35_adaptation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column(
        "mastery_evidence",
        sa.Column(
            "inferred_source_attempt_id",
            uuid,
            sa.ForeignKey("mastery_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "mastery_evidence",
        sa.Column("inferred_target_concept_id", uuid, nullable=True),
    )
    op.add_column(
        "mastery_evidence",
        sa.Column(
            "inferred_source_evidence_id", uuid,
            sa.ForeignKey("mastery_evidence.id", ondelete="RESTRICT"), nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_mastery_evidence_inference_source", "mastery_evidence",
        "(inferred_source_attempt_id IS NULL AND inferred_target_concept_id IS NULL "
        "AND inferred_source_evidence_id IS NULL) OR "
        "(kind = 'INFERRED' AND inferred_source_attempt_id IS NOT NULL "
        "AND inferred_target_concept_id IS NOT NULL "
        "AND inferred_source_evidence_id IS NOT NULL AND diagnostic_provenance IS NOT NULL)",
    )
    op.create_index(
        "uq_mastery_evidence_inferred_source_target",
        "mastery_evidence",
        ["inferred_source_attempt_id", "inferred_target_concept_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'INFERRED'"),
    )


def downgrade() -> None:
    populated = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM mastery_evidence "
        "WHERE inferred_source_evidence_id IS NOT NULL "
        "OR inferred_source_attempt_id IS NOT NULL OR inferred_target_concept_id IS NOT NULL)"
    )).scalar_one()
    if populated:
        raise RuntimeError("0010 downgrade refused: diagnostic source linkage would be discarded")
    op.drop_index(
        "uq_mastery_evidence_inferred_source_target",
        table_name="mastery_evidence",
    )
    op.drop_constraint(
        "ck_mastery_evidence_inference_source", "mastery_evidence", type_="check",
    )
    op.drop_column("mastery_evidence", "inferred_source_evidence_id")
    op.drop_column("mastery_evidence", "inferred_target_concept_id")
    op.drop_column("mastery_evidence", "inferred_source_attempt_id")
