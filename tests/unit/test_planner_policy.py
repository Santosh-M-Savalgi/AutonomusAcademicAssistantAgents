"""Sprint 3.6 precedence, immutable contracts and deterministic planner invariants."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from packages.domain import (
    AssessmentPlanningState,
    DiagnosticCandidate,
    DiagnosticState,
    DirectiveKind,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphEdge,
    PlannerAction,
    PlannerDecision,
    PlannerRule,
    PlanningDirective,
    PlanningGraphContext,
    PlanningState,
    PrerequisiteGate,
    ProjectionFreshness,
    ProjectionFreshnessResult,
    ReasonCode,
    RemediationFrame,
    ReviewCandidate,
    ReviewDueReason,
    TopicPlanningState,
    WeakPrerequisiteCandidate,
)
from packages.planner import PlannerPolicy, decide


def uid(number: int) -> UUID:
    return UUID(int=number)


LEARNER, COURSE, SESSION, GRAPH, TOPIC, NEXT_TOPIC = (uid(i) for i in range(1, 7))
CONCEPT, PREREQUISITE, DIAGNOSTIC, OTHER = (uid(i) for i in range(20, 24))


def topic(**updates: object) -> TopicPlanningState:
    return TopicPlanningState.model_validate({
        "topic_id": TOPIC, "core_concept_ids": (CONCEPT,), "authorized": True,
        "prerequisites_evaluated": True, **updates,
    })


def review(concept_id: UUID = CONCEPT, **updates: object) -> ReviewCandidate:
    return ReviewCandidate.model_validate({
        "learner_id": LEARNER, "course_id": COURSE, "stable_concept_id": concept_id,
        "reasons": (ReviewDueReason.MASTERY_BELOW_THRESHOLD, ReviewDueReason.REVIEW_OVERDUE),
        "due_at": datetime(2026, 1, 1, tzinfo=UTC), "decayed_mastery": 0.4,
        "confidence": 0.5, "mastery_status": "DEVELOPING", "review_successes": 0,
        "review_rung": 0, "review_policy_version": "review_diagnostic_v1",
        "graph_version_id": GRAPH, "supporting_evidence_ids": (uid(90),),
        "supporting_event_ids": (uid(91),), "projection_revision_id": uid(92),
        "evidence_set_digest": "a" * 64, **updates,
    })


def diagnostic(concept_id: UUID = DIAGNOSTIC, **updates: object) -> DiagnosticCandidate:
    return DiagnosticCandidate.model_validate({
        "stable_concept_id": concept_id, "score": 0.8, "descendant_count": 0,
        "confidence": 0.2, "topological_rank": 0,
        "question_version_ids": (uid(100 + concept_id.int),), **updates,
    })


def run(**updates: object) -> DiagnosticState:
    return DiagnosticState.model_validate({
        "diagnostic_run_id": uid(60), "learner_id": LEARNER, "course_id": COURSE,
        "graph_version_id": GRAPH, "diagnostic_policy_version": "diagnostic_v1", **updates,
    })


def frame(**updates: object) -> RemediationFrame:
    return RemediationFrame.model_validate({
        "frame_id": uid(70), "target_concept_id": PREREQUISITE,
        "return_to_topic_id": TOPIC, "confidence": 0.3, "evidence_ids": (uid(90),),
        **updates,
    })


def edge(**updates: object) -> GraphEdge:
    return GraphEdge.model_validate({
        "edge_id": uid(80), "edge_type": EdgeType.PREREQUISITE_OF,
        "source_node_id": PREREQUISITE, "target_node_id": CONCEPT,
        "source": EdgeSource.USER_CONFIRMED, "confidence": 1,
        "status": EdgeStatus.CONFIRMED, **updates,
    })


def directive(
    kind: DirectiveKind = DirectiveKind.MORE_PRACTICE, **updates: object,
) -> PlanningDirective:
    return PlanningDirective.model_validate({
        "directive_id": uid(50), "kind": kind,
        "target_id": CONCEPT if kind in {DirectiveKind.MORE_PRACTICE, DirectiveKind.I_KNOW_THIS}
        else TOPIC, **updates,
    })


def state(**updates: object) -> PlanningState:
    return PlanningState.model_validate({
        "learner_id": LEARNER, "course_id": COURSE, "session_id": SESSION,
        "plan_version": 1, "planner_policy_version": "planner_v1",
        "graph_context": PlanningGraphContext(
            course_id=COURSE, graph_version_id=GRAPH, current_graph_version_id=GRAPH,
            topic_ids=(TOPIC, NEXT_TOPIC), concept_ids=(CONCEPT, PREREQUISITE, DIAGNOSTIC, OTHER),
            mandatory_topic_ids=(TOPIC,),
        ), **updates,
    })


@pytest.mark.parametrize(("updates", "action", "rule"), [
    ({"budget_exceeded": True, "review_candidates": (review(),)},
     PlannerAction.ASK_USER, PlannerRule.HARD_STOP),
    ({"directives": (directive(),), "review_candidates": (review(),)},
     PlannerAction.PRACTICE_CONCEPT, PlannerRule.DIRECTIVE),
    ({"review_candidates": (review(),), "diagnostic_candidates": (diagnostic(),),
      "diagnostic_state": run()}, PlannerAction.REVIEW_DUE, PlannerRule.REVIEW),
    ({"remediation_frame": frame(), "diagnostic_candidates": (diagnostic(),),
      "diagnostic_state": run()}, PlannerAction.PRACTICE_CONCEPT, PlannerRule.REMEDIATION_CONTINUE),
    # Owner-revised test E / ADR 0025: progression precedes diagnostic work.
    ({"topic": topic(), "diagnostic_candidates": (diagnostic(),), "diagnostic_state": run()},
     PlannerAction.TEACH_CURRENT_TOPIC, PlannerRule.TOPIC_TEACH),
    ({"topic": topic(prerequisite_gates=(PrerequisiteGate(edge=edge(), satisfied=False),))},
     PlannerAction.TEACH_PREREQUISITE, PlannerRule.PREREQUISITE_GATE),
    ({"topic": topic()}, PlannerAction.TEACH_CURRENT_TOPIC, PlannerRule.TOPIC_TEACH),
    ({}, PlannerAction.ASK_USER, PlannerRule.NEEDS_STATE),
    ({"diagnostic_state": run(), "diagnostic_candidates": (diagnostic(),)},
     PlannerAction.DIAGNOSE, PlannerRule.DIAGNOSTIC),
])
def test_required_precedence_matrix(updates, action, rule) -> None:
    result = decide(state(**updates))
    assert result.action == action
    assert result.provenance is not None
    assert result.provenance.rule == rule


@pytest.mark.parametrize(("updates", "action", "reason"), [
    ({"session_complete": True, "user_paused": True, "budget_exceeded": True},
     PlannerAction.COMPLETE, ReasonCode.SESSION_COMPLETE),
    ({"user_paused": True, "budget_exceeded": True}, PlannerAction.PAUSE, ReasonCode.USER_PAUSED),
    ({"budget_exceeded": True}, PlannerAction.ASK_USER, ReasonCode.BUDGET_EXCEEDED),
    ({"hard_stop": PlannerAction.COMPLETE}, PlannerAction.COMPLETE, ReasonCode.SESSION_COMPLETE),
    ({"hard_stop": PlannerAction.PAUSE}, PlannerAction.PAUSE, ReasonCode.USER_PAUSED),
    ({"hard_stop": PlannerAction.ASK_USER}, PlannerAction.ASK_USER, ReasonCode.BUDGET_EXCEEDED),
])
def test_explicit_hard_stops_win(updates, action, reason) -> None:
    result = decide(state(
        **updates, directives=(directive(),), review_candidates=(review(),), topic=topic(),
        graph_context=None,
    ))
    assert result.action == action
    assert result.reason_codes == (reason,)


def test_terminal_state_is_not_inferred_from_empty_inputs() -> None:
    result = decide(state(graph_context=None))
    assert result.action == PlannerAction.ASK_USER
    assert result.policy_outcome == "REQUIRE_CONFIRMATION"
    assert decide(state(session_complete=True)).action == PlannerAction.COMPLETE


@pytest.mark.parametrize("freshness", list(ProjectionFreshness))
def test_required_freshness_precedes_directives_and_reviews(freshness) -> None:
    result = decide(state(
        required_freshness=(ProjectionFreshnessResult(
            learner_id=LEARNER, course_id=COURSE, stable_concept_id=CONCEPT, state=freshness,
        ),), directives=(directive(),), review_candidates=(review(),),
    ))
    assert result.policy_outcome == ("ALLOW" if freshness == ProjectionFreshness.FRESH else "BLOCK")
    if freshness != ProjectionFreshness.FRESH:
        assert result.action == PlannerAction.ASK_USER
        assert result.provenance.state_issue == freshness.value


def test_stale_graph_blocks_educational_actions_without_migrating_it() -> None:
    planning_state = state(topic=topic(), review_candidates=(review(),))
    stale_graph = planning_state.graph_context.model_copy(update={
        "current_graph_version_id": uid(999),
    })
    result = decide(state(graph_context=stale_graph, topic=topic(), directives=(directive(),)))
    assert result.policy_outcome == "BLOCK"
    assert result.reason_codes == (ReasonCode.STATE_STALE,)
    assert result.provenance.graph_version_id == GRAPH


@pytest.mark.parametrize(("updates", "issue"), [
    ({"topic": topic(), "graph_context": None}, "MISSING_GRAPH_CONTEXT"),
    ({"topic": topic(authorized=False)}, "MISSING_TOPIC_AUTHORIZATION"),
    ({"topic": topic(prerequisites_evaluated=False)}, "MISSING_TOPIC_AUTHORIZATION"),
    ({"topic": topic(topic_id=uid(999))}, "UNKNOWN_TOPIC"),
    ({"topic": topic(core_concept_ids=(uid(999),))}, "UNKNOWN_CONCEPT"),
    ({"topic": topic(), "target_topic_id": NEXT_TOPIC}, "TOPIC_CONTEXT_MISMATCH"),
    ({"review_candidates": (review(graph_version_id=uid(999)),)}, "GRAPH_CONTEXT_STALE"),
    ({"review_candidates": (review(learner_id=uid(999)),)}, "REVIEW_CONTEXT_MISMATCH"),
    ({"remediation_frame": frame(target_concept_id=uid(999))}, "UNKNOWN_CONCEPT"),
    ({"active_remediation_frame": True}, "MISSING_REMEDIATION_TARGET"),
    ({"hard_stop": PlannerAction.TEACH_CURRENT_TOPIC}, "INVALID_HARD_STOP_ACTION"),
    ({"pending_user_directive": PlannerAction.RETEACH_WITH_NEW_STRATEGY},
     "MISSING_DIRECTIVE_TARGET"),
])
def test_missing_or_invalid_authoritative_state_is_typed_block(updates, issue) -> None:
    result = decide(state(**updates))
    assert result.action == PlannerAction.ASK_USER
    assert result.policy_outcome == "BLOCK"
    assert result.provenance.state_issue == issue


@pytest.mark.parametrize(("kind", "target", "action", "outcome"), [
    (DirectiveKind.SKIP, TOPIC, PlannerAction.ADVANCE_TOPIC, "REQUIRE_CONFIRMATION"),
    (DirectiveKind.SKIP, NEXT_TOPIC, PlannerAction.ADVANCE_TOPIC, "ALLOW"),
    (DirectiveKind.EXPLAIN_SIMPLER, TOPIC, PlannerAction.RETEACH_WITH_NEW_STRATEGY, "ALLOW"),
    (DirectiveKind.MORE_PRACTICE, CONCEPT, PlannerAction.PRACTICE_CONCEPT, "ALLOW"),
    (DirectiveKind.I_KNOW_THIS, DIAGNOSTIC, PlannerAction.DIAGNOSE, "ALLOW"),
])
def test_directive_mapping_uses_explicit_ids(kind, target, action, outcome) -> None:
    result = decide(state(
        directives=(directive(kind, target_id=target),), review_candidates=(review(),),
        diagnostic_state=run(), diagnostic_candidates=(diagnostic(),),
    ))
    assert result.action == action
    assert result.target_id == str(target)
    assert result.policy_outcome == outcome
    assert result.provenance.directive_id == uid(50)
    if kind == DirectiveKind.I_KNOW_THIS:
        assert result.provenance.question_version_ids == diagnostic().question_version_ids


def test_multiple_directives_are_uuid_ordered_across_sources() -> None:
    first = directive(DirectiveKind.EXPLAIN_SIMPLER, directive_id=uid(49), source="SYSTEM")
    second = directive(directive_id=uid(50), source="LEARNER")
    decisions = []
    for directives in ((first, second), (second, first)):
        result = decide(state(directives=directives))
        assert result.action == PlannerAction.RETEACH_WITH_NEW_STRATEGY
        assert result.provenance.directive_id == first.directive_id
        decisions.append(result.canonical_bytes())
    assert decisions[0] == decisions[1]


def test_legacy_directive_keeps_mandatory_skip_confirmation() -> None:
    result = decide(state(
        pending_user_directive=PlannerAction.ADVANCE_TOPIC, target_topic_id=TOPIC,
        review_candidates=(review(),),
    ))
    assert result.action == PlannerAction.ADVANCE_TOPIC
    assert result.policy_outcome == "REQUIRE_CONFIRMATION"


def test_review_consumes_first_candidate_without_reranking_and_keeps_provenance() -> None:
    # Ordering is the selector's responsibility; the planner must not duplicate its ranking.
    selected = (review(OTHER), review(CONCEPT), review(PREREQUISITE))
    result = decide(state(review_candidates=selected))
    assert result.target_id == str(OTHER)
    assert result.confidence == selected[0].confidence
    assert result.evidence_ids == selected[0].supporting_evidence_ids
    assert result.provenance.review_reasons == tuple(reason.value for reason in selected[0].reasons)
    assert result.provenance.source_event_ids == selected[0].supporting_event_ids
    assert result.provenance.projection_revision_id == selected[0].projection_revision_id
    assert result.provenance.evidence_set_digest == selected[0].evidence_set_digest


@pytest.mark.parametrize(("complete", "continuation", "expected"), [
    (False, PlannerAction.PRACTICE_CONCEPT, PlannerAction.PRACTICE_CONCEPT),
    (False, PlannerAction.GENERATE_MICRO_CHECK, PlannerAction.GENERATE_MICRO_CHECK),
    (False, PlannerAction.GENERATE_QUIZ, PlannerAction.GENERATE_QUIZ),
    (True, PlannerAction.PRACTICE_CONCEPT, PlannerAction.RETURN_TO_TARGET),
])
def test_remediation_suppresses_review_until_return_and_never_mutates_frame(
    complete, continuation, expected,
) -> None:
    active = frame(complete=complete, continuation_action=continuation)
    snapshot = active.model_dump_json()
    result = decide(state(
        remediation_frame=active, review_candidates=(review(),), topic=topic(),
        diagnostic_state=run(), diagnostic_candidates=(diagnostic(),),
    ))
    assert result.action == expected
    assert result.target_id == str(TOPIC if complete else PREREQUISITE)
    assert result.provenance.remediation_frame_id == active.frame_id
    assert result.provenance.return_to_topic_id == TOPIC
    assert active.model_dump_json() == snapshot


def test_assessment_failure_consumes_preordered_confirmed_weak_candidates_before_topic() -> None:
    deep = WeakPrerequisiteCandidate(stable_concept_id=PREREQUISITE, path=(edge(),), confidence=0.3)
    unconfirmed = WeakPrerequisiteCandidate(
        stable_concept_id=OTHER,
        path=(edge(source_node_id=OTHER, status=EdgeStatus.PROPOSED),), confidence=0.1,
    )
    result = decide(state(
        topic=topic(), latest_assessment=AssessmentPlanningState(
            topic_id=TOPIC, failing_concept_ids=(CONCEPT,), confidence=0.4,
            weak_prerequisites=(unconfirmed, deep),
        ), diagnostic_state=run(), diagnostic_candidates=(diagnostic(),),
    ))
    assert result.action == PlannerAction.TEACH_PREREQUISITE
    assert result.target_id == str(PREREQUISITE)
    assert result.provenance.prerequisite_edge_ids == (edge().edge_id,)
    assert result.provenance.return_to_topic_id == TOPIC


def test_failure_without_executable_weak_prerequisite_reteaches() -> None:
    result = decide(state(topic=topic(), latest_assessment=AssessmentPlanningState(
        topic_id=TOPIC, failing_concept_ids=(CONCEPT,), confidence=0.4,
    )))
    assert result.action == PlannerAction.RETEACH_WITH_NEW_STRATEGY
    assert result.target_id == str(TOPIC)


def test_deepest_first_order_and_transitive_causal_path_are_supplied_by_caller() -> None:
    deep = WeakPrerequisiteCandidate(
        stable_concept_id=OTHER, path=(edge(source_node_id=OTHER),), confidence=0.3,
    )
    ancestor = WeakPrerequisiteCandidate(
        stable_concept_id=PREREQUISITE, path=(
            edge(edge_id=uid(81), target_node_id=OTHER), edge(source_node_id=OTHER),
        ), confidence=0.3,
    )
    assessment = AssessmentPlanningState(
        topic_id=TOPIC, failing_concept_ids=(CONCEPT,), confidence=0.2,
        weak_prerequisites=(deep, ancestor),
    )
    assert decide(state(topic=topic(), latest_assessment=assessment)).target_id == str(OTHER)
    result = decide(state(topic=topic(), latest_assessment=assessment.model_copy(update={
        "weak_prerequisites": (ancestor,),
    })))
    assert result.target_id == str(PREREQUISITE)
    assert result.provenance.prerequisite_edge_ids == (uid(81), uid(80))


@pytest.mark.parametrize("status", list(EdgeStatus))
@pytest.mark.parametrize("edge_type", list(EdgeType))
def test_only_confirmed_prerequisite_edges_can_block_progression(status, edge_type) -> None:
    gate = PrerequisiteGate(
        edge=edge(status=status, edge_type=edge_type, source=EdgeSource.LLM_PROPOSED),
        satisfied=False,
    )
    result = decide(state(topic=topic(prerequisite_gates=(gate,))))
    assert result.action == (
        PlannerAction.TEACH_PREREQUISITE
        if status == EdgeStatus.CONFIRMED and edge_type == EdgeType.PREREQUISITE_OF
        else PlannerAction.TEACH_CURRENT_TOPIC
    )


def test_unknown_confirmed_gate_result_blocks_instead_of_guessing() -> None:
    result = decide(state(topic=topic(prerequisite_gates=(
        PrerequisiteGate(edge=edge(), satisfied=None),
    ))))
    assert result.policy_outcome == "BLOCK"
    assert result.provenance.state_issue == "MISSING_PREREQUISITE_GATE_RESULT"


def test_reversed_or_unrelated_edge_is_not_a_gate_for_topic_core_concept() -> None:
    gate = PrerequisiteGate(
        edge=edge(source_node_id=CONCEPT, target_node_id=PREREQUISITE), satisfied=False,
    )
    assert decide(state(topic=topic(prerequisite_gates=(gate,)))).action == (
        PlannerAction.TEACH_CURRENT_TOPIC
    )


@pytest.mark.parametrize(("updates", "expected"), [
    ({}, PlannerAction.TEACH_CURRENT_TOPIC),
    ({"taught": True}, PlannerAction.GENERATE_MICRO_CHECK),
    ({"taught": True, "checked": True}, PlannerAction.GENERATE_QUIZ),
    ({"taught": True, "checked": True, "quiz_completed": True, "gate_satisfied": True,
      "next_topic_id": NEXT_TOPIC}, PlannerAction.ADVANCE_TOPIC),
])
def test_topic_position_and_satisfied_gate_precede_diagnostics(updates, expected) -> None:
    result = decide(state(
        topic=topic(**updates), diagnostic_state=run(), diagnostic_candidates=(diagnostic(),),
    ))
    assert result.action == expected
    assert result.target_id == str(NEXT_TOPIC if expected == PlannerAction.ADVANCE_TOPIC else TOPIC)


def test_completed_quiz_does_not_regenerate_or_bypass_unsatisfied_topic_gate() -> None:
    position = topic(taught=True, checked=True, quiz_completed=True, gate_satisfied=False)
    assert decide(state(topic=position)).action == PlannerAction.ASK_USER
    assert decide(state(
        topic=position, diagnostic_state=run(), diagnostic_candidates=(diagnostic(),),
    )).action == PlannerAction.DIAGNOSE


def test_satisfied_gate_with_missing_next_target_requires_state() -> None:
    result = decide(state(topic=topic(
        taught=True, checked=True, quiz_completed=True, gate_satisfied=True,
    )))
    assert result.policy_outcome == "BLOCK"
    assert result.provenance.state_issue == "MISSING_NEXT_TOPIC"


def test_multiple_diagnostics_keep_selector_order_questions_and_run_context() -> None:
    candidates = (diagnostic(OTHER), diagnostic(DIAGNOSTIC))
    result = decide(state(diagnostic_candidates=candidates, diagnostic_state=run()))
    assert result.target_id == str(OTHER)
    assert result.provenance.question_version_ids == candidates[0].question_version_ids
    assert result.provenance.diagnostic_run_id == run().diagnostic_run_id
    assert result.provenance.diagnostic_policy_version == "diagnostic_v1"


@pytest.mark.parametrize(("run_updates", "issue"), [
    ({"remaining_item_budget": 0}, "DIAGNOSTIC_BUDGET_MISMATCH"),
    ({"selected_concept_ids": (DIAGNOSTIC,)}, "DIAGNOSTIC_SELECTION_ALREADY_USED"),
    ({"diagnostic_assessed_concept_ids": (DIAGNOSTIC,)}, "DIAGNOSTIC_SELECTION_ALREADY_USED"),
    ({"attempted_question_version_ids": diagnostic().question_version_ids},
     "DIAGNOSTIC_SELECTION_ALREADY_USED"),
    ({"graph_version_id": uid(999)}, "GRAPH_CONTEXT_STALE"),
    ({"learner_id": uid(999)}, "DIAGNOSTIC_CONTEXT_MISMATCH"),
])
def test_diagnostic_requires_authoritative_run_and_valid_selection(run_updates, issue) -> None:
    result = decide(state(
        diagnostic_state=run(**run_updates), diagnostic_candidates=(diagnostic(),),
    ))
    assert result.policy_outcome == "BLOCK"
    assert result.provenance.state_issue == issue


def test_diagnostic_and_self_report_directive_require_preselected_work() -> None:
    for planning_state in (
        state(diagnostic_candidates=(diagnostic(),)),
        state(directives=(directive(DirectiveKind.I_KNOW_THIS),)),
    ):
        result = decide(planning_state)
        assert result.action == PlannerAction.ASK_USER
        assert result.policy_outcome == "BLOCK"
        assert not result.evidence_ids


@pytest.mark.parametrize("updates", [
    {"review_candidates": tuple(review(uid(20 + i)) for i in range(4))},
    {"review_candidates": (review(), review())},
    {"diagnostic_candidates": (diagnostic(), diagnostic())},
    {"directives": (directive(), directive())},
    {"topic": {"topic_id": TOPIC, "core_concept_ids": (CONCEPT,), "checked": True}},
    {"topic": {"topic_id": TOPIC, "core_concept_ids": (CONCEPT,), "quiz_completed": True}},
    {"topic": topic().model_dump() | {"next_topic_id": TOPIC}},
])
def test_contract_rejects_ambiguous_duplicates_and_invalid_learning_position(updates) -> None:
    with pytest.raises(ValidationError):
        state(**updates)


def test_input_and_decision_are_deeply_immutable_and_round_trip_canonically() -> None:
    planning_state = state(topic=topic(), directives=(directive(),))
    before = planning_state.canonical_bytes()
    result = PlannerPolicy.decide(planning_state)
    assert result == decide(planning_state)
    with pytest.raises(ValidationError):
        planning_state.topic.authorized = False
    with pytest.raises(ValidationError):
        planning_state.plan_version = 2
    with pytest.raises(ValidationError):
        result.action = PlannerAction.COMPLETE
    assert isinstance(result.reason_codes, tuple)
    assert isinstance(result.evidence_ids, tuple)
    restored_state = PlanningState.model_validate_json(planning_state.model_dump_json())
    restored_decision = PlannerDecision.model_validate_json(result.model_dump_json())
    assert restored_state == planning_state
    assert restored_state.canonical_bytes() == before
    assert restored_decision.canonical_bytes() == result.canonical_bytes()
    assert planning_state.canonical_bytes() == before
    assert len(result.provenance.state_digest) == 64


@settings(max_examples=80, derandomize=True, database=None, deadline=None)
@given(st.lists(st.booleans(), min_size=8, max_size=8))
def test_determinism_and_hard_stop_dominance_for_combinations(flags) -> None:
    complete, paused, budget, requested, due, active, has_topic, pending = flags
    planning_state = state(
        session_complete=complete, user_paused=paused, budget_exceeded=budget,
        directives=(directive(),) if requested else (),
        review_candidates=(review(),) if due else (),
        remediation_frame=frame() if active else None,
        topic=topic() if has_topic else None,
        diagnostic_state=run() if pending else None,
        diagnostic_candidates=(diagnostic(),) if pending else (),
    )
    before = planning_state.canonical_bytes()
    result = decide(planning_state)
    assert isinstance(result, PlannerDecision)
    assert result.canonical_bytes() == decide(planning_state).canonical_bytes()
    assert planning_state.canonical_bytes() == before
    if complete or paused or budget:
        assert result.provenance.rule == PlannerRule.HARD_STOP
    elif requested:
        assert result.provenance.rule == PlannerRule.DIRECTIVE
    elif due and not active:
        assert result.provenance.rule == PlannerRule.REVIEW
    elif active:
        assert result.provenance.rule == PlannerRule.REMEDIATION_CONTINUE
