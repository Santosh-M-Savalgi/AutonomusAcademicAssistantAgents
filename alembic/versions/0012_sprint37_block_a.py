"""Add Block A retry journals, source facts and durable trigger ownership."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_sprint37_block_a"
down_revision: str | None = "0011_sprint37_runtime_contracts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABLES = (
    "runtime_operation_receipts", "runtime_topic_windows", "runtime_directives",
    "runtime_assessment_batches", "runtime_window_evidence", "runtime_worker_execution_links",
    "runtime_triggers",
)

DDL = (
    """CREATE TABLE runtime_operation_receipts (
        kind VARCHAR(64) NOT NULL, scope_id UUID NOT NULL, source_id UUID NOT NULL,
        learner_id UUID NOT NULL REFERENCES student_identities(id) ON DELETE RESTRICT,
        request_bytes BYTEA NOT NULL, result_bytes BYTEA NOT NULL,
        PRIMARY KEY(kind,scope_id,source_id))""",
    """CREATE TABLE runtime_topic_windows (
        id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        version INTEGER NOT NULL, event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        closed_at TIMESTAMPTZ, value_bytes BYTEA NOT NULL,
        CONSTRAINT ck_runtime_windows_version CHECK(version >= 1))""",
    "CREATE UNIQUE INDEX uq_runtime_windows_open ON runtime_topic_windows(session_id) WHERE closed_at IS NULL",
    """CREATE TABLE runtime_directives (
        id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        version INTEGER NOT NULL, event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        value_bytes BYTEA NOT NULL, CONSTRAINT ck_runtime_directives_version CHECK(version >= 1))""",
    """CREATE TABLE runtime_assessment_batches (
        id UUID PRIMARY KEY, window_id UUID NOT NULL REFERENCES runtime_topic_windows(id) ON DELETE RESTRICT,
        event_id UUID NOT NULL UNIQUE REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        value_bytes BYTEA NOT NULL)""",
    """CREATE TABLE runtime_window_evidence (
        evidence_id UUID PRIMARY KEY REFERENCES mastery_evidence(id) ON DELETE RESTRICT,
        window_id UUID NOT NULL REFERENCES runtime_topic_windows(id) ON DELETE RESTRICT,
        event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        attempt_id UUID NOT NULL UNIQUE REFERENCES mastery_attempts(id) ON DELETE RESTRICT,
        value_bytes BYTEA NOT NULL)""",
    """CREATE TABLE runtime_worker_execution_links (
        worker_attempt_id UUID NOT NULL,
        execution_id UUID NOT NULL REFERENCES learning_execution_receipts(id) ON DELETE RESTRICT,
        job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT, attempt INTEGER NOT NULL,
        PRIMARY KEY(worker_attempt_id,execution_id),
        CONSTRAINT ck_runtime_worker_link_attempt CHECK(attempt >= 1))""",
    """CREATE TABLE runtime_triggers (
        id UUID PRIMARY KEY, learner_id UUID NOT NULL REFERENCES student_identities(id) ON DELETE RESTRICT,
        session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        kind VARCHAR(64) NOT NULL,
        source_event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        request_bytes BYTEA NOT NULL, original_result_bytes BYTEA NOT NULL,
        status VARCHAR(32) NOT NULL, eligible_after TIMESTAMPTZ, admitted_at TIMESTAMPTZ,
        CONSTRAINT ck_runtime_triggers_status CHECK(status IN ('EVIDENCE_ONLY','REJECTED','BLOCKED','DEFERRED','ADMITTED')))
    """,
    "CREATE INDEX ix_runtime_triggers_learner_status ON runtime_triggers(learner_id,status,eligible_after)",
)


def upgrade() -> None:
    for ddl in DDL:
        op.execute(ddl)
    for table in ("runtime_operation_receipts", "runtime_assessment_batches",
                  "runtime_window_evidence", "runtime_worker_execution_links"):
        op.execute(f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION sprint37_append_only()")
    op.execute("""CREATE FUNCTION block_a_facts_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Block A history cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF NEW.id <> OLD.id OR NEW.session_id <> OLD.session_id OR NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'Block A fact identity/version conflict' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
    for table in ("runtime_topic_windows", "runtime_directives"):
        op.execute(f"CREATE TRIGGER fact_identity BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION block_a_facts_identity()")
    op.execute("""CREATE FUNCTION block_a_trigger_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'trigger history cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.id,NEW.learner_id,NEW.session_id,NEW.kind,NEW.source_event_id,
                    NEW.request_bytes,NEW.original_result_bytes) IS DISTINCT FROM
               ROW(OLD.id,OLD.learner_id,OLD.session_id,OLD.kind,OLD.source_event_id,
                    OLD.request_bytes,OLD.original_result_bytes) OR
               (OLD.status IN ('ADMITTED','EVIDENCE_ONLY','REJECTED') AND NEW IS DISTINCT FROM OLD) THEN
                RAISE EXCEPTION 'trigger original identity/result is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER trigger_identity BEFORE UPDATE OR DELETE ON runtime_triggers "
               "FOR EACH ROW EXECUTE FUNCTION block_a_trigger_identity()")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT " + " OR ".join(
        f"EXISTS(SELECT 1 FROM {table})" for table in TABLES
    ))).scalar_one():
        raise RuntimeError("0012 downgrade refused: Block A history would be discarded")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION block_a_trigger_identity()")
    op.execute("DROP FUNCTION block_a_facts_identity()")
