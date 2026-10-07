"""Live Stage 1 regressions for immutable source identity and retry convergence."""

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import func, select

from packages.curriculum.diagnostics import (
    diagnostic_inference_provenance,
    inferred_evidence_for_prerequisite,
)
from packages.domain.enums import LearningEventType
from packages.domain.events import (
    ConceptLearningEventInput,
    LearningEventInput,
    LearningEventPayload,
)
from packages.domain.mastery import AttemptSnapshot
from packages.mastery.engine import decay_state, replay
from packages.mastery.scheduling import review_due_idempotency_key
from packages.persistence import (
    CurriculumGraphConcept,
    CurriculumGraphEdge,
    LearningEventRecord,
    MasteryAttempt,
    MasteryEvidenceConflictError,
    MasteryEvidenceRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    MasteryQuestionVersion,
    MasteryValidationError,
    ReviewScheduleConflictError,
    apply_evidence,
    create_attempt,
    emit_review_due,
    get_current_projection,
    get_review_schedule,
    process_due_reviews,
    select_persisted_review_candidates,
    sync_review_schedules_for_replay,
)
from packages.persistence.learning_events import (
    LearningEventConflictError,
    event_from_record,
    insert_learning_event,
)
from packages.persistence.mastery import _evidence_from_row, _persist_replay
from tests.integration.test_mastery_runtime import _evidence, _source_context

pytestmark = pytest.mark.live_integration


@pytest.fixture
async def review_source(migrate_database, live_database):
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    event = ConceptLearningEventInput(
        event_id=uuid4(), type=LearningEventType.ANSWER_GRADED,
        actor_id=evidence.learner_id, actor_subject="mastery-actor",
        learner_id=evidence.learner_id, course_id=evidence.course_id,
        occurred_at=evidence.occurred_at,
        payload=LearningEventPayload(kind="answer_graded", data={}),
        correlation_id=uuid4(), idempotency_key=f"grade:{evidence.evidence_id}",
        stable_concept_ids=(source["concept_id"],),
        source_evidence_id=evidence.evidence_id, source_attempt_id=evidence.attempt_id,
    )
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor", concept_event=event)
    return source, evidence, event


async def _process(database, evidence, at):
    async with database.session() as session, session.begin():
        return await process_due_reviews(
            session, evidence.learner_id, evidence.course_id, as_of=at,
            actor_id=evidence.learner_id, actor_subject="mastery-actor",
        )


async def test_exact_and_later_due_retries_keep_the_original_complete_envelope(
    live_database, review_source,
) -> None:
    _, evidence, _ = review_source
    at = evidence.occurred_at + timedelta(days=1)
    first, = await _process(live_database, evidence, at)
    original = (first.event_id, first.payload, first.correlation_id, first.occurred_at,
                first.recorded_at, first.created_at, first.versions, first.causation_id)
    exact, = await _process(live_database, evidence, at)
    later, = await _process(live_database, evidence, at + timedelta(days=40))
    for row in (exact, later):
        assert (row.event_id, row.payload, row.correlation_id, row.occurred_at,
                row.recorded_at, row.created_at, row.versions, row.causation_id) == original


async def test_due_retry_preserves_old_projection_metadata_but_validates_new_candidate(
    live_database, review_source,
) -> None:
    source, evidence, grading_event = review_source
    at = evidence.occurred_at + timedelta(days=1)
    first, = await _process(live_database, evidence, at)
    async with live_database.session() as session, session.begin():
        recorded = await session.get(MasteryEvidenceRecord, evidence.evidence_id)
        replayed = replay([_evidence_from_row(recorded)], at, [grading_event])
        await _persist_replay(
            session, replayed, learner_id=evidence.learner_id, course_id=evidence.course_id,
            rebuild_reason="STAGE1_TEST", replayed_at=at,
        )
        await sync_review_schedules_for_replay(
            session, replayed, learner_id=evidence.learner_id, course_id=evidence.course_id,
            concept_events=[grading_event], graph_version_id=evidence.graph_version_id,
        )
    second, = await _process(live_database, evidence, at + timedelta(seconds=1))
    assert first.event_id == second.event_id
    assert first.payload == second.payload
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session, evidence.learner_id, evidence.course_id, source["concept_id"],
        )
    assert schedule.projection_revision_id != UUID(first.payload["data"]["projection_revision_id"])


async def test_due_conflicts_do_not_relax_generic_envelope_equality(
    live_database, review_source,
) -> None:
    source, evidence, _ = review_source
    at = evidence.occurred_at + timedelta(days=1)
    first, = await _process(live_database, evidence, at)
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session, evidence.learner_id, evidence.course_id, source["concept_id"],
        )
        selection = await select_persisted_review_candidates(
            session, evidence.learner_id, evidence.course_id, as_of=at,
        )
    with pytest.raises(ReviewScheduleConflictError):
        async with live_database.session() as session, session.begin():
            await emit_review_due(
                session, schedule, selection.candidates[0], actor_id=evidence.learner_id,
                actor_subject="mastery-actor", occurred_at=at, correlation_id=uuid4(),
            )
    with pytest.raises(ReviewScheduleConflictError):
        async with live_database.session() as session, session.begin():
            await emit_review_due(
                session, schedule,
                selection.candidates[0].model_copy(update={"supporting_evidence_ids": (uuid4(),)}),
                actor_id=evidence.learner_id, actor_subject="mastery-actor", occurred_at=at,
            )
    original = event_from_record(first)
    changed = LearningEventInput.model_validate(original.model_dump(exclude={"recorded_at"}))
    changed.occurred_at = at + timedelta(seconds=1)
    with pytest.raises(LearningEventConflictError):
        async with live_database.session() as session, session.begin():
            await insert_learning_event(session, changed)


async def test_new_evidence_cycle_creates_a_new_notification_without_overwriting_history(
    live_database, review_source,
) -> None:
    source, evidence, _ = review_source
    at = evidence.occurred_at + timedelta(days=1)
    first, = await _process(live_database, evidence, at)
    new_evidence = _evidence(source, correct=0.0)
    new_evidence = new_evidence.model_copy(update={"attempt_id": uuid4()})
    async with live_database.session() as session, session.begin():
        await create_attempt(session, AttemptSnapshot(
            attempt_id=new_evidence.attempt_id, learner_id=evidence.learner_id,
            actor_id=evidence.actor_id, course_id=evidence.course_id,
            question_version_id=evidence.question_version_id,
            graph_version_id=evidence.graph_version_id, occurred_at=evidence.occurred_at,
            is_review=False,
        ), actor_subject="mastery-actor")
        await apply_evidence(session, new_evidence, actor_subject="mastery-actor")
    second, = await _process(live_database, evidence, at)
    assert first.event_id != second.event_id
    assert first.idempotency_key != second.idempotency_key
    async with live_database.session() as session:
        count = await session.scalar(select(func.count()).select_from(LearningEventRecord).where(
            LearningEventRecord.event_type == "REVIEW_DUE",
        ))
    assert count == 2


async def test_stable_due_key_still_uses_the_approved_cycle_formula(live_database, review_source):
    source, evidence, _ = review_source
    at = evidence.occurred_at + timedelta(days=1)
    emitted, = await _process(live_database, evidence, at)
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session, evidence.learner_id, evidence.course_id, source["concept_id"],
        )
    key = review_due_idempotency_key(schedule)
    assert emitted.idempotency_key == key
    assert emitted.event_id == uuid5(NAMESPACE_URL, key)


@pytest.mark.parametrize("field", ["stable_concept_id", "anchor_event_id"])
async def test_conflicting_existing_due_payload_is_rejected_and_not_overwritten(
    live_database, review_source, field,
) -> None:
    source, evidence, _ = review_source
    at = evidence.occurred_at + timedelta(days=1)
    async with live_database.session() as session:
        schedule = await get_review_schedule(
            session, evidence.learner_id, evidence.course_id, source["concept_id"],
        )
    key = review_due_idempotency_key(schedule)
    data = {
        "schedule_cycle": schedule.schedule_cycle,
        "stable_concept_id": str(schedule.stable_concept_id),
        "graph_version_id": str(schedule.graph_version_id),
        "projection_revision_id": str(schedule.projection_revision_id),
        "evidence_set_digest": schedule.evidence_set_digest,
        "due_at": schedule.due_at.isoformat(),
        "supporting_evidence_ids": [str(value) for value in schedule.supporting_evidence_ids],
        "supporting_event_ids": [str(value) for value in schedule.supporting_event_ids],
        "anchor_event_id": str(schedule.first_concept_event_id),
    }
    data[field] = str(uuid4())
    wrong_payload = LearningEventPayload(kind="review_due", data=data)
    async with live_database.session() as session, session.begin():
        await insert_learning_event(session, LearningEventInput(
            event_id=uuid5(NAMESPACE_URL, key), type=LearningEventType.REVIEW_DUE,
            actor_id=evidence.learner_id, actor_subject="mastery-actor",
            learner_id=evidence.learner_id, course_id=evidence.course_id, occurred_at=at,
            correlation_id=uuid4(), idempotency_key=key, payload=wrong_payload,
        ))
    with pytest.raises(ReviewScheduleConflictError):
        await _process(live_database, evidence, at)
    async with live_database.session() as session:
        preserved = await session.scalar(select(LearningEventRecord).where(
            LearningEventRecord.idempotency_key == key,
        ))
    assert preserved.payload == wrong_payload.model_dump(mode="json")


async def test_committed_evidence_digest_is_stable_after_application_marker_and_later_replay(
    live_database, review_source,
) -> None:
    _, evidence, grading_event = review_source
    async with live_database.session() as session:
        record = await session.get(MasteryEvidenceRecord, evidence.evidence_id)
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == evidence.learner_id,
            MasteryProjectionHead.course_id == evidence.course_id,
        ))
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
        accepted = _evidence_from_row(record)
    assert accepted.applied_at is not None
    at_projection = replay([accepted], revision.as_of, [grading_event])
    later = replay([accepted], revision.as_of + timedelta(days=10), [grading_event])
    assert revision.evidence_set_digest == at_projection.evidence_set_digest
    assert later.evidence_set_digest == at_projection.evidence_set_digest
    assert revision.evidence_count == at_projection.evidence_count == 1


async def test_late_evidence_replay_reads_match_pure_replay_at_equal_and_delayed_time(
    live_database, review_source,
) -> None:
    source, evidence, grading_event = review_source
    late = _evidence(source, correct=0.0).model_copy(update={
        "occurred_at": evidence.occurred_at - timedelta(minutes=5),
        "attempt_id": uuid4(),
    })
    async with live_database.session() as session, session.begin():
        await create_attempt(session, AttemptSnapshot(
            attempt_id=late.attempt_id, learner_id=evidence.learner_id,
            actor_id=evidence.actor_id, course_id=evidence.course_id,
            question_version_id=evidence.question_version_id,
            graph_version_id=evidence.graph_version_id, occurred_at=late.occurred_at,
            is_review=False,
        ), actor_subject="mastery-actor")
        await apply_evidence(session, late, actor_subject="mastery-actor")
    async with live_database.session() as session:
        records = (await session.scalars(select(MasteryEvidenceRecord))).all()
        head = await session.scalar(select(MasteryProjectionHead))
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
        expected = replay([_evidence_from_row(item) for item in records],
                          revision.as_of, [grading_event]).projections[0]
        for at in (revision.as_of, revision.as_of + timedelta(days=21)):
            observed = await get_current_projection(
                session, evidence.learner_id, evidence.course_id, source["concept_id"], as_of=at,
            )
            pure_state = decay_state(expected.state, at)
            assert observed.state.alpha == pytest.approx(pure_state.alpha)
            assert observed.state.beta == pytest.approx(pure_state.beta)
        assert revision.max_occurred_at == evidence.occurred_at
        assert revision.as_of > revision.max_occurred_at


@pytest.fixture
async def diagnostic_source(migrate_database, live_database):
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    ancestor, prerequisite, edge_a, edge_b = uuid4(), uuid4(), uuid4(), uuid4()
    async with live_database.session() as session, session.begin():
        for concept_id, key in ((ancestor, "ancestor"), (prerequisite, "prerequisite")):
            session.add(CurriculumGraphConcept(
                id=uuid4(), graph_id=source["graph_id"], stable_concept_id=concept_id,
                key=key, title=key.title(), source="USER_DEFINED", confidence=1.0, verified=True,
            ))
        for edge_id, parent, child in (
            (edge_a, ancestor, prerequisite), (edge_b, prerequisite, source["concept_id"]),
        ):
            session.add(CurriculumGraphEdge(
                id=uuid4(), graph_id=source["graph_id"], edge_id=edge_id,
                edge_type="PREREQUISITE_OF", source_node_id=parent, target_node_id=child,
                source="USER_CONFIRMED", confidence=1.0, status="CONFIRMED",
            ))
    evidence = _evidence(source)
    provenances = diagnostic_inference_provenance(
        diagnostic_run_id=uuid4(), learner_id=evidence.learner_id,
        source_attempt_id=evidence.attempt_id,
        source_question_version_id=evidence.question_version_id,
        source_evidence_id=evidence.evidence_id, source_graph_version_id=evidence.graph_version_id,
        prerequisite_edge_ids={ancestor: (edge_a,), prerequisite: (edge_b,)},
    )
    return source, evidence, provenances


async def test_transitive_inference_uses_original_sources_and_does_not_lose_direct_projection(
    live_database, diagnostic_source,
) -> None:
    source, evidence, provenances = diagnostic_source
    async with live_database.session() as session, session.begin():
        first = await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
        )
    async with live_database.session() as session, session.begin():
        duplicate = await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
        )
        rows = (await session.scalars(select(MasteryEvidenceRecord))).all()
        questions = await session.scalar(select(func.count()).select_from(MasteryQuestionVersion))
        attempts = await session.scalar(select(func.count()).select_from(MasteryAttempt))
    assert duplicate.projection_ids == first.projection_ids
    assert len(rows) == 3 and questions == attempts == 1
    projections = {item.stable_concept_id: item for item in first.projections}
    assert projections[source["concept_id"]].state.n_direct == 1
    for provenance in provenances:
        projection = projections[provenance.target_prerequisite_concept_id]
        assert 1 < projection.state.alpha <= 1.15
        assert projection.state.beta == 1
        assert projection.state.n_direct == 0
        assert projection.state.distinct_direct_question_ids == ()
        assert projection.state.review_successes == 0 and projection.metrics.status != "MASTERED"
        derived, = [row for row in rows if row.inferred_target_concept_id ==
                    provenance.target_prerequisite_concept_id]
        assert derived.inferred_source_evidence_id == evidence.evidence_id
        assert derived.attempt_id == evidence.attempt_id
        assert derived.question_version_id == evidence.question_version_id
        assert derived.occurred_at == evidence.occurred_at
        assert derived.diagnostic_provenance == provenance.model_dump(mode="json")


async def test_concurrent_inference_and_source_retries_converge_without_extra_revisions(
    live_database, diagnostic_source,
) -> None:
    _, evidence, provenances = diagnostic_source

    async def accept():
        async with live_database.session() as session, session.begin():
            return await apply_evidence(
                session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
            )

    first, second = await asyncio.gather(accept(), accept())
    assert first.projection_ids == second.projection_ids
    assert sorted((first.duplicate, second.duplicate)) == [False, True]
    async with live_database.session() as session:
        count = await session.scalar(select(func.count()).select_from(MasteryProjectionRevision))
    assert count == 3


async def test_committed_direct_source_can_add_missing_inferences_without_reapplying_mass(
    live_database, diagnostic_source,
) -> None:
    source, evidence, provenances = diagnostic_source
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor")
    async with live_database.session() as session, session.begin():
        reconciled = await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
        )
    assert reconciled.duplicate
    direct = next(item for item in reconciled.projections
                  if item.stable_concept_id == source["concept_id"])
    assert direct.state.n_direct == 1
    assert len(reconciled.projections) == 3


async def test_unvalidated_derived_request_cannot_bypass_original_question_role_validation(
    live_database, diagnostic_source,
) -> None:
    _, evidence, provenances = diagnostic_source
    inferred = inferred_evidence_for_prerequisite(evidence, provenances[0])
    with pytest.raises(MasteryValidationError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(session, inferred, actor_subject="mastery-actor")
    async with live_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(MasteryEvidenceRecord)) == 0


async def test_inference_and_projection_failure_rolls_back_the_entire_source_transaction(
    live_database, diagnostic_source, monkeypatch,
) -> None:
    _, evidence, provenances = diagnostic_source

    async def fail_projection(*args, **kwargs):
        raise RuntimeError("controlled projection failure")

    monkeypatch.setattr("packages.persistence.mastery._persist_replay", fail_projection)
    with pytest.raises(RuntimeError, match="controlled projection failure"):
        async with live_database.session() as session, session.begin():
            await apply_evidence(
                session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
            )
    async with live_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(MasteryEvidenceRecord)) == 0
        assert await session.scalar(
            select(func.count()).select_from(MasteryProjectionRevision)
        ) == 0


async def test_populated_stage1_linkage_downgrade_is_refused(
    live_database, diagnostic_source, service_settings,
) -> None:
    _, evidence, provenances = diagnostic_source
    async with live_database.session() as session, session.begin():
        await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
        )
    from tests.integration.conftest import ROOT

    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "0009_sprint35_adaptation"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": service_settings.database_url},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "0010 downgrade refused" in result.stderr
    async with live_database.session() as session:
        rows = (await session.scalars(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.kind == "INFERRED",
        ))).all()
    assert len(rows) == 2
    assert all(row.inferred_source_evidence_id == evidence.evidence_id for row in rows)


@pytest.mark.parametrize("correct", [0.0, 0.5])
async def test_partial_and_incorrect_answers_cannot_produce_inference(
    live_database, diagnostic_source, correct,
) -> None:
    _, evidence, provenances = diagnostic_source
    with pytest.raises(MasteryValidationError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(
                session, evidence.model_copy(update={"correct": correct}),
                actor_subject="mastery-actor", diagnostic_inferences=provenances,
            )
    async with live_database.session() as session:
        assert await session.scalar(select(func.count()).select_from(MasteryEvidenceRecord)) == 0


async def test_conflicting_inference_run_and_duplicate_provenance_are_rejected(
    live_database, diagnostic_source,
) -> None:
    _, evidence, provenances = diagnostic_source
    async with live_database.session() as session, session.begin():
        await apply_evidence(
            session, evidence, actor_subject="mastery-actor", diagnostic_inferences=provenances,
        )
    changed = provenances[0].model_copy(update={"diagnostic_run_id": uuid4()})
    with pytest.raises(MasteryEvidenceConflictError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(
                session, evidence, actor_subject="mastery-actor", diagnostic_inferences=(changed,),
            )
    with pytest.raises(MasteryEvidenceConflictError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(
                session, evidence, actor_subject="mastery-actor",
                diagnostic_inferences=(provenances[0], changed),
            )


@pytest.mark.parametrize("change", ["UNKNOWN", "PROPOSED", "REJECTED", "RELATED_TO"])
async def test_unconfirmed_or_unrelated_edges_cannot_be_used_as_inference_provenance(
    live_database, diagnostic_source, change,
) -> None:
    _, evidence, provenances = diagnostic_source
    provenance = provenances[0]
    if change == "UNKNOWN":
        provenance = provenance.model_copy(update={"confirmed_edge_ids": (uuid4(),)})
    else:
        async with live_database.session() as session, session.begin():
            edge = await session.scalar(select(CurriculumGraphEdge).where(
                CurriculumGraphEdge.edge_id == provenance.confirmed_edge_ids[0],
            ))
            if change == "RELATED_TO":
                edge.edge_type = change
            else:
                edge.status = change
    with pytest.raises(MasteryValidationError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(
                session, evidence, actor_subject="mastery-actor",
                diagnostic_inferences=(provenance,),
            )
