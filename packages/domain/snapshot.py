"""Immutable authoritative planning snapshot output; assembly remains persistence-owned."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from packages.domain.adaptation import (
    AssessmentPlanningState,
    DiagnosticCandidate,
    DiagnosticState,
    PlanningDirective,
    PlanningGraphContext,
    PlanningState,
    ProjectionFreshnessResult,
    RemediationFrame,
    ReviewCandidate,
    TopicPlanningState,
)
from packages.domain.enums import PlannerAction
from packages.domain.runtime import LearningSessionSnapshot, RuntimeValue
from packages.domain.runtime_policy import RuntimePolicy
from packages.domain.triggers import GuardCode, TriggerEvaluation

DEFAULT_RUNTIME_POLICY = RuntimePolicy()


class AuthoritativePlanningSnapshot(RuntimeValue):
    learner_id: UUID
    course_id: UUID
    session: LearningSessionSnapshot
    session_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_context: PlanningGraphContext | None = None
    topic: TopicPlanningState | None = None
    projection_freshness: tuple[ProjectionFreshnessResult, ...] = ()
    evidence_set_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_count: int = Field(default=0, ge=0)
    projection_revision_ids: tuple[UUID, ...] = ()
    review_candidates: tuple[ReviewCandidate, ...] = ()
    active_remediation: RemediationFrame | None = None
    directives: tuple[PlanningDirective, ...] = ()
    latest_assessment: AssessmentPlanningState | None = None
    diagnostic_candidates: tuple[DiagnosticCandidate, ...] = ()
    required_freshness: tuple[ProjectionFreshnessResult, ...] = ()
    trigger: TriggerEvaluation | None = None
    plan_version: int = Field(ge=1)
    frame_version: int | None = Field(default=None, ge=1)
    diagnostic_state: DiagnosticState | None = None
    cooldown_until: datetime | None = None
    runtime_policy: RuntimePolicy = DEFAULT_RUNTIME_POLICY
    guards: tuple[GuardCode, ...] = ()

    @model_validator(mode="after")
    def scope_and_order(self) -> "AuthoritativePlanningSnapshot":
        if (self.session.learner_id, self.session.course_id) != (self.learner_id, self.course_id):
            raise ValueError("Snapshot session scope conflicts")
        if self.graph_context is not None and self.graph_context.course_id != self.course_id:
            raise ValueError("Snapshot graph scope conflicts")
        if self.active_remediation is not None and (
            self.active_remediation.return_to_topic_id == self.active_remediation.target_concept_id
        ):
            raise ValueError("Remediation return target and concept must remain distinct")
        if len(set(self.projection_revision_ids)) != len(self.projection_revision_ids):
            raise ValueError("Projection revision identities must be unique")
        return self

    @property
    def planning_state(self) -> PlanningState:
        return PlanningState(
            learner_id=self.learner_id, course_id=self.course_id,
            session_id=self.session.session_id, plan_version=self.plan_version,
            planner_policy_version="planner_v1",
            hard_stop=(None if self.session.state.value != "COMPLETE" else PlannerAction.COMPLETE),
            active_remediation_frame=self.active_remediation is not None,
            remediation_frame_complete=(
                False if self.active_remediation is None else self.active_remediation.complete
            ),
            remediation_target_id=(
                None if self.active_remediation is None
                else self.active_remediation.target_concept_id
            ),
            return_to_target_id=(
                None if self.active_remediation is None
                else self.active_remediation.return_to_topic_id
            ),
            review_candidates=self.review_candidates,
            diagnostic_state=self.diagnostic_state,
            diagnostic_candidates=self.diagnostic_candidates, directives=self.directives,
            remediation_frame=self.active_remediation, topic=self.topic,
            latest_assessment=self.latest_assessment, graph_context=self.graph_context,
            required_freshness=self.required_freshness, source_event_ids=(
                () if self.trigger is None else (self.trigger.trigger_id,)
            ),
            session_complete=self.session.state.value == "COMPLETE",
        )
