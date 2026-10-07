"""Pure first-match planner policy in build-spec §6.4 order (planner_v1)."""

from hashlib import sha256
from typing import Literal
from uuid import UUID

from packages.domain.adaptation import (
    DiagnosticCandidate,
    DirectiveKind,
    PlanningState,
    ProjectionFreshness,
    ReviewDueReason,
)
from packages.domain.enums import PlannerAction, PlannerRule, ReasonCode
from packages.domain.graph import EdgeStatus, EdgeType
from packages.domain.models import PlannerDecision, PlannerDecisionProvenance


def _decision(
    state: PlanningState,
    rule: PlannerRule,
    action: PlannerAction,
    reason: ReasonCode,
    explanation: str,
    *,
    target: UUID | None = None,
    evidence_ids: tuple[UUID, ...] = (),
    confidence: float = 0,
    outcome: Literal["ALLOW", "REQUIRE_CONFIRMATION", "BLOCK"] = "ALLOW",
    directive_id: UUID | None = None,
    frame_id: UUID | None = None,
    return_to: UUID | None = None,
    diagnostic: DiagnosticCandidate | None = None,
    edge_ids: tuple[UUID, ...] = (),
    issue: str | None = None,
) -> PlannerDecision:
    graph = state.graph_context
    review = state.review_candidates[0] if rule == PlannerRule.REVIEW else None
    run = state.diagnostic_state if diagnostic is not None else None
    return PlannerDecision(
        action=action,
        target_id=str(target or state.target_topic_id or state.session_id),
        reason_codes=(reason,),
        evidence_ids=tuple(sorted(set(evidence_ids), key=lambda value: value.bytes)),
        confidence=confidence,
        policy_outcome=outcome,
        plan_version=state.plan_version,
        planner_policy_version=state.planner_policy_version,
        explanation=explanation,
        provenance=PlannerDecisionProvenance(
            rule=rule,
            learner_id=state.learner_id,
            course_id=state.course_id,
            session_id=state.session_id,
            state_digest=sha256(state.canonical_bytes()).hexdigest(),
            graph_version_id=None if graph is None else graph.graph_version_id,
            directive_id=directive_id,
            remediation_frame_id=frame_id,
            return_to_topic_id=return_to,
            diagnostic_run_id=None if run is None else run.diagnostic_run_id,
            diagnostic_policy_version=None if run is None else run.diagnostic_policy_version,
            question_version_ids=() if diagnostic is None else diagnostic.question_version_ids,
            source_event_ids=tuple(sorted(set((
                *state.source_event_ids,
                *(() if review is None else review.supporting_event_ids),
            )), key=lambda value: value.bytes)),
            prerequisite_edge_ids=edge_ids,
            projection_revision_id=None if review is None else review.projection_revision_id,
            evidence_set_digest=None if review is None else review.evidence_set_digest,
            review_reasons=() if review is None else tuple(
                "REVIEW_OVERDUE" if reason == ReviewDueReason.REVIEW_OVERDUE
                else "MASTERY_BELOW_THRESHOLD" for reason in review.reasons
            ),
            state_issue=issue,
        ),
    )


def _blocked(state: PlanningState, issue: str, *, stale: bool = False) -> PlannerDecision:
    return _decision(
        state, PlannerRule.REQUIRED_STATE, PlannerAction.ASK_USER,
        ReasonCode.STATE_STALE if stale else ReasonCode.STATE_MISSING,
        f"Authoritative planning state is unavailable: {issue}.",
        outcome="BLOCK", issue=issue,
    )


def _graph_issue(
    state: PlanningState,
    *,
    topics: tuple[UUID, ...] = (),
    concepts: tuple[UUID, ...] = (),
    version: UUID | None = None,
) -> str | None:
    """Validate detached vocabulary/context only; never traverse or rank a graph."""

    graph = state.graph_context
    if graph is None:
        return "MISSING_GRAPH_CONTEXT"
    if version is not None and version != graph.graph_version_id:
        return "GRAPH_CONTEXT_STALE"
    if any(topic_id not in graph.topic_ids for topic_id in topics):
        return "UNKNOWN_TOPIC"
    if any(concept_id not in graph.concept_ids for concept_id in concepts):
        return "UNKNOWN_CONCEPT"
    return None


def _diagnostic_issue(state: PlanningState, candidate: DiagnosticCandidate) -> str | None:
    run = state.diagnostic_state
    if run is None:
        return "MISSING_DIAGNOSTIC_RUN"
    if (run.learner_id, run.course_id) != (state.learner_id, state.course_id):
        return "DIAGNOSTIC_CONTEXT_MISMATCH"
    issue = _graph_issue(
        state, concepts=(candidate.stable_concept_id,), version=run.graph_version_id,
    )
    if issue is not None:
        return issue
    if sum(len(item.question_version_ids) for item in state.diagnostic_candidates) > (
        run.remaining_item_budget
    ):
        return "DIAGNOSTIC_BUDGET_MISMATCH"
    if candidate.stable_concept_id in (
        *run.selected_concept_ids, *run.diagnostic_assessed_concept_ids,
    ) or any(question_id in run.attempted_question_version_ids
             for question_id in candidate.question_version_ids):
        return "DIAGNOSTIC_SELECTION_ALREADY_USED"
    return None


def decide(state: PlanningState) -> PlannerDecision:
    """Select exactly one action. Supplied candidate order is authoritative."""

    # 1. Hard stops. Terminal > pause > budget; required stale/missing state also blocks.
    if state.session_complete or state.hard_stop == PlannerAction.COMPLETE:
        return _decision(
            state, PlannerRule.HARD_STOP, PlannerAction.COMPLETE, ReasonCode.SESSION_COMPLETE,
            "The session is already complete.", target=state.session_id,
        )
    if (state.user_paused or state.hard_stop == PlannerAction.PAUSE
            or state.pending_user_directive == PlannerAction.PAUSE):
        return _decision(
            state, PlannerRule.HARD_STOP, PlannerAction.PAUSE, ReasonCode.USER_PAUSED,
            "The learner paused the session.", target=state.session_id,
        )
    if state.budget_exceeded or state.hard_stop == PlannerAction.ASK_USER:
        return _decision(
            state, PlannerRule.HARD_STOP, PlannerAction.ASK_USER, ReasonCode.BUDGET_EXCEEDED,
            "The caller reports that the session budget is exhausted.", outcome="BLOCK",
        )
    if state.hard_stop is not None:
        return _blocked(state, "INVALID_HARD_STOP_ACTION")
    graph = state.graph_context
    if graph is not None:
        if graph.course_id != state.course_id:
            return _blocked(state, "GRAPH_COURSE_MISMATCH")
        if graph.graph_version_id != graph.current_graph_version_id:
            return _blocked(state, "GRAPH_CONTEXT_STALE", stale=True)
    for freshness in sorted(state.required_freshness, key=lambda item: (
        item.stable_concept_id.bytes, item.state.value,
    )):
        if (freshness.learner_id, freshness.course_id) != (state.learner_id, state.course_id):
            return _blocked(state, "FRESHNESS_CONTEXT_MISMATCH")
        if freshness.state != ProjectionFreshness.FRESH:
            return _blocked(
                state, freshness.state.value,
                stale=freshness.state in {
                    ProjectionFreshness.EVIDENCE_SET_STALE, ProjectionFreshness.GRAPH_CONTEXT_STALE,
                },
            )

    # 2. Explicit directives. UUID byte order resolves multiple pending directives.
    if state.directives and state.pending_user_directive is not None:
        return _blocked(state, "AMBIGUOUS_DIRECTIVE_INPUT")
    if state.directives:
        directive = min(state.directives, key=lambda item: item.directive_id.bytes)
        concept_target = directive.kind in {DirectiveKind.MORE_PRACTICE, DirectiveKind.I_KNOW_THIS}
        issue = _graph_issue(
            state, topics=() if concept_target else (directive.target_id,),
            concepts=(directive.target_id,) if concept_target else (),
        )
        if issue is not None:
            return _blocked(state, issue)
        if directive.kind == DirectiveKind.I_KNOW_THIS:
            candidate = next((item for item in state.diagnostic_candidates
                              if item.stable_concept_id == directive.target_id), None)
            if candidate is None:
                return _blocked(state, "MISSING_SELECTED_DIAGNOSTIC")
            issue = _diagnostic_issue(state, candidate)
            if issue is not None:
                return _blocked(state, issue, stale=issue == "GRAPH_CONTEXT_STALE")
            return _decision(
                state, PlannerRule.DIRECTIVE, PlannerAction.DIAGNOSE, ReasonCode.USER_DIRECTIVE,
                "Verify the self-report using the caller-selected diagnostic; no gate is waived.",
                target=directive.target_id, directive_id=directive.directive_id,
                diagnostic=candidate, confidence=candidate.confidence,
            )
        actions = {
            DirectiveKind.SKIP: PlannerAction.ADVANCE_TOPIC,
            DirectiveKind.EXPLAIN_SIMPLER: PlannerAction.RETEACH_WITH_NEW_STRATEGY,
            DirectiveKind.MORE_PRACTICE: PlannerAction.PRACTICE_CONCEPT,
        }
        assert graph is not None
        mandatory_skip = (
            directive.kind == DirectiveKind.SKIP
            and directive.target_id in graph.mandatory_topic_ids
        )
        return _decision(
            state, PlannerRule.DIRECTIVE, actions[directive.kind], ReasonCode.USER_DIRECTIVE,
            "Apply the explicit directive; mandatory topic skipping requires confirmation.",
            target=directive.target_id, directive_id=directive.directive_id,
            outcome="REQUIRE_CONFIRMATION" if mandatory_skip else "ALLOW",
        )
    if state.pending_user_directive is not None:
        # Sprint 3.5's mapped-action seam remains available, with required target validation.
        target = state.target_topic_id
        if target is None:
            return _blocked(state, "MISSING_DIRECTIVE_TARGET")
        issue = _graph_issue(state, topics=(target,))
        if issue is not None:
            return _blocked(state, issue)
        assert graph is not None
        return _decision(
            state, PlannerRule.DIRECTIVE, state.pending_user_directive, ReasonCode.USER_DIRECTIVE,
            "Apply the caller-mapped explicit directive.", target=target,
            outcome="REQUIRE_CONFIRMATION" if (
                state.pending_user_directive == PlannerAction.ADVANCE_TOPIC
                and target in graph.mandatory_topic_ids
            ) else "ALLOW",
        )

    # 3. Already-ranked Sprint 3.5 reviews; active frames suppress insertion even when complete.
    active_frame = state.remediation_frame is not None or state.active_remediation_frame
    if state.review_candidates and not active_frame:
        review_candidate = state.review_candidates[0]
        if (review_candidate.learner_id, review_candidate.course_id) != (
            state.learner_id, state.course_id,
        ):
            return _blocked(state, "REVIEW_CONTEXT_MISMATCH")
        issue = _graph_issue(
            state, concepts=(review_candidate.stable_concept_id,),
            version=review_candidate.graph_version_id,
        )
        if issue is not None:
            return _blocked(state, issue, stale=issue == "GRAPH_CONTEXT_STALE")
        return _decision(
            state, PlannerRule.REVIEW, PlannerAction.REVIEW_DUE, ReasonCode.REVIEW_DUE,
            "Review the first candidate supplied by the spaced-review selector.",
            target=review_candidate.stable_concept_id,
            evidence_ids=review_candidate.supporting_evidence_ids,
            confidence=review_candidate.confidence,
        )

    # 4. Continuation/return only. No remediation execution, loop guard or frame mutation.
    frame = state.remediation_frame
    if frame is not None:
        issue = _graph_issue(
            state, topics=(frame.return_to_topic_id,), concepts=(frame.target_concept_id,),
        )
        if issue is not None:
            return _blocked(state, issue)
        return _decision(
            state, PlannerRule.REMEDIATION_RETURN if frame.complete
            else PlannerRule.REMEDIATION_CONTINUE,
            PlannerAction.RETURN_TO_TARGET if frame.complete else frame.continuation_action,
            ReasonCode.FRAME_COMPLETE if frame.complete else ReasonCode.LOW_PREREQ_MASTERY,
            "Return to the saved target." if frame.complete else "Continue the active frame.",
            target=frame.return_to_topic_id if frame.complete else frame.target_concept_id,
            evidence_ids=frame.evidence_ids, confidence=frame.confidence,
            frame_id=frame.frame_id, return_to=frame.return_to_topic_id,
        )
    if state.active_remediation_frame:
        target = (state.return_to_target_id if state.remediation_frame_complete
                  else state.remediation_target_id)
        if target is None:
            return _blocked(state, "MISSING_REMEDIATION_TARGET")
        if graph is not None:
            issue = _graph_issue(
                state, topics=(target,) if state.remediation_frame_complete else (),
                concepts=() if state.remediation_frame_complete else (target,),
            )
            if issue is not None:
                return _blocked(state, issue)
        return _decision(
            state, PlannerRule.REMEDIATION_RETURN if state.remediation_frame_complete
            else PlannerRule.REMEDIATION_CONTINUE,
            PlannerAction.RETURN_TO_TARGET if state.remediation_frame_complete
            else PlannerAction.PRACTICE_CONCEPT,
            ReasonCode.FRAME_COMPLETE if state.remediation_frame_complete
            else ReasonCode.LOW_PREREQ_MASTERY,
            "Continue the caller-mapped Sprint 3.5 remediation state.", target=target,
        )

    # 5. Latest-assessment failures. Weak candidates arrive deepest-first from the caller.
    assessment = state.latest_assessment
    if assessment is not None:
        current_topic_id = (
            state.topic.topic_id if state.topic is not None else state.target_topic_id
        )
        if current_topic_id is None or current_topic_id != assessment.topic_id:
            return _blocked(state, "ASSESSMENT_TOPIC_MISMATCH")
        issue = _graph_issue(
            state, topics=(assessment.topic_id,), concepts=assessment.failing_concept_ids,
        )
        if issue is not None:
            return _blocked(state, issue)
        for prerequisite in assessment.weak_prerequisites:
            if not all(edge.edge_type == EdgeType.PREREQUISITE_OF
                       and edge.status == EdgeStatus.CONFIRMED for edge in prerequisite.path):
                continue
            if prerequisite.path[-1].target_node_id not in assessment.failing_concept_ids:
                continue
            path_concepts = tuple(value for edge in prerequisite.path
                                  for value in (edge.source_node_id, edge.target_node_id))
            issue = _graph_issue(state, concepts=path_concepts)
            if issue is not None:
                return _blocked(state, issue)
            return _decision(
                state, PlannerRule.ASSESSMENT_FAILURE, PlannerAction.TEACH_PREREQUISITE,
                ReasonCode.LOW_PREREQ_MASTERY, "Teach the first caller-ranked weak prerequisite.",
                target=prerequisite.stable_concept_id, evidence_ids=prerequisite.evidence_ids,
                confidence=prerequisite.confidence, return_to=assessment.topic_id,
                edge_ids=tuple(edge.edge_id for edge in prerequisite.path),
            )
        return _decision(
            state, PlannerRule.ASSESSMENT_FAILURE, PlannerAction.RETEACH_WITH_NEW_STRATEGY,
            ReasonCode.REPEATED_FAILURE,
            "Reteach the failed topic; no executable weak prerequisite.",
            target=assessment.topic_id, evidence_ids=assessment.evidence_ids,
            confidence=assessment.confidence,
        )

    # 6. Authorized topic progression. Prerequisite validation authorizes this branch;
    # it never turns a proposed/rejected/informational edge into a hard gate.
    topic = state.topic
    if topic is not None:
        issue = _graph_issue(state, topics=(topic.topic_id,), concepts=topic.core_concept_ids)
        if issue is not None:
            return _blocked(state, issue)
        if state.target_topic_id is not None and state.target_topic_id != topic.topic_id:
            return _blocked(state, "TOPIC_CONTEXT_MISMATCH")
        if not topic.authorized or not topic.prerequisites_evaluated:
            return _blocked(state, "MISSING_TOPIC_AUTHORIZATION")
        for gate in topic.prerequisite_gates:
            edge = gate.edge
            if (edge.edge_type != EdgeType.PREREQUISITE_OF or edge.status != EdgeStatus.CONFIRMED
                    or edge.target_node_id not in topic.core_concept_ids):
                continue
            issue = _graph_issue(state, concepts=(edge.source_node_id, edge.target_node_id))
            if issue is not None:
                return _blocked(state, issue)
            if gate.satisfied is None:
                return _blocked(state, "MISSING_PREREQUISITE_GATE_RESULT")
            if not gate.satisfied:
                return _decision(
                    state, PlannerRule.PREREQUISITE_GATE, PlannerAction.TEACH_PREREQUISITE,
                    ReasonCode.LOW_PREREQ_MASTERY, "A confirmed prerequisite blocks progression.",
                    target=edge.source_node_id, evidence_ids=gate.evidence_ids,
                    confidence=gate.confidence, return_to=topic.topic_id, edge_ids=(edge.edge_id,),
                )
        for applicable, rule, action, reason in (
            (not topic.taught, PlannerRule.TOPIC_TEACH, PlannerAction.TEACH_CURRENT_TOPIC,
             ReasonCode.TOPIC_NOT_TAUGHT),
            (not topic.checked, PlannerRule.TOPIC_CHECK, PlannerAction.GENERATE_MICRO_CHECK,
             ReasonCode.CHECK_REQUIRED),
            (not topic.quiz_completed, PlannerRule.TOPIC_QUIZ, PlannerAction.GENERATE_QUIZ,
             ReasonCode.QUIZ_REQUIRED),
        ):
            if applicable:
                return _decision(
                    state, rule, action, reason, "Proceed from the authoritative topic position.",
                    target=topic.topic_id, evidence_ids=topic.evidence_ids,
                    confidence=topic.confidence,
                )

        # 7. Advance only from a caller-evaluated satisfied gate and authorized next target.
        if topic.gate_satisfied:
            if topic.next_topic_id is None:
                return _blocked(state, "MISSING_NEXT_TOPIC")
            issue = _graph_issue(state, topics=(topic.next_topic_id,))
            if issue is not None:
                return _blocked(state, issue)
            return _decision(
                state, PlannerRule.GATE_ADVANCE, PlannerAction.ADVANCE_TOPIC,
                ReasonCode.GATE_SATISFIED, "Advance to the caller-authorized next topic.",
                target=topic.next_topic_id, evidence_ids=topic.evidence_ids,
                confidence=topic.confidence,
            )

    # 8. Pending diagnostic work follows topic progression and gate advancement (ADR 0025).
    if state.diagnostic_candidates:
        diagnostic = state.diagnostic_candidates[0]
        issue = _diagnostic_issue(state, diagnostic)
        if issue is not None:
            return _blocked(state, issue, stale=issue == "GRAPH_CONTEXT_STALE")
        return _decision(
            state, PlannerRule.DIAGNOSTIC, PlannerAction.DIAGNOSE, ReasonCode.DIAGNOSTIC_PENDING,
            "Use the first diagnostic candidate and its already-selected questions.",
            target=diagnostic.stable_concept_id, diagnostic=diagnostic,
            confidence=diagnostic.confidence,
        )

    # 9. No authoritative next action. Completion is explicit, never inferred from empty lists.
    return _decision(
        state, PlannerRule.NEEDS_STATE, PlannerAction.ASK_USER, ReasonCode.LOW_EVIDENCE,
        "No authoritative next action is available; request the missing state or learner input.",
        outcome="REQUIRE_CONFIRMATION",
    )


class PlannerPolicy:
    """Spec-named entry point; shares the same pure function as Sprint 3.5's API."""

    decide = staticmethod(decide)
