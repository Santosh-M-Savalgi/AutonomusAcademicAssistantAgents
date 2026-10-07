"""Existing selector/persistence outputs cross the pure planning boundary unchanged."""

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest
from sqlalchemy import func, select

from packages.curriculum import select_diagnostic_candidates
from packages.domain import (
    Concept,
    ConceptMastery,
    DiagnosticConceptState,
    GraphNode,
    GraphNodeType,
    GraphSnapshot,
    GraphSource,
    LearningEventType,
    MasteryState,
    PlannerAction,
    PlanningGraphContext,
    SelfReportPriorContribution,
)
from packages.domain.events import ConceptLearningEventInput, LearningEventPayload
from packages.mastery import metrics_for, replay, seed_initial_schedule, select_review_candidates
from packages.persistence import (
    LearningEventRecord,
    MasteryProjectionRevision,
    apply_evidence,
    select_persisted_review_candidates,
)
from packages.planner import decide
from tests.integration.test_mastery_runtime import _evidence, _source_context
from tests.unit.test_planner_policy import (
    CONCEPT,
    COURSE,
    DIAGNOSTIC,
    GRAPH,
    LEARNER,
    NEXT_TOPIC,
    OTHER,
    PREREQUISITE,
    TOPIC,
    edge,
    run,
    state,
    topic,
    uid,
)

AS_OF = datetime(2026, 1, 3, tzinfo=UTC)


def test_review_selector_ranking_bounds_and_uuid_ties_feed_planner_without_recalculation() -> None:
    schedules = tuple(seed_initial_schedule(
        learner_id=LEARNER, course_id=COURSE, stable_concept_id=concept_id,
        graph_version_id=GRAPH, first_event_id=uid(200 + index),
        first_event_at=AS_OF - timedelta(days=2) if concept_id != DIAGNOSTIC else AS_OF,
    ) for index, concept_id in enumerate((CONCEPT, PREREQUISITE, OTHER, DIAGNOSTIC)))
    posteriors = {
        concept_id: MasteryState(alpha=1, beta=4 if concept_id == OTHER else 2,
                                last_occurred_at=AS_OF)
        for concept_id in (CONCEPT, PREREQUISITE, OTHER, DIAGNOSTIC)
    }
    projections = {concept_id: ConceptMastery(
        stable_concept_id=concept_id, state=posterior, metrics=metrics_for(posterior),
    ) for concept_id, posterior in posteriors.items()}
    for inputs in permutations(schedules):
        selection = select_review_candidates(inputs, projections, as_of=AS_OF)
        assert tuple(item.stable_concept_id for item in selection.candidates) == (
            OTHER, CONCEPT, PREREQUISITE,
        )
        result = decide(state(review_candidates=selection.candidates))
        assert result.action == PlannerAction.REVIEW_DUE
        assert result.target_id == str(OTHER)
        assert result.confidence == selection.candidates[0].confidence


def test_real_graph_and_self_report_diagnostic_selector_feed_build_spec_precedence() -> None:
    concepts = tuple(Concept(
        id=concept_id, key=f"concept-{index}", title=f"Concept {index}",
        source=GraphSource.USER_DEFINED, confidence=1, verified=True,
    ) for index, concept_id in enumerate((CONCEPT, PREREQUISITE, DIAGNOSTIC)))
    snapshot = GraphSnapshot(
        course_id=COURSE, curriculum_revision_id=uid(10), graph_version=1,
        nodes=tuple(GraphNode(
            id=concept.id, label=concept.title, node_type=GraphNodeType.CONCEPT,
            source=concept.source, confidence=concept.confidence,
        ) for concept in concepts) + tuple(GraphNode(
            id=topic_id, label=f"Topic {index}", node_type=GraphNodeType.TOPIC,
            source=GraphSource.USER_DEFINED, confidence=1,
        ) for index, topic_id in enumerate((TOPIC, NEXT_TOPIC))),
        concepts=concepts, mappings=(), edges=(edge(),),
    )
    prior = SelfReportPriorContribution(
        assertion_id=uid(210), learner_id=LEARNER, course_id=COURSE,
        stable_concept_id=CONCEPT, graph_version_id=GRAPH, occurred_at=AS_OF,
        policy_version="review_diagnostic_v1",
    )
    posterior = replay([], AS_OF, self_report_priors=(prior,)).projections[0]
    confidence = posterior.metrics.confidence
    assert confidence == pytest.approx(0.2)
    candidates = select_diagnostic_candidates(
        snapshot,
        {concept.id: DiagnosticConceptState(
            stable_concept_id=concept.id, confidence=confidence if concept.id == CONCEPT else 0,
        ) for concept in concepts},
        {concept.id: (uid(300 + index * 2), uid(301 + index * 2))
         for index, concept in enumerate(concepts)}, run(),
    )
    assert candidates[0].stable_concept_id == PREREQUISITE
    assert sum(len(item.question_version_ids) for item in candidates) <= 12
    graph_context = PlanningGraphContext(
        course_id=snapshot.course_id, graph_version_id=GRAPH, current_graph_version_id=GRAPH,
        topic_ids=tuple(node.id for node in snapshot.nodes
                        if node.node_type == GraphNodeType.TOPIC),
        concept_ids=tuple(concept.id for concept in snapshot.concepts),
    )
    planning_state = state(
        graph_context=graph_context, diagnostic_state=run(), diagnostic_candidates=candidates,
    )
    result = decide(planning_state)
    assert result.action == PlannerAction.DIAGNOSE
    assert result.provenance.question_version_ids == candidates[0].question_version_ids
    assert decide(state(
        graph_context=graph_context, topic=topic(), diagnostic_state=run(),
        diagnostic_candidates=candidates,
    )).action == PlannerAction.TEACH_CURRENT_TOPIC


@pytest.mark.live_integration
async def test_persisted_review_is_planned_outside_transaction_without_writes(
    migrate_database, live_database,
) -> None:
    await asyncio.to_thread(migrate_database)
    source = await _source_context(live_database)
    evidence = _evidence(source)
    grading_event = ConceptLearningEventInput(
        event_id=uid(900), type=LearningEventType.ANSWER_GRADED,
        actor_id=evidence.learner_id, actor_subject="mastery-actor", learner_id=evidence.learner_id,
        course_id=evidence.course_id, occurred_at=evidence.occurred_at,
        payload=LearningEventPayload(kind="answer_graded", data={}),
        correlation_id=uid(901), idempotency_key="planner-boundary:grading",
        stable_concept_ids=tuple(item.stable_concept_id for item in evidence.concept_roles),
        source_evidence_id=evidence.evidence_id, source_attempt_id=evidence.attempt_id,
    )
    async with live_database.session() as session, session.begin():
        await apply_evidence(session, evidence, actor_subject="mastery-actor",
                             concept_event=grading_event)
    async with live_database.session() as session:
        selection = await select_persisted_review_candidates(
            session, evidence.learner_id, evidence.course_id,
            as_of=evidence.occurred_at + timedelta(days=1, seconds=1),
        )
        before = (
            await session.scalar(select(func.count()).select_from(MasteryProjectionRevision)),
            await session.scalar(select(func.count()).select_from(LearningEventRecord)),
        )
    assert selection.candidates
    context = PlanningGraphContext(
        course_id=evidence.course_id, graph_version_id=evidence.graph_version_id,
        current_graph_version_id=evidence.graph_version_id, topic_ids=(),
        concept_ids=tuple(item.stable_concept_id for item in evidence.concept_roles),
    )
    planning_state = state(
        learner_id=evidence.learner_id, course_id=evidence.course_id, graph_context=context,
        review_candidates=selection.candidates,
    )
    result = decide(planning_state)
    assert result.action == PlannerAction.REVIEW_DUE
    assert result.provenance.projection_revision_id == (
        selection.candidates[0].projection_revision_id
    )
    async with live_database.session() as session:
        after = (
            await session.scalar(select(func.count()).select_from(MasteryProjectionRevision)),
            await session.scalar(select(func.count()).select_from(LearningEventRecord)),
        )
    assert after == before
