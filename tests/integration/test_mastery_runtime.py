"""PostgreSQL-backed Sprint 3.4 evidence and projection coverage."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from packages.domain.adaptation import DiagnosticInferenceProvenance
from packages.domain.mastery import (
    AttemptSnapshot,
    ConceptRoleSnapshot,
    EvidenceInput,
    QuestionVersionSnapshot,
)
from packages.persistence import (
    Course,
    CourseMember,
    CurriculumGraphConcept,
    CurriculumGraphEdge,
    CurriculumGraphVersion,
    CurriculumReview,
    CurriculumRevision,
    Document,
    DocumentVersion,
    Job,
    MasteryEvidenceConflictError,
    MasteryEvidenceRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    MasteryValidationError,
    StudentIdentity,
    apply_evidence,
    create_attempt,
    create_question_version,
    get_current_projection,
)

pytestmark = pytest.mark.live_integration


async def _source_context(database):
    now = datetime.now(UTC)
    course_id = uuid4()
    actor_id = uuid4()
    revision_id = uuid4()
    review_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    job_id = uuid4()
    graph_id = uuid4()
    concept_id = uuid4()
    question_id = uuid4()
    question_version_id = uuid4()
    attempt_id = uuid4()
    async with database.session() as session, session.begin():
        session.add_all([
            Course(id=course_id, title="Mastery course"),
            StudentIdentity(
                id=actor_id, provider_namespace="test", external_subject="mastery-actor",
            ),
            CourseMember(course_id=course_id, subject="mastery-actor", role="student"),
            Document(
                id=document_id, course_id=course_id, original_filename="source.pdf",
                content_type="application/pdf", size_bytes=1, sha256="a" * 64,
                page_count=1, storage_key=f"source/{document_id}", uploaded_by="mastery-actor",
            ),
            DocumentVersion(
                id=document_version_id, document_id=document_id, version_number=1,
                storage_key=f"source/{document_id}/1", size_bytes=1, sha256="a" * 64,
                page_count=1,
            ),
            Job(
                id=job_id, job_type="graph_build", payload={}, status="SUCCEEDED", priority=0,
                lane="batch", attempts=0, max_attempts=3, run_after=now,
                idempotency_key=f"mastery-job:{job_id}",
            ),
        ])
        await session.flush()
        session.add(CurriculumReview(
            id=review_id, course_id=course_id, document_id=document_id,
            document_version_id=document_version_id, draft_job_id=job_id,
            original_draft_ref="mastery", status="CONFIRMED",
            current_revision_id=revision_id, revision_number=1,
            confirmed_revision_id=revision_id, created_by="mastery-actor",
            updated_by="mastery-actor", confirmed_by="mastery-actor",
            confirmed_at=now - timedelta(hours=3),
        ))
        await session.flush()
        session.add(CurriculumRevision(
            id=revision_id, review_id=review_id, revision_number=1,
            artifact_ref="mastery-artifact", artifact_sha256="b" * 64,
            content_bytes=1, idempotency_key=f"mastery-revision:{revision_id}",
            created_by="mastery-actor",
        ))
        await session.flush()
        session.add(CurriculumGraphVersion(
            id=graph_id, course_id=course_id, curriculum_revision_id=revision_id,
            version_number=1, status="PUBLISHED", graph_source="TEST",
            artifact_ref="mastery-graph", artifact_sha256="c" * 64, artifact_bytes=1,
            created_by_identity_id=actor_id,
            created_at=now - timedelta(hours=2),
            published_at=now - timedelta(hours=2),
        ))
        await session.flush()
        session.add(CurriculumGraphConcept(
            id=uuid4(), graph_id=graph_id, stable_concept_id=concept_id,
            key="mastery", title="Mastery", source="TEST", confidence=1.0,
            verified=True,
        ))
        await session.flush()
        question = QuestionVersionSnapshot(
            question_id=question_id, question_version_id=question_version_id,
            course_id=course_id, graph_version_id=graph_id, difficulty=3,
            question_type="NUMERIC", tag_confidence=1.0, is_review=False,
            available_at=now - timedelta(hours=1),
        )
        await create_question_version(
            session, question,
            (ConceptRoleSnapshot(stable_concept_id=concept_id, role="PRIMARY"),),
        )
        await create_attempt(session, AttemptSnapshot(
            attempt_id=attempt_id, learner_id=actor_id, actor_id=actor_id,
            question_version_id=question_version_id, course_id=course_id,
            graph_version_id=graph_id, occurred_at=now - timedelta(minutes=30),
            is_review=False,
        ), actor_subject="mastery-actor")
    return {
        "course_id": course_id,
        "actor_id": actor_id,
        "question_id": question_id,
        "question_version_id": question_version_id,
        "attempt_id": attempt_id,
        "graph_id": graph_id,
        "concept_id": concept_id,
        "occurred_at": now - timedelta(minutes=10),
    }


def _evidence(source: dict[str, object], *, evidence_id=None, correct=1.0) -> EvidenceInput:
    return EvidenceInput(
        evidence_id=evidence_id or uuid4(),
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        actor_id=source["actor_id"],  # type: ignore[arg-type]
        course_id=source["course_id"],  # type: ignore[arg-type]
        question_id=source["question_id"],  # type: ignore[arg-type]
        question_version_id=source["question_version_id"],  # type: ignore[arg-type]
        attempt_id=source["attempt_id"],  # type: ignore[arg-type]
        correct=correct,
        difficulty=3,
        question_type="NUMERIC",
        hints_used=0,
        grader_level="L0_RULE",
        grader_confidence=1.0,
        kind="DIRECT",
        occurred_at=source["occurred_at"],  # type: ignore[arg-type]
        graph_version_id=source["graph_id"],  # type: ignore[arg-type]
        concept_roles=(ConceptRoleSnapshot(
            stable_concept_id=source["concept_id"], role="PRIMARY",  # type: ignore[arg-type]
        ),),
        tag_confidence=1.0,
        is_review=False,
        idempotency_key=f"mastery-evidence:{evidence_id or uuid4()}",
    )


async def test_evidence_application_is_idempotent_and_projects(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    async with live_database.session() as session, session.begin():
        first = await apply_evidence(session, evidence, actor_subject="mastery-actor")
        duplicate = await apply_evidence(session, evidence, actor_subject="mastery-actor")
        assert first.projection_ids
        assert duplicate.duplicate
        assert duplicate.projection_ids == first.projection_ids
    async with live_database.session() as session:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == source["actor_id"],
            MasteryProjectionHead.course_id == source["course_id"],
        ))
        revision = None if head is None else await session.get(
            MasteryProjectionRevision, head.current_projection_id,
        )
    assert revision is not None
    assert revision.policy_version == "mastery_v1"
    assert revision.alpha > 1
    assert revision.evidence_count == 1


async def test_future_evidence_rolls_back_and_conflicting_reuse_fails(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    future = _evidence(source, evidence_id=uuid4())
    future = future.model_copy(update={"occurred_at": datetime.now(UTC) + timedelta(days=1)})
    with pytest.raises(MasteryValidationError):
        async with live_database.session() as session, session.begin():
            await apply_evidence(session, future, actor_subject="mastery-actor")
    conflicting = _evidence(source, evidence_id=uuid4(), correct=0.0)
    conflicting = conflicting.model_copy(update={"idempotency_key": "same-key"})
    original = conflicting.model_copy(update={"correct": 1.0})
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, original, actor_subject="mastery-actor")
        with pytest.raises(MasteryEvidenceConflictError):
            await apply_evidence(session, conflicting, actor_subject="mastery-actor")


async def test_projection_reads_use_the_persisted_projection_time(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor")
    async with live_database.session() as session:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == source["actor_id"],
            MasteryProjectionHead.course_id == source["course_id"],
        ))
        assert head is not None
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
        assert revision is not None
        equal = await get_current_projection(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            source["concept_id"],  # type: ignore[arg-type]
            as_of=revision.as_of,
        )
        delayed = await get_current_projection(
            session,
            source["actor_id"],  # type: ignore[arg-type]
            source["course_id"],  # type: ignore[arg-type]
            source["concept_id"],  # type: ignore[arg-type]
            as_of=revision.as_of + timedelta(days=21),
        )
    assert equal is not None and delayed is not None
    assert equal.state.last_occurred_at == revision.as_of
    assert equal.state.alpha == pytest.approx(revision.alpha)
    assert equal.state.beta == pytest.approx(revision.beta)
    assert delayed.state.alpha == pytest.approx(1 + (equal.state.alpha - 1) * 0.5)
    assert delayed.state.beta == pytest.approx(1 + (equal.state.beta - 1) * 0.5)


async def test_diagnostic_inference_persists_once_from_original_source(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    prerequisite_id = uuid4()
    edge_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(CurriculumGraphConcept(
            id=uuid4(), graph_id=source["graph_id"], stable_concept_id=prerequisite_id,
            key="prerequisite", title="Prerequisite", source="TEST", confidence=1.0,
            verified=True,
        ))
        session.add(CurriculumGraphEdge(
            id=uuid4(), graph_id=source["graph_id"], edge_id=edge_id,
            edge_type="PREREQUISITE_OF", source_node_id=prerequisite_id,
            target_node_id=source["concept_id"], source="USER_CONFIRMED", confidence=1.0,
            status="CONFIRMED",
        ))
    evidence = _evidence(source)
    provenance = DiagnosticInferenceProvenance(
        learner_id=source["actor_id"],  # type: ignore[arg-type]
        diagnostic_run_id=uuid4(),
        source_attempt_id=source["attempt_id"],  # type: ignore[arg-type]
        source_question_version_id=source["question_version_id"],  # type: ignore[arg-type]
        source_evidence_id=evidence.evidence_id,
        source_graph_version_id=source["graph_id"],  # type: ignore[arg-type]
        confirmed_edge_ids=(edge_id,),
        target_prerequisite_concept_id=prerequisite_id,
    )
    async with live_database.session() as session, session.begin():
        first = await apply_evidence(
            session,
            evidence,
            actor_subject="mastery-actor",
            diagnostic_inferences=(provenance,),
        )
        duplicate = await apply_evidence(
            session,
            evidence,
            actor_subject="mastery-actor",
            diagnostic_inferences=(provenance,),
        )
    async with live_database.session() as session:
        inferred = (await session.scalars(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.kind == "INFERRED",
            MasteryEvidenceRecord.inferred_source_attempt_id == source["attempt_id"],
            MasteryEvidenceRecord.inferred_target_concept_id == prerequisite_id,
        ))).all()
        prerequisite_head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == source["actor_id"],
            MasteryProjectionHead.course_id == source["course_id"],
            MasteryProjectionHead.stable_concept_id == prerequisite_id,
        ))
        prerequisite_revision = None if prerequisite_head is None else await session.get(
            MasteryProjectionRevision, prerequisite_head.current_projection_id,
        )
    assert first.projection_ids
    assert duplicate.duplicate
    assert len(inferred) == 1
    assert inferred[0].attempt_id == source["attempt_id"]
    assert inferred[0].question_version_id == source["question_version_id"]
    assert inferred[0].diagnostic_provenance == provenance.model_dump(mode="json")
    assert prerequisite_revision is not None
    assert prerequisite_revision.alpha > 1.0
    assert prerequisite_revision.n_direct == 0
