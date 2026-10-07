"""Add Block B publication provenance and execution receipt material."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_sprint37_block_b"
down_revision: str | None = "0012_sprint37_block_a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE learning_plan_versions ADD COLUMN source_snapshot_fingerprint VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE learning_execution_receipts "
        "ADD COLUMN request_bytes BYTEA, ADD COLUMN request_digest VARCHAR(64), "
        "ADD COLUMN result_digest VARCHAR(64), ADD COLUMN receipt_digest VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE learning_session_transitions "
        "ADD COLUMN plan_version_id UUID, ADD COLUMN execution_id UUID"
    )
    op.execute(
        "ALTER TABLE learning_session_transitions ADD CONSTRAINT "
        "fk_session_transitions_plan FOREIGN KEY(plan_version_id) "
        "REFERENCES learning_plan_versions(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE learning_session_transitions ADD CONSTRAINT "
        "fk_session_transitions_execution FOREIGN KEY(execution_id) "
        "REFERENCES learning_execution_receipts(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE learning_session_transitions ADD CONSTRAINT "
        "ck_session_transitions_execution_plan CHECK(execution_id IS NULL OR plan_version_id IS NOT NULL)"
    )
    op.execute(
        "CREATE TABLE runtime_trigger_plan_links ("
        "trigger_id UUID PRIMARY KEY REFERENCES runtime_triggers(id) ON DELETE RESTRICT, "
        "plan_version_id UUID NOT NULL UNIQUE REFERENCES learning_plan_versions(id) ON DELETE RESTRICT)"
    )
    op.execute(
        "CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON runtime_trigger_plan_links "
        "FOR EACH ROW EXECUTE FUNCTION sprint37_append_only()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM runtime_trigger_plan_links) OR "
        "EXISTS(SELECT 1 FROM learning_plan_versions) OR "
        "EXISTS(SELECT 1 FROM learning_execution_receipts) OR "
        "EXISTS(SELECT 1 FROM learning_session_transitions)"
    )).scalar_one()
    if populated:
        raise RuntimeError("0013 downgrade refused: Block B history would be discarded")
    op.execute("DROP TRIGGER immutable_history ON runtime_trigger_plan_links")
    op.drop_table("runtime_trigger_plan_links")
    op.drop_constraint(
        "ck_session_transitions_execution_plan", "learning_session_transitions", type_="check",
    )
    op.drop_constraint(
        "fk_session_transitions_execution", "learning_session_transitions", type_="foreignkey",
    )
    op.drop_constraint(
        "fk_session_transitions_plan", "learning_session_transitions", type_="foreignkey",
    )
    op.execute(
        "ALTER TABLE learning_session_transitions DROP COLUMN execution_id, "
        "DROP COLUMN plan_version_id"
    )
    op.execute(
        "ALTER TABLE learning_execution_receipts DROP COLUMN receipt_digest, "
        "DROP COLUMN result_digest, DROP COLUMN request_digest, DROP COLUMN request_bytes"
    )
    op.execute("ALTER TABLE learning_plan_versions DROP COLUMN source_snapshot_fingerprint")
