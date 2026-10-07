"""Immutable contracts for Sprint 3.5 review and diagnostic adaptation."""

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from packages.domain.enums import PlannerAction
from packages.domain.graph import GraphEdge
from packages.domain.models import DomainModel


class FrozenAdaptationModel(DomainModel):
    """Strict immutable base for pure adaptation values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Adaptation timestamps must be timezone-aware")
    return value.astimezone(UTC)


class ReviewDueReason(StrEnum):
    """Independent reasons why a concept is eligible for review."""

    MASTERY_BELOW_THRESHOLD = "MASTERY_BELOW_THRESHOLD"
    REVIEW_OVERDUE = "REVIEW_OVERDUE"


class ProjectionFreshness(StrEnum):
    """Freshness states exposed by the review selector boundary."""

    FRESH = "FRESH"
    MISSING_PROJECTION = "MISSING_PROJECTION"
    MISSING_REVISION = "MISSING_REVISION"
    EVIDENCE_SET_STALE = "EVIDENCE_SET_STALE"
    GRAPH_CONTEXT_STALE = "GRAPH_CONTEXT_STALE"


class ProjectionFreshnessResult(FrozenAdaptationModel):
    """Typed projection/freshness result without read-time mutation."""

    learner_id: UUID
    course_id: UUID
    stable_concept_id: UUID
    state: ProjectionFreshness
    projection_head_id: UUID | None = None
    projection_revision_id: UUID | None = None
    expected_evidence_set_digest: str | None = None
    observed_evidence_set_digest: str | None = None
    expected_graph_version_id: UUID | None = None
    observed_graph_version_id: UUID | None = None


class ReviewScheduleState(FrozenAdaptationModel):
    """Current durable scheduling state for one learner/course/concept key."""

    learner_id: UUID
    course_id: UUID
    stable_concept_id: UUID
    graph_version_id: UUID | None = None
    review_policy_version: str = Field(min_length=1, max_length=64)
    review_rung: int = Field(ge=0, le=5)
    review_successes: int = Field(ge=0)
    first_concept_event_id: UUID | None = None
    first_concept_event_at: datetime | None = None
    last_successful_review_at: datetime | None = None
    last_successful_review_evidence_id: UUID | None = None
    last_successful_review_event_id: UUID | None = None
    due_at: datetime | None = None
    projection_revision_id: UUID | None = None
    evidence_set_digest: str | None = Field(default=None, min_length=64, max_length=64)
    evidence_count: int = Field(default=0, ge=0)
    schedule_cycle: str = Field(min_length=64, max_length=64)
    supporting_evidence_ids: tuple[UUID, ...] = ()
    supporting_event_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def normalize_timestamps(self) -> Self:
        for field in (
            "first_concept_event_at",
            "last_successful_review_at",
            "due_at",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _utc(value))
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("Schedule evidence IDs must be unique")
        if len(set(self.supporting_event_ids)) != len(self.supporting_event_ids):
            raise ValueError("Schedule event IDs must be unique")
        return self


class ReviewCandidate(FrozenAdaptationModel):
    """Ranked immutable review candidate supplied to the planner."""

    learner_id: UUID
    course_id: UUID
    stable_concept_id: UUID
    reasons: tuple[ReviewDueReason, ...] = Field(min_length=1)
    due_at: datetime | None = None
    decayed_mastery: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    mastery_status: Literal["UNASSESSED", "WEAK", "DEVELOPING", "PROFICIENT", "MASTERED"]
    review_successes: int = Field(ge=0)
    review_rung: int = Field(ge=0, le=5)
    projection_revision_id: UUID | None = None
    evidence_set_digest: str | None = Field(default=None, min_length=64, max_length=64)
    graph_version_id: UUID | None = None
    review_policy_version: str = Field(min_length=1, max_length=64)
    schedule_cycle: str | None = Field(default=None, min_length=64, max_length=64)
    supporting_evidence_ids: tuple[UUID, ...] = ()
    supporting_event_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def normalize_and_validate(self) -> Self:
        if self.due_at is not None:
            object.__setattr__(self, "due_at", _utc(self.due_at))
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("Review candidate reasons must be unique")
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("Candidate evidence IDs must be unique")
        if len(set(self.supporting_event_ids)) != len(self.supporting_event_ids):
            raise ValueError("Candidate event IDs must be unique")
        return self


class ReviewSelectionResult(FrozenAdaptationModel):
    """Pure selection output including unavailable projection states."""

    candidates: tuple[ReviewCandidate, ...] = ()
    unavailable: tuple[ProjectionFreshnessResult, ...] = ()


class SelfReportAssertion(FrozenAdaptationModel):
    """Immutable learner assertion that seeds the weak Beta prior once."""

    assertion_id: UUID
    learner_id: UUID
    actor_id: UUID
    course_id: UUID
    stable_concept_id: UUID
    graph_version_id: UUID | None = None
    occurred_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=255)
    policy_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def normalize_timestamp(self) -> Self:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        return self


class SelfReportPriorContribution(FrozenAdaptationModel):
    """Replay-ready immutable prior contribution derived from an assertion."""

    assertion_id: UUID
    learner_id: UUID
    course_id: UUID
    stable_concept_id: UUID
    graph_version_id: UUID | None = None
    occurred_at: datetime
    alpha_delta: float = Field(default=1.0, ge=0)
    beta_delta: float = Field(default=0.0, ge=0)
    policy_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def normalize_and_lock_delta(self) -> Self:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        if self.alpha_delta != 1.0 or self.beta_delta != 0.0:
            raise ValueError("Self-report prior must contribute alpha=1 and beta=0")
        return self


class DiagnosticConceptState(FrozenAdaptationModel):
    """Current diagnostic eligibility and actual Beta confidence."""

    stable_concept_id: UUID
    confidence: float = Field(ge=0, le=1)
    diagnostic_assessed: bool = False


class DiagnosticState(FrozenAdaptationModel):
    """Bounded, deterministic state for one diagnostic run."""

    diagnostic_run_id: UUID
    learner_id: UUID
    course_id: UUID
    graph_version_id: UUID
    diagnostic_policy_version: str = Field(min_length=1, max_length=64)
    item_budget: int = Field(default=12, ge=0, le=12)
    selected_concept_ids: tuple[UUID, ...] = ()
    attempted_question_version_ids: tuple[UUID, ...] = ()
    diagnostic_assessed_concept_ids: tuple[UUID, ...] = ()
    remaining_item_budget: int = Field(default=12, ge=0, le=12)

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        for values, label in (
            (self.selected_concept_ids, "selected concepts"),
            (self.attempted_question_version_ids, "attempted questions"),
            (self.diagnostic_assessed_concept_ids, "assessed concepts"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"Diagnostic {label} must be unique")
        if self.remaining_item_budget > self.item_budget:
            raise ValueError("Remaining diagnostic budget cannot exceed total budget")
        return self


class DiagnosticCandidate(FrozenAdaptationModel):
    """Pure diagnostic concept ranking and question inventory result."""

    stable_concept_id: UUID
    score: float = Field(ge=0)
    descendant_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    topological_rank: int = Field(ge=0)
    question_version_ids: tuple[UUID, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_questions(self) -> Self:
        if len(set(self.question_version_ids)) != len(self.question_version_ids):
            raise ValueError("Diagnostic question versions must be unique")
        return self


class DiagnosticInferenceProvenance(FrozenAdaptationModel):
    """Causal provenance retained for one inferred prerequisite contribution."""

    learner_id: UUID
    diagnostic_run_id: UUID
    source_attempt_id: UUID
    source_question_version_id: UUID
    source_evidence_id: UUID
    source_graph_version_id: UUID
    confirmed_edge_ids: tuple[UUID, ...] = Field(min_length=1)
    target_prerequisite_concept_id: UUID

    @model_validator(mode="after")
    def validate_edges(self) -> Self:
        if len(set(self.confirmed_edge_ids)) != len(self.confirmed_edge_ids):
            raise ValueError("Confirmed diagnostic edge IDs must be unique")
        return self


class DirectiveKind(StrEnum):
    """Explicit directives from §6.4; no free-form interpretation."""

    SKIP = "SKIP"
    EXPLAIN_SIMPLER = "EXPLAIN_SIMPLER"
    MORE_PRACTICE = "MORE_PRACTICE"
    I_KNOW_THIS = "I_KNOW_THIS"


class PlanningDirective(FrozenAdaptationModel):
    directive_id: UUID
    kind: DirectiveKind
    target_id: UUID
    source: Literal["LEARNER", "SYSTEM"] = "LEARNER"


class PlanningGraphContext(FrozenAdaptationModel):
    """Caller-validated vocabulary for a published graph and its current identity."""

    course_id: UUID
    graph_version_id: UUID
    current_graph_version_id: UUID
    topic_ids: tuple[UUID, ...]
    concept_ids: tuple[UUID, ...]
    mandatory_topic_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_vocabulary(self) -> Self:
        for values in (self.topic_ids, self.concept_ids, self.mandatory_topic_ids):
            if len(set(values)) != len(values):
                raise ValueError("Planning graph identifiers must be unique")
        if not set(self.mandatory_topic_ids) <= set(self.topic_ids):
            raise ValueError("Mandatory topics must belong to the graph")
        if set(self.topic_ids) & set(self.concept_ids):
            raise ValueError("Graph topic and concept identities must be disjoint")
        return self


class RemediationFrame(FrozenAdaptationModel):
    """Continuation facts only; the executor owns frame pushes, pops and attempts."""

    frame_id: UUID
    target_concept_id: UUID
    return_to_topic_id: UUID
    complete: bool = False
    continuation_action: Literal[
        PlannerAction.PRACTICE_CONCEPT, PlannerAction.GENERATE_MICRO_CHECK,
        PlannerAction.GENERATE_QUIZ,
    ] = PlannerAction.PRACTICE_CONCEPT
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)


class PrerequisiteGate(FrozenAdaptationModel):
    """Pre-evaluated gate for one prerequisite -> dependent relationship."""

    edge: GraphEdge
    satisfied: bool | None
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)


class WeakPrerequisiteCandidate(FrozenAdaptationModel):
    """Caller-ranked weak prerequisite with an ordered causal path, not a raw DAG."""

    stable_concept_id: UUID
    path: tuple[GraphEdge, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if self.path[0].source_node_id != self.stable_concept_id:
            raise ValueError("Prerequisite path must start at the candidate")
        if any(left.target_node_id != right.source_node_id
               for left, right in zip(self.path, self.path[1:], strict=False)):
            raise ValueError("Prerequisite path edges must be contiguous")
        return self


class AssessmentPlanningState(FrozenAdaptationModel):
    topic_id: UUID
    failing_concept_ids: tuple[UUID, ...] = Field(min_length=1)
    weak_prerequisites: tuple[WeakPrerequisiteCandidate, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(ge=0, le=1)


class TopicPlanningState(FrozenAdaptationModel):
    """Authoritative learning position and gate results computed outside planning."""

    topic_id: UUID
    core_concept_ids: tuple[UUID, ...] = Field(min_length=1)
    authorized: bool = False
    taught: bool = False
    checked: bool = False
    quiz_completed: bool = False
    prerequisites_evaluated: bool = False
    prerequisite_gates: tuple[PrerequisiteGate, ...] = ()
    gate_satisfied: bool | None = None
    next_topic_id: UUID | None = None
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        if self.checked and not self.taught:
            raise ValueError("A topic check requires teaching to be complete")
        if self.quiz_completed and not self.checked:
            raise ValueError("A completed quiz requires a completed topic check")
        if self.next_topic_id == self.topic_id:
            raise ValueError("Topic advancement cannot target the current topic")
        if len(set(self.core_concept_ids)) != len(self.core_concept_ids):
            raise ValueError("Topic core concepts must be unique")
        edge_ids = [gate.edge.edge_id for gate in self.prerequisite_gates]
        if len(set(edge_ids)) != len(edge_ids):
            raise ValueError("Prerequisite gates must be unique")
        return self


class PlanningState(FrozenAdaptationModel):
    """Pure planner input; authoritative calculations and execution live outside it."""

    learner_id: UUID
    course_id: UUID
    session_id: UUID
    plan_version: int = Field(ge=1)
    planner_policy_version: str = Field(min_length=1, max_length=64)
    hard_stop: PlannerAction | None = None
    pending_user_directive: PlannerAction | None = None
    active_remediation_frame: bool = False
    remediation_frame_complete: bool = False
    remediation_target_id: UUID | None = None
    return_to_target_id: UUID | None = None
    review_candidates: tuple[ReviewCandidate, ...] = ()
    diagnostic_state: DiagnosticState | None = None
    diagnostic_target_id: UUID | None = None
    target_topic_id: UUID | None = None
    session_complete: bool = False
    user_paused: bool = False
    budget_exceeded: bool = False
    directives: tuple[PlanningDirective, ...] = ()
    remediation_frame: RemediationFrame | None = None
    diagnostic_candidates: tuple[DiagnosticCandidate, ...] = ()
    topic: TopicPlanningState | None = None
    latest_assessment: AssessmentPlanningState | None = None
    graph_context: PlanningGraphContext | None = None
    required_freshness: tuple[ProjectionFreshnessResult, ...] = ()
    source_event_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_planning_input(self) -> Self:
        if len(self.review_candidates) > 3:
            raise ValueError("Planner consumes at most three selected review candidates")
        for values in (
            tuple(item.stable_concept_id for item in self.review_candidates),
            tuple(item.stable_concept_id for item in self.diagnostic_candidates),
            tuple(item.directive_id for item in self.directives),
            self.source_event_ids,
        ):
            if len(set(values)) != len(values):
                raise ValueError("Planning input identifiers must be unique")
        question_ids = [question_id for item in self.diagnostic_candidates
                        for question_id in item.question_version_ids]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("Selected diagnostic questions cannot repeat")
        return self

    def canonical_bytes(self) -> bytes:
        """Stable snapshot serialization; candidate tuple ordering is meaningful."""

        data = self.model_dump(mode="json")
        data["directives"].sort(key=lambda item: item["directive_id"])
        data["required_freshness"].sort(key=lambda item: (
            item["learner_id"], item["course_id"], item["stable_concept_id"], item["state"],
        ))
        data["source_event_ids"].sort()
        graph = data["graph_context"]
        if graph is not None:
            for name in ("topic_ids", "concept_ids", "mandatory_topic_ids"):
                graph[name].sort()
        return json.dumps(
            data, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
