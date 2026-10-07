"""Stage 2 real-DDL guarantees, without a runtime repository or executor."""

import asyncio
import os
import subprocess
import sys
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from packages.curriculum.diagnostics import diagnostic_inference_provenance
from packages.domain.runtime import (
    SESSION_TRANSITIONS,
    DurablePlanVersion,
    ExecutionIdentity,
    SessionState,
)
from packages.persistence import (
    CurriculumGraphConcept,
    CurriculumGraphEdge,
    CurriculumGraphNode,
    DiagnosticInferenceLinkRecord,
    DiagnosticReservationRecord,
    DiagnosticRunRecord,
    ExecutionReceiptRecord,
    FrameAttemptRecord,
    LearningEventRecord,
    LearningPlanRecord,
    LearningPlanVersionRecord,
    LearningSessionRecord,
    MasteryAttempt,
    MasteryEvidenceRecord,
    MasteryQuestionVersion,
    RemediationFrameRecord,
    SessionTransitionRecord,
    StudentIdentity,
    apply_evidence,
)
from packages.persistence.runtime_models import RUNTIME_TABLES
from packages.planner import decide
from tests.integration.test_mastery_runtime import _evidence, _source_context
from tests.unit.test_runtime_contracts import AT, plan_contract

pytestmark = pytest.mark.live_integration


def _plan_values(plan):
    return dict(
        id=plan.identity.plan_version_id, plan_id=plan.plan.plan_id,
        session_id=plan.plan.session_id,
        version=plan.identity.version, trigger_id=plan.identity.trigger_id,
        source_kind=plan.source.kind, source_id=plan.source.source_id,
        source_event_id=plan.source_event_id, session_version=plan.session_version,
        frame_id=plan.frame_id, frame_version=plan.frame_version,
        graph_version_id=plan.graph_version_id, curriculum_revision_id=plan.curriculum_revision_id,
        snapshot_bytes=plan.snapshot_bytes, snapshot_digest=plan.snapshot_digest,
        decision_bytes=plan.decision_bytes, decision_digest=plan.decision_digest,
        action=plan.decision.action, target_id=plan.decision.target_id,
        policy_outcome=plan.decision.policy_outcome,
        mastery_policy_version=plan.mastery_policy_version,
        planner_policy_version=plan.decision.planner_policy_version,
        schema_version=plan.schema_version,
        supersedes_version_id=plan.supersedes_version_id, created_at=plan.created_at,
    )


def _successor(plan):
    snapshot = plan.snapshot.model_copy(update={"plan_version": 2})
    return DurablePlanVersion.model_validate({
        **plan.model_dump(), "identity": {
            "session_id": plan.plan.session_id, "trigger_id": uuid4(), "version": 2,
        }, "snapshot": snapshot, "decision": decide(snapshot),
        "supersedes_version_id": plan.identity.plan_version_id,
    })


@pytest.fixture
async def schema_source(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    session_id, event_id, topic_id, run_id = (uuid4() for _ in range(4))
    plan = plan_contract(
        session_id=session_id, learner_id=source["actor_id"], course_id=source["course_id"],
        source_event_id=event_id,
    )
    execution_id = ExecutionIdentity(plan_version_id=plan.identity.plan_version_id).execution_id
    async with live_database.session() as session, session.begin():
        session.add_all([
            CurriculumGraphNode(
                id=uuid4(), graph_id=source["graph_id"], stable_node_id=topic_id, node_type="TOPIC",
                label="Storage test topic", source="TEST", confidence=1.0,
            ),
            LearningEventRecord(
                event_id=event_id, event_type="SESSION_CREATED", actor_subject="mastery-actor",
                actor_identity_id=source["actor_id"], learner_identity_id=source["actor_id"],
                course_id=source["course_id"], payload={}, correlation_id=uuid4(),
            ),
        ])
        await session.flush()
        session.add(LearningSessionRecord(
            id=session_id, learner_identity_id=source["actor_id"], course_id=source["course_id"],
            state="CREATED", version=1, graph_version_id=source["graph_id"],
            current_topic_id=topic_id,
            last_event_id=event_id, created_at=AT, updated_at=AT,
        ))
        await session.flush()
        session.add(LearningPlanRecord(id=plan.plan.plan_id, session_id=session_id, created_at=AT))
        await session.flush()
        await session.execute(insert(LearningPlanVersionRecord).values(**_plan_values(plan)))
        session.add(ExecutionReceiptRecord(
            id=execution_id, plan_version_id=plan.identity.plan_version_id, session_id=session_id,
            session_version=1, action=plan.decision.action, target_id=plan.decision.target_id,
            policy_outcome="ALLOW", state="PENDING", version=1,
            child_job_ids=[], emitted_event_ids=[],
            created_at=AT,
        ))
        await session.flush()
        session.add(DiagnosticRunRecord(
            id=run_id, session_id=session_id, learner_identity_id=source["actor_id"],
            course_id=source["course_id"], graph_version_id=source["graph_id"],
            diagnostic_policy_version="diagnostic_v1", item_budget=2, source_kind="EVENT",
            source_id=event_id, source_event_id=event_id, state="OPEN", version=1, created_at=AT,
        ))
    return {**source, "session_id": session_id, "event_id": event_id, "topic_id": topic_id,
            "run_id": run_id, "plan": plan, "execution_id": execution_id}


async def _reject(database, statement, *, match=None):
    async with database.session() as session, session.begin():
        with pytest.raises(IntegrityError, match=match):
            async with session.begin_nested():
                await session.execute(statement)


def _reservation(source, **changes):
    return dict(
        id=uuid4(), diagnostic_run_id=source["run_id"], session_id=source["session_id"],
        graph_version_id=source["graph_id"], item_budget=2, execution_id=source["execution_id"],
        question_version_id=source["question_version_id"], target_concept_id=source["concept_id"],
        slot=1, state="RESERVED", version=1, assessed_concept_ids=[], reserved_at=AT,
    ) | changes


def _frame(source, **changes):
    return dict(
        id=uuid4(), session_id=source["session_id"], graph_version_id=source["graph_id"],
        target_concept_id=source["concept_id"], return_to_topic_id=source["topic_id"],
        created_by_execution_id=source["execution_id"], depth=1, state="ACTIVE", version=1,
        rung=0, strategy="reteach", guard_policy_version="guard_v1", attempt_count=0,
        max_attempts=3, min_progress_delta=0.05, baseline_mastery=0.2, latest_mastery=0.2,
        last_event_id=source["event_id"], created_at=AT, updated_at=AT,
    ) | changes


async def test_migration_matches_runtime_metadata(live_database, migrate_database):
    await asyncio.to_thread(migrate_database)

    def compare(connection):
        inspector = inspect(connection)
        for model in RUNTIME_TABLES:
            table = model.__table__
            columns = {column["name"]: column for column in inspector.get_columns(table.name)}
            assert set(columns) == set(table.columns.keys())
            for column in table.columns:
                assert columns[column.name]["nullable"] == column.nullable
                reflected = columns[column.name]["type"]
                assert isinstance(reflected, type(column.type))
                for attribute in ("length", "timezone"):
                    assert getattr(reflected, attribute, None) == getattr(
                        column.type, attribute, None,
                    )
            expected_unique = {
                (constraint.name, tuple(c.name for c in constraint.columns))
                for constraint in table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert expected_unique == {
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table.name)
            }
            assert {constraint.name for constraint in table.constraints
                    if constraint.__class__.__name__ == "CheckConstraint"} == {
                constraint["name"] for constraint in inspector.get_check_constraints(table.name)
            }
            expected_fk = {
                (tuple(e.parent.name for e in fk.elements),
                 tuple(e.target_fullname for e in fk.elements))
                for fk in table.foreign_key_constraints
            }
            actual_fk = {
                (tuple(fk["constrained_columns"]), tuple(
                    f"{fk['referred_table']}.{column}" for column in fk["referred_columns"]
                )) for fk in inspector.get_foreign_keys(table.name)
            }
            assert expected_fk == actual_fk
            assert {index.name for index in table.indexes} == {
                index["name"] for index in inspector.get_indexes(table.name)
                if not index.get("duplicates_constraint")
            }

    async with live_database.engine.connect() as connection:
        await connection.run_sync(compare)


async def test_every_sql_fsm_pair_agrees_with_the_contract(live_database, schema_source):
    async with live_database.session() as session, session.begin():
        for before in SessionState:
            for after in SessionState:
                statement = insert(SessionTransitionRecord).values(
                    session_id=schema_source["session_id"], event_id=schema_source["event_id"],
                    from_state=before, to_state=after, from_version=1, to_version=2, occurred_at=AT,
                )
                if after in SESSION_TRANSITIONS[before]:
                    savepoint = await session.begin_nested()
                    await session.execute(statement)
                    await savepoint.rollback()
                else:
                    with pytest.raises(IntegrityError, match="ck_session_transitions_legal"):
                        async with session.begin_nested():
                            await session.execute(statement)


@pytest.mark.parametrize("key,value,constraint", [
    ("decision_digest", "0" * 64, "ck_plan_versions_digests"),
    ("snapshot_digest", "0" * 64, "ck_plan_versions_digests|plan snapshot provenance mismatch"),
    ("action", "TEACH_CURRENT_TOPIC", "ck_plan_versions_decision_context"),
    ("session_id", uuid4(), "plan snapshot provenance mismatch"),
])
async def test_plan_insert_rejects_changed_bytes_and_cross_session_context(
    live_database, schema_source, key, value, constraint,
):
    values = _plan_values(_successor(schema_source["plan"]))
    values[key] = value
    await _reject(
        live_database, insert(LearningPlanVersionRecord).values(**values), match=constraint,
    )


async def test_successor_is_a_new_version_and_cannot_replace_the_old_decision(
    live_database, schema_source,
):
    original = schema_source["plan"]
    successor = _successor(original)
    async with live_database.session() as session, session.begin():
        await session.execute(insert(LearningPlanVersionRecord).values(**_plan_values(successor)))
    async with live_database.session() as session:
        old = await session.get(LearningPlanVersionRecord, original.identity.plan_version_id)
        new = await session.get(LearningPlanVersionRecord, successor.identity.plan_version_id)
        assert old.decision_bytes == original.decision_bytes
        assert new.supersedes_version_id == old.id
        assert new.decision_bytes != old.decision_bytes
        assert new.version == 2


async def test_canonical_snapshot_and_decision_provenance_must_agree(
    live_database, schema_source,
):
    values = _plan_values(_successor(schema_source["plan"]))
    values["snapshot_bytes"] = values["snapshot_bytes"].replace(
        b'"user_paused":false', b'"user_paused":true',
    )
    values["snapshot_digest"] = sha256(values["snapshot_bytes"]).hexdigest()
    await _reject(
        live_database, insert(LearningPlanVersionRecord).values(**values),
        match="plan snapshot provenance mismatch",
    )


async def test_plan_versions_decisions_and_transition_history_are_append_only(
    live_database, schema_source,
):
    plan = schema_source["plan"]
    original = _plan_values(plan)
    for statement in (
        update(LearningPlanVersionRecord).values(decision_bytes=b'{}'),
        delete(LearningPlanVersionRecord), update(LearningPlanRecord).values(created_at=AT),
    ):
        await _reject(live_database, statement, match="runtime history is immutable")
    async with live_database.session() as session:
        stored = await session.get(LearningPlanVersionRecord, plan.identity.plan_version_id)
        assert stored.decision_bytes == original["decision_bytes"]
        assert stored.snapshot_bytes == original["snapshot_bytes"]


async def test_plan_publication_and_execution_have_distinct_unique_retry_keys(
    live_database, schema_source,
):
    values = _plan_values(schema_source["plan"])
    await _reject(live_database, insert(LearningPlanVersionRecord).values(
        **{**values, "id": uuid4()},
    ))
    async with live_database.session() as session:
        receipt = await session.get(ExecutionReceiptRecord, schema_source["execution_id"])
        values = {column.name: getattr(receipt, column.name)
                  for column in ExecutionReceiptRecord.__table__.columns}
    await _reject(live_database, insert(ExecutionReceiptRecord).values(**{**values, "id": uuid4()}))
    await _reject(
        live_database, update(ExecutionReceiptRecord).values(action="TEACH_CURRENT_TOPIC"),
    )


async def test_terminal_execution_keeps_the_original_result(live_database, schema_source):
    result = b'{"original_result":"complete"}'
    async with live_database.session() as session, session.begin():
        await session.execute(update(ExecutionReceiptRecord).values(
            state="COMPLETED", completed_at=AT, result_bytes=result, version=2,
        ))
    for change in ({"result_bytes": b'{}'}, {"state": "DISPATCHED"}, {"completed_at": None}):
        await _reject(live_database, update(ExecutionReceiptRecord).values(**change))
    async with live_database.session() as session:
        receipt = await session.get(ExecutionReceiptRecord, schema_source["execution_id"])
        assert receipt.result_bytes == result


@pytest.mark.parametrize("change", [
    {"slot": 3}, {"item_budget": 3}, {"graph_version_id": uuid4()},
    {"session_id": uuid4()}, {"state": "ATTEMPTED"}, {"state": "ASSESSED"},
])
async def test_reservation_rejects_budget_scope_and_incomplete_source(
    live_database, schema_source, change,
):
    await _reject(live_database, insert(DiagnosticReservationRecord).values(
        **_reservation(schema_source, **change),
    ))


async def test_same_reservation_race_has_one_schema_winner(live_database, schema_source):
    async def reserve():
        try:
            async with live_database.session() as session, session.begin():
                await session.execute(insert(DiagnosticReservationRecord).values(
                    **_reservation(schema_source),
                ))
            return True
        except IntegrityError:
            return False

    assert sorted(await asyncio.gather(reserve(), reserve())) == [False, True]
    await _reject(live_database, update(DiagnosticReservationRecord).values(slot=2))
    await _reject(live_database, update(DiagnosticRunRecord).values(item_budget=12))
    await _reject(live_database, delete(DiagnosticReservationRecord))


async def test_disjoint_questions_fit_distinct_budget_slots(live_database, schema_source):
    async with live_database.session() as session, session.begin():
        existing = await session.get(MasteryQuestionVersion, schema_source["question_version_id"])
        values = {column.name: getattr(existing, column.name)
                  for column in MasteryQuestionVersion.__table__.columns}
        second = uuid4()
        await session.execute(insert(MasteryQuestionVersion).values(**{**values, "id": second}))
        await session.execute(insert(DiagnosticReservationRecord).values(
            **_reservation(schema_source),
        ))
        await session.execute(insert(DiagnosticReservationRecord).values(**_reservation(
            schema_source, slot=2, question_version_id=second,
        )))
    await _reject(live_database, insert(DiagnosticReservationRecord).values(**_reservation(
        schema_source, slot=2, question_version_id=second,
    )))
    await _reject(live_database, insert(DiagnosticReservationRecord).values(**_reservation(
        schema_source, slot=3, question_version_id=second,
    )))


async def test_frame_attempt_identity_and_saved_return_target_are_durable(
    live_database, schema_source,
):
    frame = _frame(schema_source)
    async with live_database.session() as session, session.begin():
        await session.execute(insert(RemediationFrameRecord).values(**frame))
        await session.execute(insert(FrameAttemptRecord).values(
            frame_id=frame["id"], source_attempt_id=schema_source["attempt_id"],
            event_id=schema_source["event_id"], rung=0, observed_mastery=0.2, occurred_at=AT,
        ))
    await _reject(live_database, insert(RemediationFrameRecord).values(**_frame(schema_source)))
    await _reject(live_database, update(RemediationFrameRecord).values(return_to_topic_id=uuid4()))
    await _reject(live_database, update(RemediationFrameRecord).values(attempt_count=4))
    await _reject(live_database, delete(FrameAttemptRecord))
    await _reject(live_database, insert(FrameAttemptRecord).values(
        frame_id=frame["id"], source_attempt_id=schema_source["attempt_id"],
        event_id=schema_source["event_id"], rung=1, observed_mastery=0.3, occurred_at=AT,
    ))


async def test_assessed_diagnostic_receipt_binds_existing_original_source_and_inference(
    live_database, schema_source,
):
    source = schema_source
    target, edge_id = uuid4(), uuid4()
    evidence = _evidence(source)
    provenance, = diagnostic_inference_provenance(
        diagnostic_run_id=source["run_id"], learner_id=source["actor_id"],
        source_attempt_id=source["attempt_id"],
        source_question_version_id=source["question_version_id"],
        source_evidence_id=evidence.evidence_id, source_graph_version_id=source["graph_id"],
        prerequisite_edge_ids={target: (edge_id,)},
    )
    reservation = _reservation(source)
    async with live_database.session() as session, session.begin():
        session.add(CurriculumGraphConcept(
            id=uuid4(), graph_id=source["graph_id"], stable_concept_id=target,
            key="diagnostic-prerequisite", title="Prerequisite", source="TEST",
            confidence=1.0, verified=True,
        ))
        session.add(CurriculumGraphEdge(
            id=uuid4(), graph_id=source["graph_id"], edge_id=edge_id,
            source_node_id=target, target_node_id=source["concept_id"], edge_type="PREREQUISITE_OF",
            source="USER_CONFIRMED", confidence=1.0, status="CONFIRMED",
        ))
        await session.flush()
        await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=(provenance,),
        )
        await session.execute(insert(DiagnosticReservationRecord).values(**reservation))
        await session.execute(update(DiagnosticReservationRecord).values(
            state="ASSESSED", version=2, source_attempt_id=source["attempt_id"], attempted_at=AT,
            source_evidence_id=evidence.evidence_id, completion_event_id=source["event_id"],
            assessed_concept_ids=[str(source["concept_id"])], assessed_at=AT,
        ))
        inferred_id = await session.scalar(select(MasteryEvidenceRecord.id).where(
            MasteryEvidenceRecord.kind == "INFERRED",
        ))
        await session.execute(insert(DiagnosticInferenceLinkRecord).values(
            evidence_id=inferred_id, reservation_id=reservation["id"], target_concept_id=target,
        ))
    await _reject(live_database, insert(DiagnosticInferenceLinkRecord).values(
        evidence_id=evidence.evidence_id, reservation_id=reservation["id"],
        target_concept_id=uuid4(),
    ), match="diagnostic inference source mismatch")
    await _reject(live_database, update(DiagnosticReservationRecord).values(state="RESERVED"))
    await _reject(live_database, delete(DiagnosticInferenceLinkRecord))
    async with live_database.session() as session:
        stored = await session.get(DiagnosticReservationRecord, reservation["id"])
        assert stored.source_evidence_id == evidence.evidence_id


async def test_cross_learner_diagnostic_source_is_rejected(live_database, schema_source):
    actor_id, attempt_id = uuid4(), uuid4()
    async with live_database.session() as session, session.begin():
        session.add(StudentIdentity(
            id=actor_id, provider_namespace="runtime-test", external_subject=str(actor_id),
        ))
        await session.flush()
        original = await session.get(MasteryAttempt, schema_source["attempt_id"])
        values = {column.name: getattr(original, column.name)
                  for column in MasteryAttempt.__table__.columns}
        await session.execute(insert(MasteryAttempt).values(
            **{**values, "id": attempt_id, "learner_identity_id": actor_id,
               "actor_identity_id": actor_id},
        ))
    await _reject(live_database, insert(DiagnosticReservationRecord).values(**_reservation(
        schema_source, state="ATTEMPTED", source_attempt_id=attempt_id, attempted_at=AT,
    )), match="diagnostic attempt context mismatch")


async def test_stage2_upgrade_and_empty_downgrade_preserve_stage1_data(
    live_database, migrate_database,
):
    await asyncio.to_thread(migrate_database, "upgrade", "0010_sprint37_stage1_alignment")
    source = await _source_context(live_database)
    evidence = _evidence(source)
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor")
        before = (await session.execute(text("SELECT to_jsonb(e) FROM mastery_evidence e"))).all()
    for command, revision in (("upgrade", "head"), ("downgrade", "0010_sprint37_stage1_alignment"),
                              ("upgrade", "head")):
        await asyncio.to_thread(migrate_database, command, revision)
        async with live_database.session() as session:
            after = (await session.execute(text(
                "SELECT to_jsonb(e) FROM mastery_evidence e",
            ))).all()
            assert after == before


async def test_populated_runtime_downgrade_refuses_without_losing_history(
    live_database, schema_source, service_settings,
):
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "0010_sprint37_stage1_alignment"],
        env={**os.environ, "DATABASE_URL": service_settings.database_url},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert any(message in result.stdout + result.stderr for message in (
        "0011 downgrade refused", "0012 downgrade refused", "0013 downgrade refused",
    ))
    async with live_database.session() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0013_sprint37_block_b"
        )
        assert await session.scalar(select(LearningSessionRecord.id)) == schema_source["session_id"]
