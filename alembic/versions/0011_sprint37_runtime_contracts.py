"""Add the additive Sprint 3.7 Stage 2 runtime contract schema."""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_sprint37_runtime_contracts"
down_revision: str | None = "0010_sprint37_stage1_alignment"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_CREATE_ORDER = (
    "learning_sessions",
    "learning_session_transitions",
    "learning_plans",
    "learning_plan_versions",
    "learning_execution_receipts",
    "remediation_frames",
    "remediation_frame_attempts",
    "diagnostic_runs",
    "diagnostic_reservations",
    "diagnostic_inference_links",
)

# Frozen DDL: future model/enum changes cannot change this historical revision.
_TABLE_DDL = (
    """CREATE TABLE learning_sessions (
        id UUID PRIMARY KEY,
        learner_identity_id UUID NOT NULL REFERENCES student_identities(id) ON DELETE RESTRICT,
        course_id UUID NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
        state VARCHAR(32) NOT NULL, version INTEGER NOT NULL,
        graph_version_id UUID REFERENCES curriculum_graph_versions(id) ON DELETE RESTRICT,
        current_topic_id UUID, current_plan_version_id UUID, active_frame_id UUID,
        last_event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
        CONSTRAINT uq_sessions_scope UNIQUE(id, learner_identity_id, course_id),
        CONSTRAINT ck_sessions_state CHECK(state IN ('ADVANCE','ASSESSING','CHECKPOINT','COMPLETE',
            'CREATED','DIAGNOSING','NEEDS_STATE','PAUSED','PLANNING','REPLANNING','RETRIEVING','TEACHING')),
        CONSTRAINT ck_sessions_version CHECK(version >= 1),
        CONSTRAINT ck_sessions_times CHECK(updated_at >= created_at),
        CONSTRAINT ck_sessions_completion CHECK((state = 'COMPLETE') = (completed_at IS NOT NULL)
            AND (completed_at IS NULL OR completed_at BETWEEN created_at AND updated_at)),
        CONSTRAINT ck_sessions_position CHECK(current_topic_id IS NULL OR graph_version_id IS NOT NULL),
        CONSTRAINT fk_sessions_topic FOREIGN KEY(graph_version_id,current_topic_id)
            REFERENCES curriculum_graph_nodes(graph_id,stable_node_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE learning_session_transitions (
        session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        from_state VARCHAR(32) NOT NULL, to_state VARCHAR(32) NOT NULL,
        from_version INTEGER NOT NULL, to_version INTEGER NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(session_id,event_id),
        CONSTRAINT uq_session_transitions_version UNIQUE(session_id,to_version),
        CONSTRAINT ck_session_transitions_version CHECK(from_version >= 1 AND to_version = from_version + 1),
        CONSTRAINT ck_session_transitions_legal CHECK(
            (from_state = 'CREATED' AND to_state IN ('CREATED','NEEDS_STATE','PAUSED','PLANNING')) OR
            (from_state = 'PLANNING' AND to_state IN ('COMPLETE','DIAGNOSING','NEEDS_STATE','PAUSED',
                'PLANNING','RETRIEVING','TEACHING')) OR
            (from_state = 'RETRIEVING' AND to_state IN ('NEEDS_STATE','PAUSED','REPLANNING','RETRIEVING','TEACHING')) OR
            (from_state = 'TEACHING' AND to_state IN ('CHECKPOINT','NEEDS_STATE','PAUSED','REPLANNING','TEACHING')) OR
            (from_state = 'CHECKPOINT' AND to_state IN ('ASSESSING','CHECKPOINT','NEEDS_STATE','PAUSED','REPLANNING')) OR
            (from_state = 'ASSESSING' AND to_state IN ('ASSESSING','DIAGNOSING','NEEDS_STATE','PAUSED','REPLANNING')) OR
            (from_state = 'DIAGNOSING' AND to_state IN ('DIAGNOSING','NEEDS_STATE','PAUSED','REPLANNING')) OR
            (from_state = 'REPLANNING' AND to_state IN ('ADVANCE','COMPLETE','DIAGNOSING','NEEDS_STATE',
                'PAUSED','REPLANNING','RETRIEVING','TEACHING')) OR
            (from_state = 'ADVANCE' AND to_state IN ('ADVANCE','NEEDS_STATE','PAUSED','PLANNING')) OR
            (from_state = 'PAUSED' AND to_state IN ('NEEDS_STATE','PAUSED','PLANNING')) OR
            (from_state = 'NEEDS_STATE' AND to_state IN ('NEEDS_STATE','PAUSED','PLANNING')))
    )""",
    """CREATE TABLE learning_plans (
        id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        created_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_plans_session UNIQUE(session_id), CONSTRAINT uq_plans_scope UNIQUE(id,session_id)
    )""",
    """CREATE TABLE learning_plan_versions (
        id UUID PRIMARY KEY, plan_id UUID NOT NULL, session_id UUID NOT NULL,
        version INTEGER NOT NULL, trigger_id UUID NOT NULL, source_kind VARCHAR(32) NOT NULL,
        source_id UUID NOT NULL,
        source_event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        session_version INTEGER NOT NULL, frame_id UUID, frame_version INTEGER,
        graph_version_id UUID REFERENCES curriculum_graph_versions(id) ON DELETE RESTRICT,
        curriculum_revision_id UUID REFERENCES curriculum_revisions(id) ON DELETE RESTRICT,
        snapshot_bytes BYTEA NOT NULL, snapshot_digest VARCHAR(64) NOT NULL,
        decision_bytes BYTEA NOT NULL, decision_digest VARCHAR(64) NOT NULL,
        action VARCHAR(64) NOT NULL, target_id VARCHAR(255) NOT NULL, policy_outcome VARCHAR(32) NOT NULL,
        mastery_policy_version VARCHAR(64) NOT NULL, planner_policy_version VARCHAR(64) NOT NULL,
        schema_version VARCHAR(32) NOT NULL, supersedes_version_id UUID, created_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_plan_versions_number UNIQUE(plan_id,version),
        CONSTRAINT uq_plan_versions_trigger UNIQUE(session_id,trigger_id),
        CONSTRAINT uq_plan_versions_session UNIQUE(id,session_id),
        CONSTRAINT uq_plan_versions_plan UNIQUE(id,plan_id),
        CONSTRAINT uq_plan_versions_execution_context UNIQUE(id,session_id,action,target_id,policy_outcome,session_version),
        CONSTRAINT fk_plan_versions_scope FOREIGN KEY(plan_id,session_id)
            REFERENCES learning_plans(id,session_id) ON DELETE RESTRICT,
        CONSTRAINT fk_plan_versions_predecessor FOREIGN KEY(supersedes_version_id,plan_id)
            REFERENCES learning_plan_versions(id,plan_id) ON DELETE RESTRICT,
        CONSTRAINT ck_plan_versions_versions CHECK(version >= 1 AND session_version >= 1),
        CONSTRAINT ck_plan_versions_predecessor CHECK((version = 1) = (supersedes_version_id IS NULL)
            AND (supersedes_version_id IS NULL OR supersedes_version_id <> id)),
        CONSTRAINT ck_plan_versions_frame CHECK((frame_id IS NULL) = (frame_version IS NULL)
            AND (frame_version IS NULL OR frame_version >= 1)),
        CONSTRAINT ck_plan_versions_graph CHECK((graph_version_id IS NULL) = (curriculum_revision_id IS NULL)),
        CONSTRAINT ck_plan_versions_source CHECK(source_kind IN ('DIRECTIVE','EVENT','OUTCOME','SESSION')),
        CONSTRAINT ck_plan_versions_action CHECK(action IN ('ADVANCE_TOPIC','ASK_USER','COMPLETE','DIAGNOSE',
            'ESCALATE_MODEL','GENERATE_MICRO_CHECK','GENERATE_QUIZ','PAUSE','PRACTICE_CONCEPT',
            'RETEACH_WITH_NEW_STRATEGY','RETURN_TO_TARGET','REVIEW_DUE','SEARCH_MORE_CONTEXT',
            'TEACH_CURRENT_TOPIC','TEACH_PREREQUISITE')),
        CONSTRAINT ck_plan_versions_policy_outcome CHECK(policy_outcome IN ('ALLOW','REQUIRE_CONFIRMATION','BLOCK')),
        CONSTRAINT ck_plan_versions_digests CHECK(encode(sha256(snapshot_bytes),'hex') = snapshot_digest
            AND encode(sha256(decision_bytes),'hex') = decision_digest),
        CONSTRAINT ck_plan_versions_decision_context CHECK((
            (convert_from(decision_bytes,'UTF8')::jsonb ->> 'action') = action AND
            (convert_from(decision_bytes,'UTF8')::jsonb ->> 'target_id') = target_id AND
            (convert_from(decision_bytes,'UTF8')::jsonb ->> 'policy_outcome') = policy_outcome AND
            (convert_from(decision_bytes,'UTF8')::jsonb ->> 'plan_version') = version::text AND
            (convert_from(decision_bytes,'UTF8')::jsonb ->> 'planner_policy_version') = planner_policy_version
        ) IS TRUE),
        CONSTRAINT ck_plan_versions_policy_versions CHECK(length(mastery_policy_version) > 0
            AND length(planner_policy_version) > 0 AND schema_version = 'runtime-v1')
    )""",
    """CREATE TABLE learning_execution_receipts (
        id UUID PRIMARY KEY, plan_version_id UUID NOT NULL, session_id UUID NOT NULL,
        session_version INTEGER NOT NULL, action VARCHAR(64) NOT NULL, target_id VARCHAR(255) NOT NULL,
        policy_outcome VARCHAR(32) NOT NULL, state VARCHAR(32) NOT NULL, version INTEGER NOT NULL,
        confirmation_event_id UUID REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        child_job_ids JSONB NOT NULL, emitted_event_ids JSONB NOT NULL, result_bytes BYTEA,
        created_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
        CONSTRAINT uq_execution_receipts_plan_version UNIQUE(plan_version_id),
        CONSTRAINT uq_execution_receipts_session UNIQUE(id,session_id),
        CONSTRAINT fk_execution_receipts_plan_context FOREIGN KEY(plan_version_id,session_id,
            action,target_id,policy_outcome,session_version) REFERENCES learning_plan_versions(
            id,session_id,action,target_id,policy_outcome,session_version) ON DELETE RESTRICT,
        CONSTRAINT ck_execution_receipts_state CHECK(state IN ('AWAITING_CONFIRMATION','BLOCKED',
            'COMPLETED','DISPATCHED','FAILED','PENDING','STALE','SUPERSEDED')),
        CONSTRAINT ck_execution_receipts_version CHECK(version >= 1),
        CONSTRAINT ck_execution_receipts_completion CHECK(
            (state IN ('COMPLETED','BLOCKED','STALE','SUPERSEDED','FAILED')) = (completed_at IS NOT NULL)
            AND (completed_at IS NOT NULL) = (result_bytes IS NOT NULL)
            AND (completed_at IS NULL OR completed_at >= created_at)),
        CONSTRAINT ck_execution_receipts_children CHECK(jsonb_typeof(child_job_ids) = 'array'
            AND jsonb_typeof(emitted_event_ids) = 'array'),
        CONSTRAINT ck_execution_receipts_block CHECK(policy_outcome <> 'BLOCK' OR (
            state IN ('BLOCKED','STALE','SUPERSEDED') AND child_job_ids = '[]'::jsonb)),
        CONSTRAINT ck_execution_receipts_confirmation CHECK(policy_outcome <> 'REQUIRE_CONFIRMATION'
            OR confirmation_event_id IS NOT NULL OR (state IN ('AWAITING_CONFIRMATION','BLOCKED',
            'STALE','SUPERSEDED','FAILED') AND child_job_ids = '[]'::jsonb))
    )""",
    """CREATE TABLE remediation_frames (
        id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
        graph_version_id UUID NOT NULL REFERENCES curriculum_graph_versions(id) ON DELETE RESTRICT,
        target_concept_id UUID NOT NULL, return_to_topic_id UUID NOT NULL,
        created_by_execution_id UUID NOT NULL, parent_frame_id UUID, depth INTEGER NOT NULL,
        state VARCHAR(32) NOT NULL, version INTEGER NOT NULL, rung INTEGER NOT NULL,
        strategy VARCHAR(64) NOT NULL, guard_policy_version VARCHAR(64) NOT NULL,
        attempt_count INTEGER NOT NULL, max_attempts INTEGER NOT NULL, min_progress_delta FLOAT NOT NULL,
        baseline_mastery FLOAT NOT NULL, latest_mastery FLOAT NOT NULL,
        last_event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        returned_by_execution_id UUID, returned_at TIMESTAMPTZ,
        CONSTRAINT uq_remediation_frames_session UNIQUE(id,session_id),
        CONSTRAINT uq_remediation_frames_execution UNIQUE(created_by_execution_id),
        CONSTRAINT uq_remediation_frames_return_execution UNIQUE(returned_by_execution_id),
        CONSTRAINT fk_remediation_frames_execution FOREIGN KEY(created_by_execution_id,session_id)
            REFERENCES learning_execution_receipts(id,session_id) ON DELETE RESTRICT,
        CONSTRAINT fk_remediation_frames_parent FOREIGN KEY(parent_frame_id,session_id)
            REFERENCES remediation_frames(id,session_id) ON DELETE RESTRICT,
        CONSTRAINT fk_remediation_frames_return_execution FOREIGN KEY(returned_by_execution_id,session_id)
            REFERENCES learning_execution_receipts(id,session_id) ON DELETE RESTRICT,
        CONSTRAINT fk_remediation_frames_target FOREIGN KEY(graph_version_id,target_concept_id)
            REFERENCES curriculum_graph_concepts(graph_id,stable_concept_id) ON DELETE RESTRICT,
        CONSTRAINT fk_remediation_frames_return FOREIGN KEY(graph_version_id,return_to_topic_id)
            REFERENCES curriculum_graph_nodes(graph_id,stable_node_id) ON DELETE RESTRICT,
        CONSTRAINT ck_remediation_frames_state CHECK(state IN ('ACTIVE','BLOCKED_NEEDS_HUMAN','COMPLETE','RETURNED')),
        CONSTRAINT ck_remediation_frames_bounds CHECK(version >= 1 AND depth >= 1 AND rung >= 0
            AND attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts),
        CONSTRAINT ck_remediation_frames_progress CHECK(baseline_mastery BETWEEN 0 AND 1
            AND latest_mastery BETWEEN 0 AND 1 AND min_progress_delta BETWEEN 0 AND 1),
        CONSTRAINT ck_remediation_frames_parent CHECK((depth = 1) = (parent_frame_id IS NULL)
            AND (parent_frame_id IS NULL OR parent_frame_id <> id)),
        CONSTRAINT ck_remediation_frames_return CHECK((state = 'RETURNED') = (returned_at IS NOT NULL)
            AND (returned_at IS NOT NULL) = (returned_by_execution_id IS NOT NULL))
    )""",
    """CREATE TABLE remediation_frame_attempts (
        frame_id UUID NOT NULL REFERENCES remediation_frames(id) ON DELETE RESTRICT,
        source_attempt_id UUID NOT NULL REFERENCES mastery_attempts(id) ON DELETE RESTRICT,
        event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        rung INTEGER NOT NULL, observed_mastery FLOAT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(frame_id,source_attempt_id),
        CONSTRAINT uq_frame_attempts_source UNIQUE(source_attempt_id),
        CONSTRAINT uq_frame_attempts_event UNIQUE(frame_id,event_id),
        CONSTRAINT ck_frame_attempts_bounds CHECK(rung >= 0 AND observed_mastery BETWEEN 0 AND 1)
    )""",
    """CREATE TABLE diagnostic_runs (
        id UUID PRIMARY KEY, session_id UUID NOT NULL, learner_identity_id UUID NOT NULL,
        course_id UUID NOT NULL,
        graph_version_id UUID NOT NULL REFERENCES curriculum_graph_versions(id) ON DELETE RESTRICT,
        diagnostic_policy_version VARCHAR(64) NOT NULL, item_budget INTEGER NOT NULL,
        source_kind VARCHAR(32) NOT NULL, source_id UUID NOT NULL,
        source_event_id UUID NOT NULL REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        state VARCHAR(32) NOT NULL, version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        completion_event_id UUID REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        CONSTRAINT uq_diagnostic_runs_context UNIQUE(id,session_id,graph_version_id,item_budget),
        CONSTRAINT uq_diagnostic_runs_source UNIQUE(session_id,source_kind,source_id),
        CONSTRAINT fk_diagnostic_runs_session FOREIGN KEY(session_id,learner_identity_id,course_id)
            REFERENCES learning_sessions(id,learner_identity_id,course_id) ON DELETE RESTRICT,
        CONSTRAINT ck_diagnostic_runs_state CHECK(state IN ('CANCELLED','COMPLETE','OPEN')),
        CONSTRAINT ck_diagnostic_runs_source CHECK(source_kind IN ('DIRECTIVE','EVENT','OUTCOME','SESSION')),
        CONSTRAINT ck_diagnostic_runs_bounds CHECK(version >= 1 AND item_budget BETWEEN 0 AND 12),
        CONSTRAINT ck_diagnostic_runs_completion CHECK((state <> 'OPEN') = (completed_at IS NOT NULL)
            AND (completed_at IS NOT NULL) = (completion_event_id IS NOT NULL)
            AND (completed_at IS NULL OR completed_at >= created_at))
    )""",
    """CREATE TABLE diagnostic_reservations (
        id UUID PRIMARY KEY, diagnostic_run_id UUID NOT NULL, session_id UUID NOT NULL,
        graph_version_id UUID NOT NULL, item_budget INTEGER NOT NULL, execution_id UUID NOT NULL,
        question_version_id UUID NOT NULL REFERENCES mastery_question_versions(id) ON DELETE RESTRICT,
        target_concept_id UUID NOT NULL, slot INTEGER NOT NULL, state VARCHAR(32) NOT NULL,
        version INTEGER NOT NULL,
        source_attempt_id UUID REFERENCES mastery_attempts(id) ON DELETE RESTRICT,
        source_evidence_id UUID REFERENCES mastery_evidence(id) ON DELETE RESTRICT,
        completion_event_id UUID REFERENCES learning_events(event_id) ON DELETE RESTRICT,
        assessed_concept_ids JSONB NOT NULL, reserved_at TIMESTAMPTZ NOT NULL,
        attempted_at TIMESTAMPTZ, assessed_at TIMESTAMPTZ,
        CONSTRAINT uq_diagnostic_reservations_slot UNIQUE(diagnostic_run_id,slot),
        CONSTRAINT uq_diagnostic_reservations_question UNIQUE(diagnostic_run_id,question_version_id),
        CONSTRAINT uq_diagnostic_reservations_attempt UNIQUE(source_attempt_id),
        CONSTRAINT uq_diagnostic_reservations_evidence UNIQUE(source_evidence_id),
        CONSTRAINT fk_diagnostic_reservations_run FOREIGN KEY(diagnostic_run_id,session_id,graph_version_id,item_budget)
            REFERENCES diagnostic_runs(id,session_id,graph_version_id,item_budget) ON DELETE RESTRICT,
        CONSTRAINT fk_diagnostic_reservations_execution FOREIGN KEY(execution_id,session_id)
            REFERENCES learning_execution_receipts(id,session_id) ON DELETE RESTRICT,
        CONSTRAINT fk_diagnostic_reservations_target FOREIGN KEY(graph_version_id,target_concept_id)
            REFERENCES curriculum_graph_concepts(graph_id,stable_concept_id) ON DELETE RESTRICT,
        CONSTRAINT ck_diagnostic_reservations_state CHECK(state IN ('ASSESSED','ATTEMPTED','RESERVED')),
        CONSTRAINT ck_diagnostic_reservations_bounds CHECK(version >= 1 AND slot BETWEEN 1 AND item_budget),
        CONSTRAINT ck_diagnostic_reservations_attempt CHECK((state <> 'RESERVED') = (source_attempt_id IS NOT NULL)
            AND (source_attempt_id IS NOT NULL) = (attempted_at IS NOT NULL)
            AND (attempted_at IS NULL OR attempted_at >= reserved_at)),
        CONSTRAINT ck_diagnostic_reservations_assessment CHECK((state = 'ASSESSED') = (source_evidence_id IS NOT NULL)
            AND (source_evidence_id IS NOT NULL) = (completion_event_id IS NOT NULL)
            AND (completion_event_id IS NOT NULL) = (assessed_at IS NOT NULL)
            AND jsonb_typeof(assessed_concept_ids) = 'array'
            AND (state = 'ASSESSED') = (jsonb_array_length(assessed_concept_ids) > 0)
            AND (assessed_at IS NULL OR assessed_at >= attempted_at))
    )""",
    """CREATE TABLE diagnostic_inference_links (
        evidence_id UUID PRIMARY KEY REFERENCES mastery_evidence(id) ON DELETE RESTRICT,
        reservation_id UUID NOT NULL REFERENCES diagnostic_reservations(id) ON DELETE RESTRICT,
        target_concept_id UUID NOT NULL,
        CONSTRAINT uq_diagnostic_inference_links_target UNIQUE(reservation_id,target_concept_id)
    )""",
)

_EXTRA_DDL = (
    "ALTER TABLE learning_sessions ADD CONSTRAINT fk_sessions_frame_head FOREIGN KEY(active_frame_id,id) REFERENCES remediation_frames(id,session_id) ON DELETE RESTRICT",
    "ALTER TABLE learning_sessions ADD CONSTRAINT fk_sessions_plan_head FOREIGN KEY(current_plan_version_id,id) REFERENCES learning_plan_versions(id,session_id) ON DELETE RESTRICT",
    "ALTER TABLE learning_plan_versions ADD CONSTRAINT fk_plan_versions_frame FOREIGN KEY(frame_id,session_id) REFERENCES remediation_frames(id,session_id) ON DELETE RESTRICT",
    "CREATE INDEX ix_sessions_learner_course_state ON learning_sessions(learner_identity_id,course_id,state)",
    "CREATE INDEX ix_plan_versions_session_created ON learning_plan_versions(session_id,created_at)",
    "CREATE INDEX ix_execution_receipts_session_state ON learning_execution_receipts(session_id,state)",
    "CREATE UNIQUE INDEX uq_remediation_frames_active_depth ON remediation_frames(session_id,depth) WHERE state IN ('ACTIVE','COMPLETE')",
    "CREATE INDEX ix_diagnostic_runs_learner_state ON diagnostic_runs(learner_identity_id,state)",
)

_APPEND_ONLY = (
    "learning_plans", "learning_plan_versions", "learning_session_transitions",
    "remediation_frame_attempts", "diagnostic_inference_links",
)
_IDENTITY_COLUMNS = {
    "learning_sessions": ("id", "learner_identity_id", "course_id", "created_at"),
    "learning_execution_receipts": ("id", "plan_version_id", "session_id", "session_version",
                                    "action", "target_id", "policy_outcome", "created_at"),
    "remediation_frames": ("id", "session_id", "graph_version_id", "target_concept_id",
                           "return_to_topic_id", "created_by_execution_id", "parent_frame_id",
                           "depth", "guard_policy_version", "max_attempts", "min_progress_delta", "created_at"),
    "diagnostic_runs": ("id", "session_id", "learner_identity_id", "course_id", "graph_version_id",
                        "diagnostic_policy_version", "item_budget", "source_kind", "source_id",
                        "source_event_id", "created_at"),
    "diagnostic_reservations": ("id", "diagnostic_run_id", "session_id", "graph_version_id",
                                "item_budget", "execution_id", "question_version_id",
                                "target_concept_id", "slot", "reserved_at"),
}


def upgrade() -> None:
    for ddl in (*_TABLE_DDL, *_EXTRA_DDL):
        op.execute(ddl)
    op.execute("""CREATE FUNCTION sprint37_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'runtime history is immutable' USING ERRCODE = '23514'; END $$""")
    for name in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {name} "
                   "FOR EACH ROW EXECUTE FUNCTION sprint37_append_only()")
    op.execute("""CREATE FUNCTION sprint37_runtime_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE field_name text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'runtime history cannot be deleted' USING ERRCODE = '23514';
            END IF;
            FOREACH field_name IN ARRAY TG_ARGV LOOP
                IF to_jsonb(OLD)->field_name IS DISTINCT FROM to_jsonb(NEW)->field_name THEN
                    RAISE EXCEPTION 'runtime identity is immutable: %', field_name USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF TG_TABLE_NAME = 'diagnostic_reservations' THEN
                IF OLD.source_attempt_id IS NOT NULL AND (
                    NEW.source_attempt_id IS DISTINCT FROM OLD.source_attempt_id OR
                    NEW.attempted_at IS DISTINCT FROM OLD.attempted_at
                ) THEN
                    RAISE EXCEPTION 'original diagnostic attempt is immutable' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF (TG_TABLE_NAME = 'learning_execution_receipts' AND OLD.state IN
                    ('COMPLETED','BLOCKED','STALE','SUPERSEDED','FAILED')) OR
               (TG_TABLE_NAME = 'learning_sessions' AND OLD.state = 'COMPLETE') OR
               (TG_TABLE_NAME = 'remediation_frames' AND OLD.state = 'RETURNED') OR
               (TG_TABLE_NAME = 'diagnostic_runs' AND OLD.state <> 'OPEN') OR
               (TG_TABLE_NAME = 'diagnostic_reservations' AND OLD.state = 'ASSESSED') THEN
                IF NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'terminal runtime result is immutable' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$""")
    for name, columns in _IDENTITY_COLUMNS.items():
        args = ",".join(f"'{column}'" for column in columns)
        op.execute(f"CREATE TRIGGER immutable_identity BEFORE UPDATE OR DELETE ON {name} "
                   f"FOR EACH ROW EXECUTE FUNCTION sprint37_runtime_identity({args})")
    op.execute("""CREATE FUNCTION sprint37_plan_context() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot jsonb; decision jsonb; owner learning_sessions%ROWTYPE;
        BEGIN
            snapshot := convert_from(NEW.snapshot_bytes,'UTF8')::jsonb;
            decision := convert_from(NEW.decision_bytes,'UTF8')::jsonb;
            SELECT * INTO owner FROM learning_sessions WHERE id = NEW.session_id;
            IF NOT FOUND OR (
                snapshot->>'learner_id' = owner.learner_identity_id::text AND
                snapshot->>'course_id' = owner.course_id::text AND
                snapshot->>'session_id' = owner.id::text AND
                snapshot->>'plan_version' = NEW.version::text AND
                snapshot->>'planner_policy_version' = NEW.planner_policy_version AND
                decision->'provenance'->>'learner_id' = owner.learner_identity_id::text AND
                decision->'provenance'->>'course_id' = owner.course_id::text AND
                decision->'provenance'->>'session_id' = owner.id::text AND
                decision->'provenance'->>'state_digest' = NEW.snapshot_digest
            ) IS NOT TRUE THEN
                RAISE EXCEPTION 'plan snapshot provenance mismatch' USING ERRCODE = '23514';
            END IF;
            IF NEW.version > 1 AND NOT EXISTS (
                SELECT 1 FROM learning_plan_versions previous WHERE previous.id = NEW.supersedes_version_id
                    AND previous.plan_id = NEW.plan_id AND previous.version = NEW.version - 1
            ) THEN
                RAISE EXCEPTION 'plan predecessor version mismatch' USING ERRCODE = '23514';
            END IF;
            IF NEW.graph_version_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM curriculum_graph_versions graph WHERE graph.id = NEW.graph_version_id
                    AND graph.course_id = owner.course_id AND graph.curriculum_revision_id = NEW.curriculum_revision_id
            ) THEN
                RAISE EXCEPTION 'plan graph revision mismatch' USING ERRCODE = '23514';
            END IF;
            IF (snapshot->'graph_context'->>'graph_version_id') IS DISTINCT FROM NEW.graph_version_id::text
                OR (decision->'provenance'->>'graph_version_id') IS DISTINCT FROM NEW.graph_version_id::text
                OR (snapshot->'remediation_frame'->>'frame_id') IS DISTINCT FROM NEW.frame_id::text THEN
                RAISE EXCEPTION 'plan dependency identity mismatch' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER validate_plan_context BEFORE INSERT ON learning_plan_versions "
               "FOR EACH ROW EXECUTE FUNCTION sprint37_plan_context()")
    op.execute("""CREATE FUNCTION sprint37_diagnostic_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'diagnostic_reservations' THEN
                IF NOT EXISTS (SELECT 1 FROM mastery_question_versions question, diagnostic_runs run
                    WHERE question.id = NEW.question_version_id AND run.id = NEW.diagnostic_run_id
                        AND question.graph_version_id = NEW.graph_version_id AND question.course_id = run.course_id
                        AND question.is_review = false) THEN
                    RAISE EXCEPTION 'diagnostic question context mismatch' USING ERRCODE = '23514';
                END IF;
                IF NEW.source_attempt_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM mastery_attempts attempt, diagnostic_runs run
                    WHERE attempt.id = NEW.source_attempt_id AND run.id = NEW.diagnostic_run_id
                        AND attempt.learner_identity_id = run.learner_identity_id AND attempt.course_id = run.course_id
                        AND attempt.question_version_id = NEW.question_version_id
                        AND attempt.graph_version_id = NEW.graph_version_id AND attempt.is_review = false
                ) THEN
                    RAISE EXCEPTION 'diagnostic attempt context mismatch' USING ERRCODE = '23514';
                END IF;
                IF NEW.source_evidence_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM mastery_evidence evidence, diagnostic_runs run
                    WHERE evidence.id = NEW.source_evidence_id AND run.id = NEW.diagnostic_run_id
                        AND evidence.learner_identity_id = run.learner_identity_id AND evidence.course_id = run.course_id
                        AND evidence.attempt_id = NEW.source_attempt_id AND evidence.question_version_id = NEW.question_version_id
                        AND evidence.graph_version_id = NEW.graph_version_id AND evidence.kind = 'DIRECT'
                        AND evidence.is_review = false
                ) THEN
                    RAISE EXCEPTION 'diagnostic evidence context mismatch' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF NOT EXISTS (SELECT 1 FROM diagnostic_reservations reservation, mastery_evidence evidence
                    WHERE reservation.id = NEW.reservation_id AND evidence.id = NEW.evidence_id
                        AND reservation.state = 'ASSESSED' AND evidence.kind = 'INFERRED'
                        AND evidence.inferred_source_attempt_id = reservation.source_attempt_id
                        AND evidence.inferred_source_evidence_id = reservation.source_evidence_id
                        AND evidence.inferred_target_concept_id = NEW.target_concept_id
                        AND evidence.graph_version_id = reservation.graph_version_id
                        AND evidence.diagnostic_provenance->>'diagnostic_run_id' = reservation.diagnostic_run_id::text
                ) THEN
                    RAISE EXCEPTION 'diagnostic inference source mismatch' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER validate_diagnostic_source BEFORE INSERT OR UPDATE ON diagnostic_reservations "
               "FOR EACH ROW EXECUTE FUNCTION sprint37_diagnostic_source()")
    op.execute("CREATE TRIGGER validate_diagnostic_source BEFORE INSERT ON diagnostic_inference_links "
               "FOR EACH ROW EXECUTE FUNCTION sprint37_diagnostic_source()")


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.exec_driver_sql("SELECT " + " OR ".join(
        f"EXISTS (SELECT 1 FROM {name})" for name in _CREATE_ORDER
    )).scalar_one()
    if populated:
        raise RuntimeError("0011 downgrade refused: runtime history would be discarded")
    op.drop_constraint("fk_sessions_frame_head", "learning_sessions", type_="foreignkey")
    op.drop_constraint("fk_sessions_plan_head", "learning_sessions", type_="foreignkey")
    op.drop_constraint("fk_plan_versions_frame", "learning_plan_versions", type_="foreignkey")
    for name in reversed(_CREATE_ORDER):
        op.drop_table(name)
    op.execute("DROP FUNCTION sprint37_runtime_identity()")
    op.execute("DROP FUNCTION sprint37_append_only()")
    op.execute("DROP FUNCTION sprint37_plan_context()")
    op.execute("DROP FUNCTION sprint37_diagnostic_source()")
