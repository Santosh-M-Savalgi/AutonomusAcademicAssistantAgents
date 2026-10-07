"""Add immutable operational curriculum graph and successor metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_learning_graph_versions"
down_revision: str | None = "0006_learning_identity_events"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB()
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "curriculum_graph_versions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("curriculum_revision_id", uuid, nullable=False),
        sa.Column("parent_graph_id", uuid, nullable=True),
        sa.Column("build_job_id", uuid, nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("graph_source", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_bytes", sa.Integer(), nullable=True),
        sa.Column("curriculum_source", jsonb, nullable=True),
        sa.Column("created_by_identity_id", uuid, nullable=True),
        sa.Column("reviewed_by_identity_id", uuid, nullable=True),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", timestamp, nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["curriculum_revision_id"], ["curriculum_revisions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_graph_id"], ["curriculum_graph_versions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["build_job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "curriculum_revision_id", "version_number",
            name="uq_curriculum_graph_versions_revision_number",
        ),
    )
    op.create_index(
        "ix_curriculum_graph_versions_course_created", "curriculum_graph_versions",
        ["course_id", "created_at", "id"],
    )
    op.create_index(
        "ix_curriculum_graph_versions_revision_status", "curriculum_graph_versions",
        ["curriculum_revision_id", "status", "version_number"],
    )

    op.create_table(
        "curriculum_graph_nodes",
        sa.Column("id", uuid, nullable=False),
        sa.Column("graph_id", uuid, nullable=False),
        sa.Column("stable_node_id", uuid, nullable=False),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("parent_stable_node_id", uuid, nullable=True),
        sa.Column("curriculum_element_id", uuid, nullable=True),
        sa.Column("curriculum_element", jsonb, nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_id"], ["curriculum_graph_versions.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "stable_node_id", name="uq_graph_nodes_stable_id"),
    )
    op.create_index(
        "ix_graph_nodes_graph_type", "curriculum_graph_nodes", ["graph_id", "node_type"],
    )

    op.create_table(
        "curriculum_graph_concepts",
        sa.Column("id", uuid, nullable=False),
        sa.Column("graph_id", uuid, nullable=False),
        sa.Column("stable_concept_id", uuid, nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("derived_from_topic_id", uuid, nullable=True),
        sa.ForeignKeyConstraint(
            ["graph_id"], ["curriculum_graph_versions.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "graph_id", "stable_concept_id", name="uq_graph_concepts_stable_id",
        ),
    )
    op.create_table(
        "curriculum_graph_mappings",
        sa.Column("id", uuid, nullable=False),
        sa.Column("graph_id", uuid, nullable=False),
        sa.Column("mapping_id", uuid, nullable=False),
        sa.Column("topic_id", uuid, nullable=False),
        sa.Column("concept_id", uuid, nullable=False),
        sa.Column("mapping_kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["graph_id"], ["curriculum_graph_versions.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "mapping_id", name="uq_graph_mappings_id"),
        sa.UniqueConstraint("graph_id", "topic_id", "concept_id", name="uq_graph_mapping_pair"),
    )
    op.create_table(
        "curriculum_graph_edges",
        sa.Column("id", uuid, nullable=False),
        sa.Column("graph_id", uuid, nullable=False),
        sa.Column("edge_id", uuid, nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False),
        sa.Column("source_node_id", uuid, nullable=False),
        sa.Column("target_node_id", uuid, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by_identity_id", uuid, nullable=True),
        sa.Column("reviewed_at", timestamp, nullable=True),
        sa.ForeignKeyConstraint(
            ["graph_id"], ["curriculum_graph_versions.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "edge_id", name="uq_graph_edges_id"),
    )
    op.create_index(
        "ix_graph_edges_confirmed_prerequisites", "curriculum_graph_edges",
        ["graph_id", "source_node_id", "target_node_id"],
        postgresql_where=sa.text("edge_type = 'PREREQUISITE_OF' AND status = 'CONFIRMED'"),
    )

    op.create_table(
        "curriculum_successor_versions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("course_id", uuid, nullable=False),
        sa.Column("parent_review_id", uuid, nullable=False),
        sa.Column("parent_revision_id", uuid, nullable=False),
        sa.Column("successor_review_id", uuid, nullable=False),
        sa.Column("successor_revision_id", uuid, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_identity_id", uuid, nullable=False),
        sa.Column("lineage", jsonb, nullable=False),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_review_id"], ["curriculum_reviews.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["curriculum_revisions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_review_id"], ["curriculum_reviews.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_revision_id"], ["curriculum_revisions.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"], ["student_identities.id"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_revision_id", "successor_review_id", "successor_revision_id",
            name="uq_curriculum_successors_parent_successor",
        ),
    )
    op.create_index(
        "ix_curriculum_successors_course", "curriculum_successor_versions",
        ["course_id", "created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    populated = connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM curriculum_graph_versions) "
        "OR EXISTS (SELECT 1 FROM curriculum_successor_versions)"
    )).scalar_one()
    if populated:
        raise RuntimeError(
            "0007 downgrade refused: published graphs or successor metadata would be discarded"
        )
    op.drop_index("ix_curriculum_successors_course", table_name="curriculum_successor_versions")
    op.drop_table("curriculum_successor_versions")
    op.drop_index("ix_graph_edges_confirmed_prerequisites", table_name="curriculum_graph_edges")
    op.drop_table("curriculum_graph_edges")
    op.drop_table("curriculum_graph_mappings")
    op.drop_table("curriculum_graph_concepts")
    op.drop_index("ix_graph_nodes_graph_type", table_name="curriculum_graph_nodes")
    op.drop_table("curriculum_graph_nodes")
    op.drop_index(
        "ix_curriculum_graph_versions_revision_status", table_name="curriculum_graph_versions",
    )
    op.drop_index(
        "ix_curriculum_graph_versions_course_created", table_name="curriculum_graph_versions",
    )
    op.drop_table("curriculum_graph_versions")
