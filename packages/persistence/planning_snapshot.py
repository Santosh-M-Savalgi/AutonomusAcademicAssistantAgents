"""Stage 5 authoritative read assembler with learner-first coherence fences."""

import json
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.curriculum.diagnostics import select_diagnostic_candidates
from packages.domain.adaptation import (
    AssessmentPlanningState,
    DiagnosticCandidate,
    DiagnosticConceptState,
    DiagnosticState,
    PlanningDirective,
    PlanningGraphContext,
    ProjectionFreshness,
    ProjectionFreshnessResult,
    RemediationFrame,
)
from packages.domain.graph import GraphNodeType
from packages.domain.runtime import LearningSessionSnapshot, SessionState
from packages.domain.runtime_state import AssessmentBatch, RuntimeDirective, TopicWindow
from packages.domain.snapshot import AuthoritativePlanningSnapshot
from packages.domain.triggers import GuardCode, TriggerEvaluation
from packages.persistence.graphs import _graph_rows, _snapshot_from_rows
from packages.persistence.models import (
    CurriculumGraphConcept,
    CurriculumGraphMapping,
    CurriculumGraphNode,
    CurriculumGraphVersion,
    MasteryEvidenceRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    MasteryQuestionVersion,
)
from packages.persistence.review_schedule import select_persisted_review_candidates
from packages.persistence.runtime import RuntimeStaleError, lock_runtime_learner
from packages.persistence.runtime_models import (
    DiagnosticRunRecord,
    LearningPlanVersionRecord,
    LearningSessionRecord,
    RemediationFrameRecord,
)
from packages.persistence.runtime_support_models import (
    AssessmentBatchRecord,
    RuntimeDirectiveRecord,
    TopicWindowRecord,
)


class SnapshotUnavailableError(ValueError):
    """The requested coherent snapshot cannot be assembled from authoritative facts."""


async def _current_graph(
    session: AsyncSession, course_id: UUID,
) -> CurriculumGraphVersion | None:
    value = await session.scalar(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.course_id == course_id,
        CurriculumGraphVersion.status == "PUBLISHED",
    ).order_by(CurriculumGraphVersion.created_at.desc(), CurriculumGraphVersion.id).limit(1)
      .execution_options(populate_existing=True))
    return value


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


async def _frame_contract(row: RemediationFrameRecord) -> RemediationFrame:
    return RemediationFrame(
        frame_id=row.id,
        target_concept_id=row.target_concept_id,
        return_to_topic_id=row.return_to_topic_id,
        complete=row.state == "COMPLETE",
        evidence_ids=(),
        confidence=row.latest_mastery,
    )


async def assemble_planning_snapshot(
    session: AsyncSession,
    learner_id: UUID,
    session_id: UUID,
    *,
    as_of: datetime,
    trigger: TriggerEvaluation | None = None,
) -> AuthoritativePlanningSnapshot:
    """Read one fenced planning view; never creates revisions, plans or events."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Snapshot time must be timezone-aware")
    await lock_runtime_learner(session, learner_id)
    session_row = await session.scalar(select(LearningSessionRecord).where(
        LearningSessionRecord.id == session_id,
    ).with_for_update().execution_options(populate_existing=True))
    if session_row is None or session_row.learner_identity_id != learner_id:
        raise SnapshotUnavailableError("Session is missing or belongs to another learner")

    graph = await _current_graph(session, session_row.course_id)
    guards: list[GuardCode] = []
    if session_row.state == "COMPLETE":
        guards.append(GuardCode.TERMINAL_SESSION)
    if graph is None:
        guards.append(GuardCode.MISSING_GRAPH_CONTEXT)
    elif session_row.graph_version_id != graph.id:
        guards.append(GuardCode.STALE_GRAPH)
    if session_row.current_topic_id is not None and graph is not None and (
        await session.scalar(select(CurriculumGraphNode.id).where(
            CurriculumGraphNode.graph_id == graph.id,
            CurriculumGraphNode.stable_node_id == session_row.current_topic_id,
            CurriculumGraphNode.node_type == GraphNodeType.TOPIC.value,
        )) is None
    ):
        guards.append(GuardCode.MISSING_GRAPH_CONTEXT)

    session_value = LearningSessionSnapshot(
        session_id=session_row.id,
        learner_id=session_row.learner_identity_id,
        course_id=session_row.course_id,
        state=SessionState(session_row.state),
        version=session_row.version,
        graph_version_id=session_row.graph_version_id,
        current_topic_id=session_row.current_topic_id,
        current_plan_version_id=session_row.current_plan_version_id,
        active_frame_id=session_row.active_frame_id,
        last_event_id=session_row.last_event_id,
        created_at=session_row.created_at,
        updated_at=session_row.updated_at,
        completed_at=session_row.completed_at,
    )

    topic_window = None
    if session_row.current_topic_id is not None:
        topic_window = await session.scalar(select(TopicWindowRecord).where(
            TopicWindowRecord.session_id == session_id,
            TopicWindowRecord.closed_at.is_(None),
        ).execution_options(populate_existing=True))
    topic_value = None if topic_window is None else TopicWindow.model_validate_json(
        topic_window.value_bytes,
    )
    if session_row.current_topic_id is not None and topic_value is None:
        guards.append(GuardCode.UNAVAILABLE_REQUIRED_STATE)

    concept_ids: tuple[UUID, ...] = ()
    if graph is not None and session_row.current_topic_id is not None:
        concept_values = (await session.scalars(select(CurriculumGraphMapping.concept_id).where(
            CurriculumGraphMapping.graph_id == graph.id,
            CurriculumGraphMapping.topic_id == session_row.current_topic_id,
        ))).all()
        concept_ids = tuple(sorted(concept_values, key=lambda item: item.bytes))

    evidence_rows = (await session.scalars(select(MasteryEvidenceRecord).where(
        MasteryEvidenceRecord.learner_identity_id == learner_id,
        MasteryEvidenceRecord.course_id == session_row.course_id,
    ).order_by(MasteryEvidenceRecord.occurred_at, MasteryEvidenceRecord.id)
      .execution_options(populate_existing=True))).all()
    evidence_count = len(evidence_rows)
    evidence_digest = None
    if evidence_rows:
        from packages.mastery.engine import _digest
        from packages.persistence.mastery import _evidence_from_row
        evidence_digest = _digest([_evidence_from_row(row) for row in evidence_rows], ())

    freshness: list[ProjectionFreshnessResult] = []
    revision_ids: list[UUID] = []
    for concept_id in concept_ids:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == learner_id,
            MasteryProjectionHead.course_id == session_row.course_id,
            MasteryProjectionHead.stable_concept_id == concept_id,
        ).execution_options(populate_existing=True))
        if head is None:
            guards.append(GuardCode.MISSING_PROJECTION)
            freshness.append(ProjectionFreshnessResult(
                learner_id=learner_id, course_id=session_row.course_id,
                stable_concept_id=concept_id, state=ProjectionFreshness.MISSING_PROJECTION,
            ))
            continue
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id,
                                     populate_existing=True)
        if revision is None:
            guards.append(GuardCode.MISSING_REVISION)
            freshness.append(ProjectionFreshnessResult(
                learner_id=learner_id, course_id=session_row.course_id,
                stable_concept_id=concept_id, state=ProjectionFreshness.MISSING_REVISION,
                projection_head_id=head.id,
            ))
            continue
        revision_ids.append(revision.id)
        state = ProjectionFreshness.FRESH
        concept_graph_ids = {
            row.graph_version_id for row in evidence_rows
            if any(str(role.get("stable_concept_id")) == str(concept_id)
                   for role in row.concept_roles)
        }
        if graph is not None and concept_graph_ids and concept_graph_ids != {graph.id}:
            state = ProjectionFreshness.GRAPH_CONTEXT_STALE
            guards.append(GuardCode.STALE_GRAPH)
        if evidence_digest is not None and revision.evidence_set_digest != evidence_digest:
            state = ProjectionFreshness.EVIDENCE_SET_STALE
            guards.append(GuardCode.STALE_EVIDENCE_SET)
        freshness.append(ProjectionFreshnessResult(
            learner_id=learner_id, course_id=session_row.course_id,
            stable_concept_id=concept_id, state=state, projection_head_id=head.id,
            projection_revision_id=revision.id,
            expected_evidence_set_digest=evidence_digest,
            observed_evidence_set_digest=revision.evidence_set_digest,
            expected_graph_version_id=session_row.graph_version_id,
            observed_graph_version_id=(
                min(concept_graph_ids, key=lambda item: item.bytes) if concept_graph_ids else None
            ),
        ))

    review = await select_persisted_review_candidates(
        session, learner_id, session_row.course_id, as_of=as_of,
        active_remediation=session_row.active_frame_id is not None,
    )
    guards.extend(
        GuardCode.STALE_EVIDENCE_SET
        for item in review.unavailable
        if item.state == ProjectionFreshness.EVIDENCE_SET_STALE
    )

    frame_value: RemediationFrame | None = None
    frame_version: int | None = None
    if session_row.active_frame_id is not None:
        frame = await session.get(RemediationFrameRecord, session_row.active_frame_id,
                                  populate_existing=True)
        if frame is None:
            guards.append(GuardCode.UNAVAILABLE_REQUIRED_STATE)
        else:
            frame_value = await _frame_contract(frame)
            frame_version = frame.version

    topic_state = None
    if topic_value is not None:
        from packages.domain.adaptation import TopicPlanningState
        topic_state = TopicPlanningState(
            topic_id=topic_value.topic_id,
            core_concept_ids=topic_value.core_concept_ids,
            authorized=topic_value.authorized,
            taught=topic_value.taught,
            checked=topic_value.checked,
            quiz_completed=topic_value.quiz_completed,
            prerequisites_evaluated=topic_value.prerequisites_evaluated,
            prerequisite_gates=topic_value.prerequisite_gates or (),
            gate_satisfied=topic_value.gate_satisfied,
            next_topic_id=topic_value.next_topic_id,
            evidence_ids=topic_value.evidence_ids,
            confidence=topic_value.confidence,
        )

    latest_assessment = None
    if topic_value is not None:
        batch_rows = (await session.scalars(select(AssessmentBatchRecord).where(
            AssessmentBatchRecord.window_id == topic_value.window_id,
        ))).all()
        batches = [AssessmentBatch.model_validate_json(row.value_bytes) for row in batch_rows]
        if batches:
            batch = max(batches, key=lambda item: (item.completed_at, item.batch_id.bytes))
            if batch.kind.value == "QUIZ":
                latest_assessment = AssessmentPlanningState(
                    topic_id=topic_value.topic_id,
                    failing_concept_ids=batch.failing_concept_ids or topic_value.core_concept_ids,
                    evidence_ids=batch.evidence_ids,
                    confidence=batch.confidence,
                )

    plan_version = 1
    if session_row.current_plan_version_id is not None:
        plan = await session.get(LearningPlanVersionRecord, session_row.current_plan_version_id,
                                 populate_existing=True)
        if plan is None:
            guards.append(GuardCode.UNAVAILABLE_REQUIRED_STATE)
        else:
            # The snapshot carries the deterministic successor version that the
            # next publication is authorized to claim.
            plan_version = plan.version + 1

    directive_values: list[PlanningDirective] = []
    directive_rows = (await session.scalars(select(RuntimeDirectiveRecord).where(
        RuntimeDirectiveRecord.session_id == session_id,
    ).order_by(RuntimeDirectiveRecord.id))).all()
    for row in directive_rows:
        directive = RuntimeDirective.model_validate_json(row.value_bytes)
        if directive.state.value == "PENDING" and directive.valid_from <= as_of and (
            directive.expires_at is None or as_of < directive.expires_at
        ):
            directive_values.append(directive.directive)

    graph_context = None
    diagnostic_state: DiagnosticState | None = None
    diagnostic_candidates: tuple[DiagnosticCandidate, ...] = ()
    if graph is not None:
        topic_values = (await session.scalars(select(CurriculumGraphNode.stable_node_id).where(
            CurriculumGraphNode.graph_id == graph.id,
            CurriculumGraphNode.node_type == GraphNodeType.TOPIC.value,
        ))).all()
        concept_values = (await session.scalars(
            select(CurriculumGraphConcept.stable_concept_id).where(
                CurriculumGraphConcept.graph_id == graph.id,
            )
        )).all()
        graph_context = PlanningGraphContext(
            course_id=session_row.course_id,
            graph_version_id=graph.id,
            current_graph_version_id=graph.id,
            topic_ids=tuple(sorted(topic_values, key=lambda item: item.bytes)),
            concept_ids=tuple(sorted(concept_values, key=lambda item: item.bytes)),
        )
        run = await session.scalar(select(DiagnosticRunRecord).where(
            DiagnosticRunRecord.session_id == session_id,
            DiagnosticRunRecord.state == "OPEN",
        ).order_by(DiagnosticRunRecord.created_at.desc()).limit(1))
        if run is not None:
            try:
                rows = await _graph_rows(session, graph)
                graph_definition = _snapshot_from_rows(graph, *rows)
            except (TypeError, ValueError):
                guards.append(GuardCode.UNAVAILABLE_REQUIRED_STATE)
            else:
                question_rows = (await session.scalars(select(MasteryQuestionVersion).where(
                    MasteryQuestionVersion.graph_version_id == graph.id,
                    MasteryQuestionVersion.course_id == session_row.course_id,
                ))).all()
                question_ids: dict[UUID, tuple[UUID, ...]] = {}
                for question in question_rows:
                    for role in question.concept_roles:
                        concept_id = UUID(str(role["stable_concept_id"]))
                        question_ids[concept_id] = (
                            *question_ids.get(concept_id, ()), question.id,
                        )
                concept_states = {
                    concept_id: DiagnosticConceptState(stable_concept_id=concept_id, confidence=0)
                    for concept_id in graph_context.concept_ids
                }
                diagnostic_state = DiagnosticState(
                    diagnostic_run_id=run.id,
                    learner_id=learner_id,
                    course_id=session_row.course_id,
                    graph_version_id=run.graph_version_id,
                    diagnostic_policy_version=run.diagnostic_policy_version,
                    item_budget=run.item_budget,
                    remaining_item_budget=run.item_budget,
                )
                diagnostic_candidates = select_diagnostic_candidates(
                    graph_definition, concept_states, question_ids, diagnostic_state,
                )

    fingerprint_source = {
        "session": session_value.model_dump(mode="json"),
        "graph": None if graph_context is None else graph_context.model_dump(mode="json"),
        "freshness": [item.model_dump(mode="json") for item in freshness],
        "digest": evidence_digest,
        "count": evidence_count,
        "revisions": [str(item) for item in revision_ids],
        "window": None if topic_window is None else topic_window.value_bytes.decode(),
        "frame": None if frame_value is None else frame_value.model_dump(mode="json"),
        "topic": None if topic_state is None else topic_state.model_dump(mode="json"),
        "assessment": (
            None if latest_assessment is None else latest_assessment.model_dump(mode="json")
        ),
        "diagnostic": [item.model_dump(mode="json") for item in diagnostic_candidates],
        "directives": [item.model_dump(mode="json") for item in directive_values],
        "trigger": None if trigger is None else trigger.model_dump(mode="json"),
        "plan_version": plan_version,
    }
    fingerprint = sha256(_json(fingerprint_source)).hexdigest()
    result = AuthoritativePlanningSnapshot(
        learner_id=learner_id,
        course_id=session_row.course_id,
        session=session_value,
        session_fingerprint=fingerprint,
        graph_context=graph_context,
        topic=topic_state,
        projection_freshness=tuple(freshness),
        evidence_set_digest=evidence_digest,
        evidence_count=evidence_count,
        projection_revision_ids=tuple(revision_ids),
        review_candidates=review.candidates,
        latest_assessment=latest_assessment,
        diagnostic_candidates=diagnostic_candidates,
        diagnostic_state=diagnostic_state,
        active_remediation=frame_value,
        directives=tuple(directive_values),
        required_freshness=tuple(freshness),
        trigger=trigger,
        plan_version=plan_version,
        frame_version=frame_version,
        guards=tuple(sorted(set(guards), key=lambda item: item.value)),
    )
    current = await session.scalar(select(LearningSessionRecord).where(
        LearningSessionRecord.id == session_id,
    ).execution_options(populate_existing=True))
    if current is None or current.version != session_value.version or (
        current.last_event_id != session_value.last_event_id
    ):
        raise RuntimeStaleError("Authoritative planning snapshot became stale during assembly")
    return result


async def revalidate_planning_snapshot(
    session: AsyncSession, snapshot: AuthoritativePlanningSnapshot,
) -> AuthoritativePlanningSnapshot:
    """Reject a detached snapshot after any authoritative session mutation."""

    await lock_runtime_learner(session, snapshot.learner_id)
    current = await session.scalar(select(LearningSessionRecord).where(
        LearningSessionRecord.id == snapshot.session.session_id,
    ).with_for_update().execution_options(populate_existing=True))
    if current is None or current.learner_identity_id != snapshot.learner_id:
        raise RuntimeStaleError("Planning snapshot session no longer exists")
    if current.version != snapshot.session.version or (
        current.last_event_id != snapshot.session.last_event_id
    ):
        raise RuntimeStaleError("Planning snapshot session fence is stale")
    return snapshot
