"""Caller-owned transactional persistence for Sprint 3.4 mastery evidence."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.curriculum.diagnostics import (
    confirmed_prerequisite_provenance,
    inferred_evidence_for_prerequisite,
)
from packages.domain.adaptation import (
    DiagnosticInferenceProvenance,
    SelfReportAssertion,
    SelfReportPriorContribution,
)
from packages.domain.enums import LearningEventType
from packages.domain.events import (
    ConceptLearningEventInput,
    LearningEventPayload,
)
from packages.domain.graph import EdgeSource, EdgeStatus, EdgeType, GraphEdge
from packages.domain.mastery import (
    AttemptSnapshot,
    ConceptMastery,
    ConceptRoleSnapshot,
    EvidenceInput,
    EvidenceRecord,
    MasteryMetrics,
    MasteryState,
    MasteryUpdateResult,
    QuestionVersionSnapshot,
    ReplayResult,
)
from packages.mastery.engine import decay_state, metrics_for
from packages.mastery.engine import replay as pure_replay
from packages.mastery.weights import calculate_weight_snapshot
from packages.persistence.concept_events import insert_concept_learning_event
from packages.persistence.models import (
    CourseMember,
    CurriculumGraphConcept,
    CurriculumGraphEdge,
    CurriculumGraphVersion,
    LearningEventConceptAssociation,
    LearningEventRecord,
    MasteryAttempt,
    MasteryContributionRecord,
    MasteryEvidenceRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    MasteryQuestionVersion,
    SelfReportAssertionRecord,
    StudentIdentity,
)
from packages.persistence.review_schedule import sync_review_schedules_for_replay


class MasteryEvidenceConflictError(ValueError):
    """Evidence or idempotency key was reused with different immutable data."""


class MasteryValidationError(ValueError):
    """Evidence source context or authorization failed validation."""


async def _db_clock(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if value is None:
        raise RuntimeError("Database did not return a timestamp")
    return cast(datetime, value).astimezone(UTC)


def _roles_json(roles: Sequence[ConceptRoleSnapshot]) -> list[dict[str, str]]:
    return [item.model_dump(mode="json") for item in roles]


async def create_question_version(
    session: AsyncSession,
    snapshot: QuestionVersionSnapshot,
    concept_roles: Sequence[ConceptRoleSnapshot],
) -> MasteryQuestionVersion:
    """Persist immutable question-version metadata without committing."""

    graph = await session.scalar(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.id == snapshot.graph_version_id,
        CurriculumGraphVersion.course_id == snapshot.course_id,
        CurriculumGraphVersion.status == "PUBLISHED",
    ))
    if graph is None or graph.published_at is None:
        raise MasteryValidationError("Question version requires a published course graph")
    if not concept_roles:
        raise MasteryValidationError("Question version requires concept role snapshots")
    if graph.published_at > snapshot.available_at:
        raise MasteryValidationError("Question version is available before graph publication")
    row = MasteryQuestionVersion(
        id=snapshot.question_version_id,
        question_id=snapshot.question_id,
        course_id=snapshot.course_id,
        graph_version_id=snapshot.graph_version_id,
        difficulty=snapshot.difficulty,
        question_type=snapshot.question_type,
        n_options=snapshot.n_options,
        tag_confidence=snapshot.tag_confidence,
        is_review=snapshot.is_review,
        available_at=snapshot.available_at,
        concept_roles=_roles_json(concept_roles),
    )
    session.add(row)
    await session.flush()
    return row


async def create_attempt(
    session: AsyncSession,
    attempt: AttemptSnapshot,
    *,
    actor_subject: str | None = None,
) -> MasteryAttempt:
    """Validate and persist an immutable attempt snapshot."""

    question = await session.get(MasteryQuestionVersion, attempt.question_version_id)
    if question is None:
        raise MasteryValidationError("Attempt question version does not exist")
    if (
        question.course_id != attempt.course_id
        or question.graph_version_id != attempt.graph_version_id
    ):
        raise MasteryValidationError("Attempt source context does not match question version")
    if question.is_review != attempt.is_review:
        raise MasteryValidationError("Attempt review marker conflicts with question version")
    if question.available_at > attempt.occurred_at:
        raise MasteryValidationError("Attempt occurs before question availability")
    graph = await session.get(CurriculumGraphVersion, attempt.graph_version_id)
    if graph is None or graph.status != "PUBLISHED" or graph.published_at is None:
        raise MasteryValidationError("Attempt requires a published graph")
    if graph.published_at > attempt.occurred_at:
        raise MasteryValidationError("Attempt occurs before graph publication")
    if actor_subject is not None:
        member = await session.scalar(select(CourseMember).where(
            CourseMember.course_id == attempt.course_id,
            CourseMember.subject == actor_subject,
        ))
        if member is None:
            raise MasteryValidationError("Course membership is required for attempt creation")
    if (
        actor_subject is None
        and attempt.actor_id is not None
        and attempt.actor_id != attempt.learner_id
    ):
        raise MasteryValidationError("Delegated attempt creation requires authorization context")
    row = MasteryAttempt(
        id=attempt.attempt_id,
        learner_identity_id=attempt.learner_id,
        actor_identity_id=attempt.actor_id,
        question_version_id=attempt.question_version_id,
        course_id=attempt.course_id,
        graph_version_id=attempt.graph_version_id,
        occurred_at=attempt.occurred_at,
        is_review=attempt.is_review,
    )
    session.add(row)
    await session.flush()
    return row


def _evidence_from_row(row: MasteryEvidenceRecord) -> EvidenceRecord:
    roles = tuple(ConceptRoleSnapshot.model_validate(item) for item in row.concept_roles)
    return EvidenceRecord(
        evidence_id=row.id,
        learner_id=row.learner_identity_id,
        actor_id=row.actor_identity_id,
        course_id=row.course_id,
        question_id=row.question_id,
        question_version_id=row.question_version_id,
        attempt_id=row.attempt_id,
        correct=row.correct,
        difficulty=cast(Literal[1, 2, 3, 4, 5], row.difficulty),
        question_type=cast(
            Literal["MCQ", "TRUE_FALSE", "NUMERIC", "SHORT_TEXT", "CODE"],
            row.question_type,
        ),
        n_options=row.n_options,
        hints_used=row.hints_used,
        grader_level=cast(
            Literal["L0_RULE", "L1_TESTS", "L2_LLM_RUBRIC", "L3_ESCALATED"],
            row.grader_level,
        ),
        grader_confidence=row.grader_confidence,
        kind=cast(Literal["DIRECT", "INFERRED"], row.kind),
        occurred_at=row.occurred_at,
        graph_version_id=row.graph_version_id,
        concept_roles=roles,
        tag_confidence=row.tag_confidence,
        is_review=row.is_review,
        idempotency_key=row.idempotency_key,
        recorded_at=row.recorded_at,
        applied_at=row.applied_at,
        diagnostic_provenance=(
            None if row.diagnostic_provenance is None
            else DiagnosticInferenceProvenance.model_validate(row.diagnostic_provenance)
        ),
    )


def _same_evidence(row: MasteryEvidenceRecord, evidence: EvidenceInput) -> bool:
    return (
        _evidence_from_row(row).model_dump(exclude={"recorded_at", "applied_at"})
        == evidence.model_dump()
    )


def _diagnostic_inference_key(provenance: DiagnosticInferenceProvenance) -> str:
    return (
        "diagnostic-inferred:v1:"
        f"{provenance.source_attempt_id.hex}:"
        f"{provenance.target_prerequisite_concept_id.hex}"
    )


async def _lock_mastery_learner(session: AsyncSession, learner_id: UUID) -> None:
    """Serialize caller-owned mastery transactions before reading the source set.

    The existing identity row covers absent projection/schedule/evidence rows.
    Lock order is learner identity, source evidence UUIDs, concept UUIDs.
    """

    learner = await session.scalar(select(StudentIdentity).where(
        StudentIdentity.id == learner_id,
    ).with_for_update())
    if learner is None:
        raise MasteryValidationError("Mastery learner identity does not exist")


async def _persist_diagnostic_inference(
    session: AsyncSession,
    provenance: DiagnosticInferenceProvenance,
    *,
    validation_time: datetime,
) -> MasteryEvidenceRecord:
    """Persist one validated derived contribution without inventing source rows."""

    key = _diagnostic_inference_key(provenance)
    source = await session.scalar(select(MasteryEvidenceRecord).where(
        MasteryEvidenceRecord.id == provenance.source_evidence_id,
    ).with_for_update().execution_options(populate_existing=True))
    if source is None:
        raise MasteryValidationError("Diagnostic source evidence does not exist")
    if (
        source.learner_identity_id != provenance.learner_id
        or source.attempt_id != provenance.source_attempt_id
        or source.question_version_id != provenance.source_question_version_id
        or source.graph_version_id != provenance.source_graph_version_id
        or source.kind != "DIRECT"
        or source.correct != 1.0
        or source.is_review
    ):
        raise MasteryValidationError(
            "Diagnostic inference source is not a full-credit direct answer"
        )

    attempt = await session.get(MasteryAttempt, provenance.source_attempt_id)
    question = await session.get(MasteryQuestionVersion, provenance.source_question_version_id)
    graph = await session.get(CurriculumGraphVersion, provenance.source_graph_version_id)
    if attempt is None or question is None or graph is None:
        raise MasteryValidationError("Diagnostic inference source context does not exist")
    if (
        attempt.learner_identity_id != provenance.learner_id
        or attempt.question_version_id != provenance.source_question_version_id
        or question.graph_version_id != provenance.source_graph_version_id
        or attempt.graph_version_id != provenance.source_graph_version_id
        or attempt.course_id != source.course_id
        or question.course_id != source.course_id
        or question.question_id != source.question_id
        or sorted(question.concept_roles, key=str) != sorted(source.concept_roles, key=str)
        or (
            question.difficulty, question.question_type,
            question.n_options, question.tag_confidence,
        )
        != (source.difficulty, source.question_type, source.n_options, source.tag_confidence)
        or attempt.is_review or question.is_review
        or graph.published_at is None
        or graph.published_at > source.occurred_at
        or question.available_at > attempt.occurred_at
        or attempt.occurred_at > source.occurred_at
        or source.occurred_at > validation_time
        or graph.course_id != source.course_id
        or graph.status != "PUBLISHED"
    ):
        raise MasteryValidationError("Diagnostic inference source context conflicts")

    edge_rows = list((await session.scalars(select(CurriculumGraphEdge).where(
        CurriculumGraphEdge.graph_id == provenance.source_graph_version_id,
    ))).all())
    target = provenance.target_prerequisite_concept_id
    source_concepts = {
        UUID(str(item["stable_concept_id"])) for item in source.concept_roles
    }
    confirmed_edges = tuple(GraphEdge(
        edge_id=edge.edge_id, edge_type=EdgeType(edge.edge_type),
        source_node_id=edge.source_node_id, target_node_id=edge.target_node_id,
        source=EdgeSource(edge.source), confidence=edge.confidence, status=EdgeStatus(edge.status),
    ) for edge in edge_rows)
    closure = confirmed_prerequisite_provenance(confirmed_edges, tuple(source_concepts))
    if (
        target not in closure
        or set(closure[target]) != set(provenance.confirmed_edge_ids)
    ):
        raise MasteryValidationError(
            "Diagnostic inference provenance does not match the confirmed prerequisite closure"
        )
    concept_ids = set((await session.scalars(select(CurriculumGraphConcept.stable_concept_id).where(
        CurriculumGraphConcept.graph_id == source.graph_version_id,
    ))).all())
    if target not in concept_ids or not source_concepts <= concept_ids or any(
        edge.source_node_id not in concept_ids or edge.target_node_id not in concept_ids
        for edge in confirmed_edges if edge.edge_type == EdgeType.PREREQUISITE_OF
    ):
        raise MasteryValidationError("Diagnostic inference concept is absent from its graph")

    derived = inferred_evidence_for_prerequisite(_evidence_from_row(source), provenance)

    existing = await session.scalar(select(MasteryEvidenceRecord).where(
        (MasteryEvidenceRecord.idempotency_key == key)
        | (
            (MasteryEvidenceRecord.inferred_source_attempt_id == provenance.source_attempt_id)
            & (
                MasteryEvidenceRecord.inferred_target_concept_id == target
            )
        )
    ).with_for_update())
    if existing is not None:
        if not _same_evidence(existing, derived) or (
            existing.inferred_source_evidence_id != source.id
            or existing.inferred_source_attempt_id != provenance.source_attempt_id
            or existing.inferred_target_concept_id != target
        ):
            raise MasteryEvidenceConflictError("Conflicting diagnostic inference reuse")
        return existing

    inferred_row = MasteryEvidenceRecord(
        id=derived.evidence_id,
        learner_identity_id=derived.learner_id,
        actor_identity_id=derived.actor_id,
        course_id=derived.course_id,
        question_id=derived.question_id,
        question_version_id=derived.question_version_id,
        attempt_id=derived.attempt_id,
        graph_version_id=derived.graph_version_id,
        correct=derived.correct,
        difficulty=derived.difficulty,
        question_type=derived.question_type,
        n_options=derived.n_options,
        hints_used=derived.hints_used,
        grader_level=derived.grader_level,
        grader_confidence=derived.grader_confidence,
        kind=derived.kind,
        occurred_at=derived.occurred_at,
        recorded_at=validation_time,
        is_review=derived.is_review,
        tag_confidence=derived.tag_confidence,
        concept_roles=_roles_json(derived.concept_roles),
        weight_snapshot=calculate_weight_snapshot(derived).model_dump(mode="json"),
        diagnostic_provenance=provenance.model_dump(mode="json"),
        idempotency_key=derived.idempotency_key,
        inferred_source_attempt_id=provenance.source_attempt_id,
        inferred_target_concept_id=target,
        inferred_source_evidence_id=source.id,
    )
    try:
        async with session.begin_nested():
            session.add(inferred_row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(MasteryEvidenceRecord).where(
            MasteryEvidenceRecord.idempotency_key == key,
        ))
        if existing is None:
            raise
        if not _same_evidence(existing, derived) or (
            existing.inferred_source_evidence_id != source.id
            or existing.inferred_source_attempt_id != provenance.source_attempt_id
            or existing.inferred_target_concept_id != target
        ):
            raise MasteryEvidenceConflictError("Conflicting diagnostic inference reuse") from None
        return cast(MasteryEvidenceRecord, existing)
    return inferred_row


async def _persist_diagnostic_inferences(
    session: AsyncSession,
    provenances: Sequence[DiagnosticInferenceProvenance],
    *,
    validation_time: datetime,
) -> tuple[MasteryEvidenceRecord, ...]:
    rows: list[MasteryEvidenceRecord] = []
    seen: dict[tuple[UUID, UUID], DiagnosticInferenceProvenance] = {}
    for provenance in sorted(provenances, key=lambda item: (
        item.source_attempt_id.bytes, item.target_prerequisite_concept_id.bytes,
    )):
        identity = (provenance.source_attempt_id, provenance.target_prerequisite_concept_id)
        if identity in seen:
            if seen[identity] != provenance:
                raise MasteryEvidenceConflictError("Conflicting duplicate diagnostic inference")
            continue
        seen[identity] = provenance
        rows.append(await _persist_diagnostic_inference(
            session, provenance, validation_time=validation_time,
        ))
    return tuple(rows)


def _validate_concept_event(
    concept_event: ConceptLearningEventInput,
    evidence: EvidenceInput,
) -> None:
    if concept_event.type == LearningEventType.ANSWER_GRADED and (
        concept_event.source_evidence_id != evidence.evidence_id
        or concept_event.source_attempt_id != evidence.attempt_id
    ):
        raise MasteryValidationError(
            "Qualifying answer-grading events require matching evidence and attempt IDs"
        )
    if (
        concept_event.learner_id != evidence.learner_id
        or concept_event.course_id != evidence.course_id
        or set(concept_event.stable_concept_ids)
        != {item.stable_concept_id for item in evidence.concept_roles}
    ):
        raise MasteryValidationError("Concept event source context does not match evidence")
    if concept_event.source_evidence_id not in (None, evidence.evidence_id):
        raise MasteryValidationError("Concept event source evidence does not match")


async def _concept_events(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
) -> list[ConceptLearningEventInput]:
    rows = (await session.execute(
        select(LearningEventRecord, LearningEventConceptAssociation).join(
            LearningEventConceptAssociation,
            LearningEventConceptAssociation.event_id == LearningEventRecord.event_id,
        ).where(
            LearningEventConceptAssociation.learner_identity_id == learner_id,
            LearningEventConceptAssociation.course_id == course_id,
            LearningEventRecord.event_schema_version == "learning-event-v2",
        ).order_by(
            LearningEventRecord.occurred_at,
            LearningEventRecord.event_id,
        )
    )).all()
    grouped: dict[UUID, tuple[LearningEventRecord, list[UUID]]] = {}
    for event_row, association in rows:
        current = grouped.get(event_row.event_id)
        if current is None:
            grouped[event_row.event_id] = (event_row, [association.stable_concept_id])
        else:
            current[1].append(association.stable_concept_id)
    result: list[ConceptLearningEventInput] = []
    for event_row, concept_ids in grouped.values():
        if event_row.actor_identity_id is None or event_row.occurred_at is None:
            continue
        payload = event_row.payload
        result.append(ConceptLearningEventInput(
            event_id=event_row.event_id,
            type=LearningEventType(event_row.event_type),
            actor_id=event_row.actor_identity_id,
            actor_subject=event_row.actor_subject,
            learner_id=learner_id,
            course_id=event_row.course_id,
            occurred_at=event_row.occurred_at,
            payload=LearningEventPayload(
                schema_version="learning-payload-v1",
                kind=str(payload["kind"]),
                data=cast(dict[str, object], payload["data"]),
            ),
            correlation_id=event_row.correlation_id,
            causation_id=event_row.causation_id,
            idempotency_key=event_row.idempotency_key or str(event_row.event_id),
            stable_concept_ids=tuple(sorted(set(concept_ids), key=lambda value: value.bytes)),
            source_evidence_id=(
                UUID(str(payload["source_evidence_id"]))
                if payload.get("source_evidence_id") else None
            ),
            source_attempt_id=(
                UUID(str(payload["source_attempt_id"]))
                if payload.get("source_attempt_id") else None
            ),
        ))
    return result


async def _self_report_priors(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
) -> list[SelfReportPriorContribution]:
    rows = (await session.scalars(select(SelfReportAssertionRecord).where(
        SelfReportAssertionRecord.learner_identity_id == learner_id,
        SelfReportAssertionRecord.course_id == course_id,
    ).order_by(SelfReportAssertionRecord.id))).all()
    return [SelfReportPriorContribution(
        assertion_id=row.id,
        learner_id=row.learner_identity_id,
        course_id=row.course_id,
        stable_concept_id=row.stable_concept_id,
        graph_version_id=row.graph_version_id,
        occurred_at=row.occurred_at,
        alpha_delta=row.alpha_delta,
        beta_delta=row.beta_delta,
        policy_version=row.policy_version,
    ) for row in rows]


async def record_self_report_assertion(
    session: AsyncSession,
    assertion: SelfReportAssertion,
    *,
    actor_subject: str | None = None,
) -> SelfReportAssertionRecord:
    """Insert one immutable self-report assertion without committing."""

    actor = await session.get(StudentIdentity, assertion.actor_id)
    if actor is None:
        raise MasteryValidationError("Self-report actor identity does not exist")
    if actor_subject is not None and actor.external_subject != actor_subject:
        raise MasteryValidationError("Self-report actor does not match authenticated subject")
    if actor_subject is None and assertion.actor_id != assertion.learner_id:
        raise MasteryValidationError("Delegated self-report requires authorization context")
    if actor_subject is not None:
        member = await session.scalar(select(CourseMember).where(
            CourseMember.course_id == assertion.course_id,
            CourseMember.subject == actor_subject,
        ))
        if member is None:
            raise MasteryValidationError("Course membership is required for self-report")
    if assertion.graph_version_id is not None:
        graph = await session.get(CurriculumGraphVersion, assertion.graph_version_id)
        if (
            graph is None
            or graph.course_id != assertion.course_id
            or graph.status != "PUBLISHED"
            or graph.published_at is None
        ):
            raise MasteryValidationError("Self-report requires a published course graph")
        concept_exists = await session.scalar(select(CurriculumGraphConcept.id).where(
            CurriculumGraphConcept.graph_id == assertion.graph_version_id,
            CurriculumGraphConcept.stable_concept_id == assertion.stable_concept_id,
        ))
        if concept_exists is None:
            raise MasteryValidationError("Self-report concept is absent from its graph version")
    existing = await session.scalar(select(SelfReportAssertionRecord).where(
        (SelfReportAssertionRecord.id == assertion.assertion_id)
        | (SelfReportAssertionRecord.idempotency_key == assertion.idempotency_key)
    ).with_for_update())
    if existing is not None:
        logical_match = (
            existing.id == assertion.assertion_id
            and existing.learner_identity_id == assertion.learner_id
            and existing.actor_identity_id == assertion.actor_id
            and existing.course_id == assertion.course_id
            and existing.stable_concept_id == assertion.stable_concept_id
            and existing.graph_version_id == assertion.graph_version_id
            and existing.occurred_at == assertion.occurred_at
            and existing.policy_version == assertion.policy_version
        )
        if not logical_match:
            raise MasteryEvidenceConflictError("Conflicting self-report assertion reuse")
        return existing
    concept_existing = await session.scalar(select(SelfReportAssertionRecord).where(
        SelfReportAssertionRecord.learner_identity_id == assertion.learner_id,
        SelfReportAssertionRecord.course_id == assertion.course_id,
        SelfReportAssertionRecord.stable_concept_id == assertion.stable_concept_id,
    ).with_for_update())
    if concept_existing is not None:
        raise MasteryEvidenceConflictError(
            "A self-report prior already exists for this learner/course/concept"
        )
    row = SelfReportAssertionRecord(
        id=assertion.assertion_id,
        learner_identity_id=assertion.learner_id,
        actor_identity_id=assertion.actor_id,
        course_id=assertion.course_id,
        stable_concept_id=assertion.stable_concept_id,
        graph_version_id=assertion.graph_version_id,
        occurred_at=assertion.occurred_at,
        idempotency_key=assertion.idempotency_key,
        policy_version=assertion.policy_version,
        alpha_delta=1.0,
        beta_delta=0.0,
    )
    session.add(row)
    await session.flush()
    return row


async def _current_projection_ids(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    concept_ids: Sequence[UUID],
) -> tuple[UUID, ...]:
    rows = (await session.scalars(select(MasteryProjectionHead).where(
        MasteryProjectionHead.learner_identity_id == learner_id,
        MasteryProjectionHead.course_id == course_id,
        MasteryProjectionHead.stable_concept_id.in_(concept_ids),
    ))).all()
    return tuple(sorted((row.current_projection_id for row in rows), key=lambda value: value.bytes))


def _projection_domain(row: MasteryProjectionRevision) -> ConceptMastery:
    state = MasteryState(
        alpha=row.alpha,
        beta=row.beta,
        n_direct=row.n_direct,
        distinct_direct_question_ids=tuple(
            UUID(value) for value in row.distinct_direct_question_ids
        ),
        review_successes=row.review_successes,
        review_rung=row.review_rung,
        has_qualifying_review=row.review_successes > 0,
        last_successful_review_at=row.last_successful_review_at,
        last_successful_review_evidence_id=row.last_successful_review_evidence_id,
        last_successful_review_event_id=row.last_successful_review_event_id,
        last_occurred_at=row.as_of,
    )
    return ConceptMastery(
        stable_concept_id=row.stable_concept_id,
        state=state,
        metrics=MasteryMetrics(
            n_eff=row.n_eff,
            mastery=row.mastery,
            confidence=row.confidence,
            status=cast(
                Literal["UNASSESSED", "WEAK", "DEVELOPING", "PROFICIENT", "MASTERED"],
                row.status,
            ),
        ),
    )


async def get_current_projection(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    stable_concept_id: UUID,
    *,
    as_of: datetime,
) -> ConceptMastery | None:
    """Read the current head and apply lazy forgetting transiently."""

    head = await session.scalar(select(MasteryProjectionHead).where(
        MasteryProjectionHead.learner_identity_id == learner_id,
        MasteryProjectionHead.course_id == course_id,
        MasteryProjectionHead.stable_concept_id == stable_concept_id,
    ))
    if head is None:
        return None
    revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
    if revision is None:
        raise RuntimeError("Projection head points to a missing revision")
    domain = _projection_domain(revision)
    state = decay_state(domain.state, as_of)
    return ConceptMastery(
        stable_concept_id=stable_concept_id,
        state=state,
        metrics=metrics_for(state, state.has_qualifying_review),
    )


async def list_projection_revisions(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    stable_concept_id: UUID,
) -> list[MasteryProjectionRevision]:
    """List immutable revisions without creating a read-time revision."""

    return list((await session.scalars(select(MasteryProjectionRevision).where(
        MasteryProjectionRevision.learner_identity_id == learner_id,
        MasteryProjectionRevision.course_id == course_id,
        MasteryProjectionRevision.stable_concept_id == stable_concept_id,
    ).order_by(MasteryProjectionRevision.projection_version))).all())


async def _persist_replay(
    session: AsyncSession,
    replay_result: ReplayResult,
    *,
    learner_id: UUID,
    course_id: UUID,
    rebuild_reason: str,
    replayed_at: datetime,
) -> tuple[UUID, ...]:
    projection_ids: list[UUID] = []
    for projection in replay_result.projections:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == learner_id,
            MasteryProjectionHead.course_id == course_id,
            MasteryProjectionHead.stable_concept_id == projection.stable_concept_id,
        ).with_for_update().execution_options(populate_existing=True))
        if head is not None:
            current = await session.get(MasteryProjectionRevision, head.current_projection_id)
            if current is not None and (
                current.evidence_set_digest == replay_result.evidence_set_digest
                and current.as_of == replay_result.as_of
                and current.alpha == projection.state.alpha
                and current.beta == projection.state.beta
                and current.review_successes == projection.state.review_successes
                and current.review_rung == projection.state.review_rung
                and current.last_successful_review_at
                == projection.state.last_successful_review_at
                and current.last_successful_review_evidence_id
                == projection.state.last_successful_review_evidence_id
                and current.last_successful_review_event_id
                == projection.state.last_successful_review_event_id
            ):
                projection_ids.append(current.id)
                continue
            version = head.current_projection_version + 1
        else:
            version = 1
        revision = MasteryProjectionRevision(
            id=uuid4(),
            learner_identity_id=learner_id,
            course_id=course_id,
            stable_concept_id=projection.stable_concept_id,
            projection_version=version,
            policy_version="mastery_v1",
            as_of=replay_result.as_of,
            replayed_at=replayed_at,
            evidence_set_digest=replay_result.evidence_set_digest,
            evidence_count=replay_result.evidence_count,
            max_occurred_at=replay_result.max_occurred_at,
            max_evidence_id=replay_result.max_evidence_id,
            alpha=projection.state.alpha,
            beta=projection.state.beta,
            n_eff=projection.metrics.n_eff,
            mastery=projection.metrics.mastery,
            confidence=projection.metrics.confidence,
            status=projection.metrics.status,
            n_direct=projection.state.n_direct,
            distinct_direct_question_ids=[
                str(value) for value in projection.state.distinct_direct_question_ids
            ],
            review_successes=projection.state.review_successes,
            review_rung=projection.state.review_rung,
            last_successful_review_at=projection.state.last_successful_review_at,
            last_successful_review_evidence_id=projection.state.last_successful_review_evidence_id,
            last_successful_review_event_id=projection.state.last_successful_review_event_id,
            rebuild_reason=rebuild_reason,
        )
        session.add(revision)
        await session.flush()
        if head is None:
            session.add(MasteryProjectionHead(
                id=uuid4(), learner_identity_id=learner_id, course_id=course_id,
                stable_concept_id=projection.stable_concept_id,
                current_projection_id=revision.id,
                current_projection_version=version,
            ))
        else:
            head.current_projection_id = revision.id
            head.current_projection_version = version
        projection_ids.append(revision.id)
        for contribution in replay_result.contributions:
            if contribution.stable_concept_id != projection.stable_concept_id:
                continue
            evidence_row = await session.get(MasteryEvidenceRecord, contribution.evidence_id)
            if evidence_row is None:
                continue
            session.add(MasteryContributionRecord(
                projection_id=revision.id,
                evidence_id=contribution.evidence_id,
                learner_identity_id=learner_id,
                course_id=course_id,
                stable_concept_id=contribution.stable_concept_id,
                alpha_delta=contribution.alpha_delta,
                beta_delta=contribution.beta_delta,
                applied=contribution.applied,
                reason=contribution.reason,
            ))
    await session.flush()
    return tuple(sorted(projection_ids, key=lambda value: value.bytes))


async def _duplicate_mastery_result(
    session: AsyncSession,
    evidence: EvidenceInput,
    inferences: Sequence[DiagnosticInferenceProvenance],
) -> MasteryUpdateResult:
    concept_ids = sorted({
        *(item.stable_concept_id for item in evidence.concept_roles),
        *(item.target_prerequisite_concept_id for item in inferences),
    }, key=lambda item: item.bytes)
    projection_ids = await _current_projection_ids(
        session, evidence.learner_id, evidence.course_id, concept_ids,
    )
    rows = (await session.scalars(select(MasteryProjectionRevision).where(
        MasteryProjectionRevision.id.in_(projection_ids),
    ))).all()
    return MasteryUpdateResult(
        evidence_id=evidence.evidence_id, projection_ids=projection_ids,
        projections=tuple(_projection_domain(row) for row in rows), duplicate=True,
    )


async def _replay_accepted_course(
    session: AsyncSession,
    evidence: EvidenceInput,
    *,
    validation_time: datetime,
    rebuild_reason: str,
    duplicate: bool,
) -> MasteryUpdateResult:
    all_rows = (await session.scalars(select(MasteryEvidenceRecord).where(
        MasteryEvidenceRecord.learner_identity_id == evidence.learner_id,
        MasteryEvidenceRecord.course_id == evidence.course_id,
    ).order_by(MasteryEvidenceRecord.occurred_at, MasteryEvidenceRecord.id))).all()
    records = [_evidence_from_row(item) for item in all_rows]
    events = await _concept_events(session, evidence.learner_id, evidence.course_id)
    priors = await _self_report_priors(session, evidence.learner_id, evidence.course_id)
    replay_result = pure_replay(records, validation_time, events, priors)
    projection_ids = await _persist_replay(
        session, replay_result, learner_id=evidence.learner_id,
        course_id=evidence.course_id, rebuild_reason=rebuild_reason,
        replayed_at=validation_time,
    )
    await sync_review_schedules_for_replay(
        session, replay_result, learner_id=evidence.learner_id,
        course_id=evidence.course_id, concept_events=events,
        graph_version_id=evidence.graph_version_id,
    )
    for row in all_rows:
        if row.applied_at is None:
            row.applied_at = validation_time
    await session.flush()
    return MasteryUpdateResult(
        evidence_id=evidence.evidence_id, projection_ids=projection_ids,
        projections=replay_result.projections, duplicate=duplicate,
    )


async def apply_evidence(
    session: AsyncSession,
    evidence: EvidenceInput,
    *,
    actor_subject: str | None = None,
    concept_event: ConceptLearningEventInput | None = None,
    diagnostic_inferences: Sequence[DiagnosticInferenceProvenance] = (),
    rebuild_reason: str = "EVIDENCE_APPLICATION",
) -> MasteryUpdateResult:
    """Validate, persist and replay evidence inside the caller transaction.

    Diagnostic requests attach to this direct source; their derived roles do
    not reinterpret the question's immutable role snapshot.
    """

    await _lock_mastery_learner(session, evidence.learner_id)
    validation_time = await _db_clock(session)
    if evidence.diagnostic_provenance is not None:
        raise MasteryValidationError(
            "Submit diagnostic inference provenance with its original direct source evidence"
        )
    if evidence.occurred_at > validation_time:
        raise MasteryValidationError("Evidence cannot occur in the future")
    if evidence.actor_id is not None:
        actor = await session.get(StudentIdentity, evidence.actor_id)
        if actor is None:
            raise MasteryValidationError("Evidence actor identity does not exist")
        if actor_subject is not None and actor.external_subject != actor_subject:
            raise MasteryValidationError("Evidence actor does not match authenticated subject")
        if actor_subject is None and evidence.actor_id != evidence.learner_id:
            raise MasteryValidationError("Delegated evidence requires authorization context")
        if actor_subject is not None:
            member = await session.scalar(select(CourseMember).where(
                CourseMember.course_id == evidence.course_id,
                CourseMember.subject == actor_subject,
            ))
            if member is None:
                raise MasteryValidationError("Course membership is required for evidence")
    for provenance in diagnostic_inferences:
        if (
            provenance.learner_id != evidence.learner_id
            or provenance.source_evidence_id != evidence.evidence_id
            or provenance.source_attempt_id != evidence.attempt_id
            or provenance.source_question_version_id != evidence.question_version_id
            or provenance.source_graph_version_id != evidence.graph_version_id
        ):
            raise MasteryValidationError(
                "Diagnostic inference must reference the accepted source evidence"
            )

    existing = await session.scalar(select(MasteryEvidenceRecord).where(
        (MasteryEvidenceRecord.id == evidence.evidence_id)
        | (MasteryEvidenceRecord.idempotency_key == evidence.idempotency_key)
    ).with_for_update().execution_options(populate_existing=True))
    if existing is not None:
        if not _same_evidence(existing, evidence):
            raise MasteryEvidenceConflictError("Conflicting evidence reuse")
        if concept_event is None and not diagnostic_inferences:
            return await _duplicate_mastery_result(session, evidence, diagnostic_inferences)
        if concept_event is not None:
            _validate_concept_event(concept_event, evidence)
            event_existing = await session.scalar(select(LearningEventRecord).where(
                LearningEventRecord.idempotency_key == concept_event.idempotency_key,
            ))
            await insert_concept_learning_event(
                session, concept_event, validation_db_at=validation_time,
            )
            event_was_new = event_existing is None
        else:
            event_was_new = False
        inference_rows = await _persist_diagnostic_inferences(
            session, diagnostic_inferences, validation_time=validation_time,
        )
        inference_was_new = any(row.applied_at is None for row in inference_rows)
        if not event_was_new and not inference_was_new:
            return await _duplicate_mastery_result(session, evidence, diagnostic_inferences)
        return await _replay_accepted_course(
            session, evidence, validation_time=validation_time,
            rebuild_reason=rebuild_reason, duplicate=True,
        )

    question = await session.get(MasteryQuestionVersion, evidence.question_version_id)
    attempt = await session.get(MasteryAttempt, evidence.attempt_id)
    graph = await session.get(CurriculumGraphVersion, evidence.graph_version_id)
    if question is None or attempt is None or graph is None:
        raise MasteryValidationError("Evidence source context does not exist")
    if question.question_id != evidence.question_id or question.course_id != evidence.course_id:
        raise MasteryValidationError("Evidence question context conflicts")
    if question.graph_version_id != evidence.graph_version_id:
        raise MasteryValidationError("Evidence graph context conflicts with question version")
    if sorted(question.concept_roles, key=str) != sorted(
        _roles_json(evidence.concept_roles), key=str,
    ):
        raise MasteryValidationError("Evidence concept roles conflict with question version")
    if (
        attempt.learner_identity_id != evidence.learner_id
        or attempt.course_id != evidence.course_id
    ):
        raise MasteryValidationError("Evidence learner/course conflicts with attempt")
    if attempt.question_version_id != evidence.question_version_id:
        raise MasteryValidationError("Evidence attempt/question relationship conflicts")
    if (
        attempt.graph_version_id != evidence.graph_version_id
        or attempt.is_review != evidence.is_review
    ):
        raise MasteryValidationError("Evidence attempt snapshot conflicts")
    if graph.status != "PUBLISHED" or graph.published_at is None:
        raise MasteryValidationError("Evidence requires a published graph")
    concept_ids = [item.stable_concept_id for item in evidence.concept_roles]
    graph_concept_ids = set((await session.scalars(select(
        CurriculumGraphConcept.stable_concept_id,
    ).where(
        CurriculumGraphConcept.graph_id == evidence.graph_version_id,
        CurriculumGraphConcept.stable_concept_id.in_(concept_ids),
    ))).all())
    if graph_concept_ids != set(concept_ids):
        raise MasteryValidationError("Evidence contains a concept absent from its graph version")
    if graph.published_at > attempt.occurred_at or graph.published_at > evidence.occurred_at:
        raise MasteryValidationError("Evidence occurs before graph publication")
    if question.available_at > attempt.occurred_at or attempt.occurred_at > evidence.occurred_at:
        raise MasteryValidationError("Evidence occurrence ordering is invalid")
    if question.is_review != evidence.is_review:
        raise MasteryValidationError("Evidence review marker conflicts with question version")
    stored_weight = calculate_weight_snapshot(evidence)
    row = MasteryEvidenceRecord(
        id=evidence.evidence_id,
        learner_identity_id=evidence.learner_id,
        actor_identity_id=evidence.actor_id,
        course_id=evidence.course_id,
        question_id=evidence.question_id,
        question_version_id=evidence.question_version_id,
        attempt_id=evidence.attempt_id,
        graph_version_id=evidence.graph_version_id,
        correct=evidence.correct,
        difficulty=evidence.difficulty,
        question_type=evidence.question_type,
        n_options=evidence.n_options,
        hints_used=evidence.hints_used,
        grader_level=evidence.grader_level,
        grader_confidence=evidence.grader_confidence,
        kind=evidence.kind,
        occurred_at=evidence.occurred_at,
        recorded_at=validation_time,
        is_review=evidence.is_review,
        tag_confidence=evidence.tag_confidence,
        concept_roles=_roles_json(evidence.concept_roles),
        weight_snapshot=stored_weight.model_dump(mode="json"),
        diagnostic_provenance=(
            None if evidence.diagnostic_provenance is None
            else evidence.diagnostic_provenance.model_dump(mode="json")
        ),
        idempotency_key=evidence.idempotency_key,
    )
    session.add(row)
    await session.flush()
    if concept_event is not None:
        _validate_concept_event(concept_event, evidence)
        await insert_concept_learning_event(
            session, concept_event, validation_db_at=validation_time,
        )
    await _persist_diagnostic_inferences(
        session, diagnostic_inferences, validation_time=validation_time,
    )
    return await _replay_accepted_course(
        session, evidence, validation_time=validation_time,
        rebuild_reason=rebuild_reason, duplicate=False,
    )


async def apply_self_report(
    session: AsyncSession,
    assertion: SelfReportAssertion,
    *,
    actor_subject: str | None = None,
    rebuild_reason: str = "SELF_REPORT_PRIOR",
) -> MasteryUpdateResult:
    """Persist one self-report and replay the learner/course atomically."""

    await _lock_mastery_learner(session, assertion.learner_id)
    validation_time = await _db_clock(session)
    if assertion.occurred_at > validation_time:
        raise MasteryValidationError("Self-report cannot occur in the future")
    existing = await session.scalar(select(SelfReportAssertionRecord).where(
        (SelfReportAssertionRecord.id == assertion.assertion_id)
        | (SelfReportAssertionRecord.idempotency_key == assertion.idempotency_key)
    ).with_for_update())
    await record_self_report_assertion(session, assertion, actor_subject=actor_subject)
    if existing is not None:
        projection_ids = await _current_projection_ids(
            session,
            assertion.learner_id,
            assertion.course_id,
            [assertion.stable_concept_id],
        )
        rows = tuple((await session.scalars(select(MasteryProjectionRevision).where(
            MasteryProjectionRevision.id.in_(projection_ids),
        ))).all())
        return MasteryUpdateResult(
            evidence_id=assertion.assertion_id,
            projection_ids=projection_ids,
            projections=tuple(_projection_domain(row) for row in rows),
            duplicate=True,
        )
    all_rows = (await session.scalars(select(MasteryEvidenceRecord).where(
        MasteryEvidenceRecord.learner_identity_id == assertion.learner_id,
        MasteryEvidenceRecord.course_id == assertion.course_id,
    ).order_by(MasteryEvidenceRecord.occurred_at, MasteryEvidenceRecord.id))).all()
    records = [_evidence_from_row(item) for item in all_rows]
    events = await _concept_events(session, assertion.learner_id, assertion.course_id)
    priors = await _self_report_priors(session, assertion.learner_id, assertion.course_id)
    replay_result = pure_replay(records, validation_time, events, priors)
    projection_ids = await _persist_replay(
        session,
        replay_result,
        learner_id=assertion.learner_id,
        course_id=assertion.course_id,
        rebuild_reason=rebuild_reason,
        replayed_at=validation_time,
    )
    await sync_review_schedules_for_replay(
        session,
        replay_result,
        learner_id=assertion.learner_id,
        course_id=assertion.course_id,
        concept_events=events,
        graph_version_id=assertion.graph_version_id,
    )
    return MasteryUpdateResult(
        evidence_id=assertion.assertion_id,
        projection_ids=projection_ids,
        projections=replay_result.projections,
    )
