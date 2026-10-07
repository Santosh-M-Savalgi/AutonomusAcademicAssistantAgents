"""Disposable live coverage for Block C remediation and recovery boundaries."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from packages.domain.adaptation import DiagnosticCandidate, DiagnosticState
from packages.domain.enums import LearningEventType
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.domain.runtime import (
    DiagnosticRunSnapshot,
    DiagnosticRunState,
    FrameAttempt,
    FrameState,
    RemediationFrameSnapshot,
    SourceIdentity,
    SourceKind,
)
from packages.persistence import (
    MasteryAttempt,
    MasteryEvidenceRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    complete_diagnostic_answer,
    complete_diagnostic_run,
    create_diagnostic_run,
    get_current_projection,
    get_learning_session,
    push_remediation_frame,
    record_remediation_attempt,
    reserve_diagnostic_candidates,
)
from packages.persistence.concept_events import insert_concept_learning_event
from tests.integration.test_block_b_planning_execution import (
    _publish,
    _snapshot,
)
from tests.integration.test_mastery_runtime import _evidence
from tests.unit.test_runtime_contracts import AT

pytest_plugins = ("tests.integration.test_block_b_planning_execution",)
pytestmark = pytest.mark.live_integration


async def test_stage8_frame_push_and_attempt_retry_replays_original_result(
    live_database, block_b_source,
) -> None:
    source, session_value = block_b_source
    snapshot = await _snapshot(live_database, source, session_value)
    plan = await _publish(live_database, source, session_value, snapshot)
    from packages.persistence import execute_published_plan

    async with live_database.session() as session, session.begin():
        receipt = await execute_published_plan(
            session, session_value.learner_id, plan.identity.plan_version_id,
            event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
            completed_at=AT + timedelta(seconds=4),
        )

    async with live_database.session() as session, session.begin():
        current = await get_learning_session(
            session, session_value.learner_id, session_value.session_id,
        )
        assert current is not None
        revision = await session.scalar(select(MasteryProjectionRevision).join(
            MasteryProjectionHead,
            MasteryProjectionHead.current_projection_id == MasteryProjectionRevision.id,
        ).where(
            MasteryProjectionHead.learner_identity_id == session_value.learner_id,
            MasteryProjectionHead.course_id == session_value.course_id,
            MasteryProjectionHead.stable_concept_id == source["concept_id"],
        ))
        assert revision is not None
        projection = await get_current_projection(
            session, session_value.learner_id, session_value.course_id,
            source["concept_id"], as_of=revision.created_at,
        )
        assert projection is not None
        frame = RemediationFrameSnapshot(
            frame_id=uuid4(), session_id=session_value.session_id,
            graph_version_id=source["graph_id"], target_concept_id=source["concept_id"],
            return_to_topic_id=source["topic_id"],
            created_by_execution_id=receipt.identity.execution_id,
            depth=1, state=FrameState.ACTIVE, version=1, rung=0,
            strategy="RETEACH_WITH_NEW_STRATEGY", guard_policy_version="guard_v1",
            attempt_count=0, max_attempts=3, min_progress_delta=0.05,
            baseline_mastery=projection.metrics.mastery,
            latest_mastery=projection.metrics.mastery, last_event_id=source["event_id"],
        )
        pushed = await push_remediation_frame(
            session, session_value.learner_id, frame,
            expected_session_version=current.version, created_at=AT,
        )
        assert await push_remediation_frame(
            session, session_value.learner_id, frame,
            expected_session_version=current.version, created_at=AT,
        ) == pushed

    async with live_database.session() as session, session.begin():
        evidence = await session.scalar(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.learner_identity_id == session_value.learner_id,
            MasteryEvidenceRecord.attempt_id == source["attempt_id"],
        ))
        attempt_row = await session.get(MasteryAttempt, source["attempt_id"])
        assert evidence is not None and attempt_row is not None
        event_id = uuid4()
        await insert_concept_learning_event(session, ConceptLearningEventInput(
            event_id=event_id, type=LearningEventType.ANSWER_GRADED,
            actor_id=session_value.learner_id, actor_subject="mastery-actor",
            learner_id=session_value.learner_id, course_id=session_value.course_id,
            occurred_at=attempt_row.occurred_at,
            payload=LearningEventPayload(kind="answer_graded", data={}),
            correlation_id=uuid4(), idempotency_key=f"block-c-frame:{event_id}",
            stable_concept_ids=(source["concept_id"],),
            source_evidence_id=evidence.id, source_attempt_id=attempt_row.id,
        ))
        revision = await session.scalar(select(MasteryProjectionRevision).join(
            MasteryProjectionHead,
            MasteryProjectionHead.current_projection_id == MasteryProjectionRevision.id,
        ).where(
            MasteryProjectionHead.learner_identity_id == session_value.learner_id,
            MasteryProjectionHead.course_id == session_value.course_id,
            MasteryProjectionHead.stable_concept_id == source["concept_id"],
        ))
        assert revision is not None
        projection = await get_current_projection(
            session, session_value.learner_id, session_value.course_id,
                source["concept_id"], as_of=revision.created_at,
        )
        assert projection is not None
        frame = await get_learning_session(
            session, session_value.learner_id, session_value.session_id,
        )
        assert frame is not None and frame.active_frame_id is not None
        attempt = FrameAttempt(
            frame_id=frame.active_frame_id, source_attempt_id=attempt_row.id,
            event_id=event_id, rung=0, observed_mastery=projection.metrics.mastery,
            occurred_at=attempt_row.occurred_at,
        )
        first = await record_remediation_attempt(
            session, session_value.learner_id, session_value.session_id, attempt,
            expected_frame_version=1,
        )
        assert first.frame.attempt_count == 1

    async with live_database.session() as session, session.begin():
        replay = await record_remediation_attempt(
            session, session_value.learner_id, session_value.session_id, attempt,
            expected_frame_version=1,
        )
        assert replay == first


async def test_stage9_diagnostic_reservation_answer_and_run_completion_are_durable(
    live_database, block_b_source,
) -> None:
    source, session_value = block_b_source
    snapshot = await _snapshot(live_database, source, session_value)
    plan = await _publish(live_database, source, session_value, snapshot)
    from packages.persistence import execute_published_plan

    async with live_database.session() as session, session.begin():
        receipt = await execute_published_plan(
            session, session_value.learner_id, plan.identity.plan_version_id,
            event_id=source["execution_event_id"], started_at=AT + timedelta(seconds=3),
            completed_at=AT + timedelta(seconds=4),
        )

    run_id = uuid4()
    async with live_database.session() as session, session.begin():
        await create_diagnostic_run(session, DiagnosticRunSnapshot(
            diagnostic=DiagnosticState(
                diagnostic_run_id=run_id, learner_id=session_value.learner_id,
                course_id=session_value.course_id, graph_version_id=source["graph_id"],
                diagnostic_policy_version="diagnostic_v1", item_budget=12,
                remaining_item_budget=12,
            ),
            session_id=session_value.session_id,
            source=SourceIdentity(kind=SourceKind.EVENT, source_id=source["event_id"]),
            source_event_id=source["event_id"], state=DiagnosticRunState.OPEN,
            version=1, created_at=AT + timedelta(seconds=5),
        ))
        candidate = DiagnosticCandidate(
            stable_concept_id=source["concept_id"], score=1.0, descendant_count=0,
            confidence=0.2, topological_rank=0,
            question_version_ids=(source["question_version_id"],),
        )
        reservations = await reserve_diagnostic_candidates(
            session, session_value.learner_id, session_value.session_id,
            run_id=run_id, execution_id=receipt.identity.execution_id,
            candidates=(candidate,), expected_run_version=1,
            reserved_at=AT + timedelta(seconds=5),
        )
        assert len(reservations) == 1

    async with live_database.session() as session, session.begin():
        evidence_row = await session.scalar(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.learner_identity_id == session_value.learner_id,
            MasteryEvidenceRecord.attempt_id == source["attempt_id"],
        ))
        attempt_row = await session.get(MasteryAttempt, source["attempt_id"])
        assert evidence_row is not None and attempt_row is not None
        evidence = _evidence(source, evidence_id=evidence_row.id).model_copy(update={
            "idempotency_key": evidence_row.idempotency_key,
            "occurred_at": evidence_row.occurred_at,
        })
        answer_event = uuid4()
        await insert_concept_learning_event(session, ConceptLearningEventInput(
            event_id=answer_event, type=LearningEventType.ANSWER_GRADED,
            actor_id=session_value.learner_id, actor_subject="mastery-actor",
            learner_id=session_value.learner_id, course_id=session_value.course_id,
            occurred_at=evidence.occurred_at,
            payload=LearningEventPayload(kind="answer_graded", data={}),
            correlation_id=uuid4(), idempotency_key=f"block-c-diagnostic:{answer_event}",
            stable_concept_ids=(source["concept_id"],),
            source_evidence_id=evidence.evidence_id, source_attempt_id=attempt_row.id,
        ))
        completed, update = await complete_diagnostic_answer(
            session, session_value.learner_id, session_value.session_id,
            reservations[0].reservation_id, evidence=evidence, event_id=answer_event,
            attempted_at=attempt_row.occurred_at, assessed_at=attempt_row.occurred_at,
            concept_event=ConceptLearningEventInput(
                event_id=answer_event, type=LearningEventType.ANSWER_GRADED,
                actor_id=session_value.learner_id, actor_subject="mastery-actor",
                learner_id=session_value.learner_id, course_id=session_value.course_id,
                occurred_at=evidence.occurred_at,
                payload=LearningEventPayload(kind="answer_graded", data={}),
                correlation_id=uuid4(), idempotency_key=f"block-c-diagnostic:{answer_event}",
                stable_concept_ids=(source["concept_id"],),
                source_evidence_id=evidence.evidence_id, source_attempt_id=attempt_row.id,
            ),
        )
        assert completed.state.value == "ASSESSED"
        assert update.duplicate is True
        finished = await complete_diagnostic_run(
            session, session_value.learner_id, session_value.session_id, run_id,
            expected_version=1, event_id=source["alternate_event_id"],
            completed_at=AT + timedelta(seconds=7),
        )
        assert finished.state == DiagnosticRunState.COMPLETE
