"""Add isolated LangGraph PostgreSQL checkpoint tables for draft generation."""

from alembic import op

revision = "0003_curriculum_checkpoints"
down_revision = "0002_curriculum_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Final schema of langgraph-checkpoint-postgres 3.1.2 migrations 0..9.
    # Normal indexes are transactional because these tables are new and empty.
    op.execute("CREATE SCHEMA IF NOT EXISTS curriculum_checkpoints")
    op.execute("""CREATE TABLE curriculum_checkpoints.checkpoint_migrations
               (v INTEGER PRIMARY KEY)""")
    op.execute("""CREATE TABLE curriculum_checkpoints.checkpoints (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT,
        checkpoint JSONB NOT NULL, metadata JSONB NOT NULL DEFAULT '{}',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))""")
    op.execute("""CREATE TABLE curriculum_checkpoints.checkpoint_blobs (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version))""")
    op.execute("""CREATE TABLE curriculum_checkpoints.checkpoint_writes (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL,
        channel TEXT NOT NULL, type TEXT, blob BYTEA NOT NULL,
        task_path TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))""")
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(f"CREATE INDEX {table}_thread_id_idx ON curriculum_checkpoints.{table}(thread_id)")
    op.execute("INSERT INTO curriculum_checkpoints.checkpoint_migrations SELECT generate_series(0,9)")


def downgrade() -> None:
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f"DROP TABLE curriculum_checkpoints.{table}")
    op.execute("DROP SCHEMA curriculum_checkpoints")
