"""Detached Stage 2 runtime contracts; no assembly, publication or execution."""

import json
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ConfigDict, Field, field_validator, model_validator

from packages.domain.adaptation import DiagnosticInferenceProvenance, DiagnosticState, PlanningState
from packages.domain.models import DomainModel, PlannerDecision


class RuntimeValue(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Runtime timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return value

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")

    def _identity(self, kind: str) -> UUID:
        return uuid5(NAMESPACE_URL, f"aaa:runtime:{kind}:v1:{self.canonical_bytes().decode()}")


class SourceKind(StrEnum):
    OUTCOME = "OUTCOME"
    EVENT = "EVENT"
    DIRECTIVE = "DIRECTIVE"
    SESSION = "SESSION"


class SourceIdentity(RuntimeValue):
    kind: SourceKind
    source_id: UUID

    @property
    def identity_id(self) -> UUID:
        return self._identity("source")


class TriggerIdentity(RuntimeValue):
    learner_id: UUID
    source: SourceIdentity
    trigger_kind: str = Field(min_length=1, max_length=64)
    window_id: UUID | None = None

    @property
    def trigger_id(self) -> UUID:
        return self._identity("trigger")


class PlanVersionIdentity(RuntimeValue):
    session_id: UUID
    trigger_id: UUID
    version: int = Field(ge=1)

    @property
    def plan_version_id(self) -> UUID:
        return self._identity("plan")


class ExecutionIdentity(RuntimeValue):
    plan_version_id: UUID

    @property
    def execution_id(self) -> UUID:
        # One educational execution per immutable decision, across all deliveries.
        return self._identity("execution")


class WorkerAttemptIdentity(RuntimeValue):
    job_id: UUID
    attempt: int = Field(ge=1)

    @property
    def worker_attempt_id(self) -> UUID:
        return self._identity("worker-attempt")


class SessionState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RETRIEVING = "RETRIEVING"
    TEACHING = "TEACHING"
    CHECKPOINT = "CHECKPOINT"
    ASSESSING = "ASSESSING"
    DIAGNOSING = "DIAGNOSING"
    REPLANNING = "REPLANNING"
    ADVANCE = "ADVANCE"
    PAUSED = "PAUSED"
    NEEDS_STATE = "NEEDS_STATE"
    COMPLETE = "COMPLETE"


_PROGRESSION = {
    SessionState.CREATED: {SessionState.PLANNING},
    SessionState.PLANNING: {SessionState.RETRIEVING, SessionState.TEACHING,
                            SessionState.DIAGNOSING, SessionState.COMPLETE},
    SessionState.RETRIEVING: {SessionState.TEACHING, SessionState.REPLANNING},
    SessionState.TEACHING: {SessionState.CHECKPOINT, SessionState.REPLANNING},
    SessionState.CHECKPOINT: {SessionState.ASSESSING, SessionState.REPLANNING},
    SessionState.ASSESSING: {SessionState.DIAGNOSING, SessionState.REPLANNING},
    SessionState.DIAGNOSING: {SessionState.REPLANNING},
    SessionState.REPLANNING: {SessionState.RETRIEVING, SessionState.TEACHING,
                              SessionState.DIAGNOSING, SessionState.ADVANCE,
                              SessionState.COMPLETE},
    SessionState.ADVANCE: {SessionState.PLANNING},
    SessionState.PAUSED: {SessionState.PLANNING},
    SessionState.NEEDS_STATE: {SessionState.PLANNING},
    SessionState.COMPLETE: set(),
}
SESSION_TRANSITIONS = MappingProxyType({
    state: frozenset(
        successors | {state, SessionState.PAUSED, SessionState.NEEDS_STATE}
        if state != SessionState.COMPLETE else successors
    ) for state, successors in _PROGRESSION.items()
})


class SessionTransition(RuntimeValue):
    session_id: UUID
    event_id: UUID
    from_state: SessionState
    to_state: SessionState
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=2)
    occurred_at: datetime
    plan_version_id: UUID | None = None
    execution_id: UUID | None = None

    @model_validator(mode="after")
    def legal_transition(self) -> Self:
        if self.to_state not in SESSION_TRANSITIONS[self.from_state]:
            raise ValueError("Illegal session transition")
        if self.to_version != self.from_version + 1:
            raise ValueError("Session transition must increment the version exactly once")
        if self.execution_id is not None and self.plan_version_id is None:
            raise ValueError("An execution-linked transition requires its plan version")
        return self


class LearningSessionSnapshot(RuntimeValue):
    session_id: UUID
    learner_id: UUID
    course_id: UUID
    state: SessionState
    version: int = Field(ge=1)
    graph_version_id: UUID | None = None
    current_topic_id: UUID | None = None
    current_plan_version_id: UUID | None = None
    active_frame_id: UUID | None = None
    last_event_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def lifecycle(self) -> Self:
        if (self.state == SessionState.COMPLETE) != (self.completed_at is not None):
            raise ValueError("Only a complete session has a completion timestamp")
        if self.current_topic_id is not None and self.graph_version_id is None:
            raise ValueError("Learning position requires a graph version")
        if self.updated_at < self.created_at:
            raise ValueError("Session update cannot precede creation")
        if self.completed_at is not None and not (
            self.created_at <= self.completed_at <= self.updated_at
        ):
            raise ValueError("Session completion must be within its lifecycle")
        return self


class LearningPlan(RuntimeValue):
    plan_id: UUID
    session_id: UUID
    learner_id: UUID
    course_id: UUID
    created_at: datetime


def deterministic_plan_id(session_id: UUID) -> UUID:
    """Return the one immutable plan aggregate identity owned by a session."""

    return uuid5(NAMESPACE_URL, f"aaa:runtime:learning-plan:v1:{session_id}")


class DurablePlanVersion(RuntimeValue):
    plan: LearningPlan
    identity: PlanVersionIdentity
    source: SourceIdentity
    source_event_id: UUID
    session_version: int = Field(ge=1)
    frame_id: UUID | None = None
    frame_version: int | None = Field(default=None, ge=1)
    curriculum_revision_id: UUID | None = None
    graph_version_id: UUID | None = None
    mastery_policy_version: str = Field(min_length=1, max_length=64)
    snapshot: PlanningState
    decision: PlannerDecision
    supersedes_version_id: UUID | None = None
    source_snapshot_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    schema_version: Literal["runtime-v1"] = "runtime-v1"

    @property
    def snapshot_bytes(self) -> bytes:
        return self.snapshot.canonical_bytes()

    @property
    def snapshot_digest(self) -> str:
        return sha256(self.snapshot_bytes).hexdigest()

    @property
    def decision_bytes(self) -> bytes:
        return self.decision.canonical_bytes()

    @property
    def decision_digest(self) -> str:
        return sha256(self.decision_bytes).hexdigest()

    @model_validator(mode="after")
    def matching_context(self) -> Self:
        scope = (self.plan.learner_id, self.plan.course_id, self.plan.session_id)
        if scope != (self.snapshot.learner_id, self.snapshot.course_id, self.snapshot.session_id):
            raise ValueError("Plan and planning snapshot scopes must match")
        if self.identity.session_id != self.plan.session_id:
            raise ValueError("Plan identity must belong to its session")
        if self.identity.version != self.snapshot.plan_version or (
            self.decision.plan_version != self.identity.version
        ):
            raise ValueError("Plan, snapshot and decision versions must match")
        provenance = self.decision.provenance
        if provenance is None or scope != (
            provenance.learner_id, provenance.course_id, provenance.session_id,
        ) or provenance.state_digest != self.snapshot_digest:
            raise ValueError("Decision must retain the exact planning snapshot provenance")
        graph = self.snapshot.graph_context
        if self.graph_version_id != (None if graph is None else graph.graph_version_id):
            raise ValueError("Plan must retain the snapshot graph identity")
        if provenance.graph_version_id != self.graph_version_id or (
            (self.graph_version_id is None) != (self.curriculum_revision_id is None)
        ):
            raise ValueError("Graph and curriculum revision provenance must be paired")
        frame = self.snapshot.remediation_frame
        if self.frame_id != (None if frame is None else frame.frame_id) or (
            (self.frame_id is None) != (self.frame_version is None)
        ) or (self.snapshot.active_remediation_frame and frame is None):
            raise ValueError("Active remediation requires a versioned durable frame")
        if self.decision.planner_policy_version != self.snapshot.planner_policy_version:
            raise ValueError("Planner policy versions must match")
        if (self.identity.version == 1) != (self.supersedes_version_id is None):
            raise ValueError("Every later plan version must link its predecessor")
        if self.supersedes_version_id == self.identity.plan_version_id:
            raise ValueError("A plan version cannot supersede itself")
        if self.created_at < self.plan.created_at:
            raise ValueError("Plan version cannot precede its plan")
        return self


class FrameState(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    RETURNED = "RETURNED"
    BLOCKED_NEEDS_HUMAN = "BLOCKED_NEEDS_HUMAN"


class RemediationFrameSnapshot(RuntimeValue):
    frame_id: UUID
    session_id: UUID
    graph_version_id: UUID
    target_concept_id: UUID
    return_to_topic_id: UUID
    created_by_execution_id: UUID
    parent_frame_id: UUID | None = None
    depth: int = Field(ge=1)
    state: FrameState
    version: int = Field(ge=1)
    rung: int = Field(ge=0)
    strategy: str = Field(min_length=1, max_length=64)
    guard_policy_version: str = Field(min_length=1, max_length=64)
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    min_progress_delta: float = Field(ge=0, le=1)
    baseline_mastery: float = Field(ge=0, le=1)
    latest_mastery: float = Field(ge=0, le=1)
    last_event_id: UUID
    returned_by_execution_id: UUID | None = None
    returned_at: datetime | None = None

    @property
    def progress_delta(self) -> float:
        return self.latest_mastery - self.baseline_mastery

    @model_validator(mode="after")
    def frame_bounds(self) -> Self:
        if self.attempt_count > self.max_attempts:
            raise ValueError("Frame attempts exceed the configured rung budget")
        if (self.depth == 1) != (self.parent_frame_id is None) or (
            self.parent_frame_id == self.frame_id
        ):
            raise ValueError("Frame stack must retain a distinct parent above depth one")
        if (self.state == FrameState.RETURNED) != (self.returned_at is not None):
            raise ValueError("Only a returned frame has a return timestamp")
        if (self.state == FrameState.RETURNED) != (self.returned_by_execution_id is not None):
            raise ValueError("Frame return requires its owning execution")
        return self


class FrameAttempt(RuntimeValue):
    frame_id: UUID
    source_attempt_id: UUID
    event_id: UUID
    rung: int = Field(ge=0)
    observed_mastery: float = Field(ge=0, le=1)
    occurred_at: datetime


class ExecutionState(StrEnum):
    PENDING = "PENDING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


TERMINAL_EXECUTION_STATES = frozenset({
    ExecutionState.COMPLETED, ExecutionState.BLOCKED, ExecutionState.STALE,
    ExecutionState.SUPERSEDED, ExecutionState.FAILED,
})


class ExecutionReceipt(RuntimeValue):
    identity: ExecutionIdentity
    plan: DurablePlanVersion
    state: ExecutionState
    version: int = Field(ge=1)
    confirmation_event_id: UUID | None = None
    child_job_ids: tuple[UUID, ...] = ()
    emitted_event_ids: tuple[UUID, ...] = ()
    request_bytes: bytes = b""
    request_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_bytes: bytes | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def receipt_context(self) -> Self:
        if not self.request_bytes:
            object.__setattr__(self, "request_bytes", canonical_execution_request(self.plan))
        request_digest = sha256(self.request_bytes).hexdigest()
        if self.request_digest is not None and self.request_digest != request_digest:
            raise ValueError("Execution request digest does not match its immutable request")
        object.__setattr__(self, "request_digest", request_digest)
        if self.identity.plan_version_id != self.plan.identity.plan_version_id:
            raise ValueError("Execution identity must refer to its immutable plan version")
        terminal = self.state in TERMINAL_EXECUTION_STATES
        if terminal != (self.completed_at is not None) or terminal != (
            self.result_bytes is not None
        ):
            raise ValueError("Terminal execution requires its original result and completion time")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("Execution completion cannot precede creation")
        for values in (self.child_job_ids, self.emitted_event_ids):
            if len(values) != len(set(values)):
                raise ValueError("Receipt child identities must be unique")
        outcome = self.plan.decision.policy_outcome
        if outcome == "BLOCK" and (
            self.state not in {ExecutionState.BLOCKED, ExecutionState.STALE,
                               ExecutionState.SUPERSEDED} or self.child_job_ids
        ):
            raise ValueError("A blocked decision cannot dispatch educational work")
        if outcome == "REQUIRE_CONFIRMATION" and self.confirmation_event_id is None and (
            self.state not in {ExecutionState.AWAITING_CONFIRMATION, ExecutionState.BLOCKED,
                               ExecutionState.STALE, ExecutionState.SUPERSEDED,
                               ExecutionState.FAILED} or self.child_job_ids
        ):
            raise ValueError("Educational work requires a linked confirmation event")
        return self

    @property
    def result_digest(self) -> str | None:
        return None if self.result_bytes is None else sha256(self.result_bytes).hexdigest()

    @property
    def receipt_fingerprint(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def canonical_execution_request(plan: DurablePlanVersion) -> bytes:
    """Canonical immutable input to the deterministic educational action."""

    return json.dumps({
        "plan_version_id": str(plan.identity.plan_version_id),
        "plan_id": str(plan.plan.plan_id),
        "session_id": str(plan.plan.session_id),
        "session_version": plan.session_version,
        "action": plan.decision.action,
        "target_id": plan.decision.target_id,
        "snapshot_digest": plan.snapshot_digest,
        "decision_digest": plan.decision_digest,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class DiagnosticRunState(StrEnum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class DiagnosticRunSnapshot(RuntimeValue):
    diagnostic: DiagnosticState
    session_id: UUID
    source: SourceIdentity
    source_event_id: UUID
    state: DiagnosticRunState
    version: int = Field(ge=1)
    created_at: datetime
    completed_at: datetime | None = None
    completion_event_id: UUID | None = None

    @model_validator(mode="after")
    def completion(self) -> Self:
        terminal = self.state != DiagnosticRunState.OPEN
        if terminal != (self.completed_at is not None) or terminal != (
            self.completion_event_id is not None
        ):
            raise ValueError("Closed diagnostic run requires completion time and event")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("Diagnostic completion cannot precede creation")
        return self


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    ATTEMPTED = "ATTEMPTED"
    ASSESSED = "ASSESSED"


class DiagnosticReservation(RuntimeValue):
    reservation_id: UUID
    diagnostic_run_id: UUID
    graph_version_id: UUID
    execution_id: UUID
    question_version_id: UUID
    target_concept_id: UUID
    item_budget: int = Field(ge=1, le=12)
    slot: int = Field(ge=1)
    state: ReservationState
    version: int = Field(ge=1)
    source_attempt_id: UUID | None = None
    source_evidence_id: UUID | None = None
    completion_event_id: UUID | None = None
    assessed_concept_ids: tuple[UUID, ...] = ()
    reserved_at: datetime
    attempted_at: datetime | None = None
    assessed_at: datetime | None = None

    @model_validator(mode="after")
    def reservation_bounds(self) -> Self:
        if self.slot > self.item_budget:
            raise ValueError("Reservation slot exceeds the run budget")
        attempted = self.state != ReservationState.RESERVED
        assessed = self.state == ReservationState.ASSESSED
        if attempted != (self.source_attempt_id is not None) or attempted != (
            self.attempted_at is not None
        ):
            raise ValueError("Attempted reservation requires the original attempt and time")
        if any(assessed != present for present in (
            self.source_evidence_id is not None, self.completion_event_id is not None,
            self.assessed_at is not None, bool(self.assessed_concept_ids),
        )):
            raise ValueError(
                "Assessed reservation requires source evidence, event, concepts and time",
            )
        if len(set(self.assessed_concept_ids)) != len(self.assessed_concept_ids):
            raise ValueError("Assessed concepts must be unique")
        if self.attempted_at is not None and self.attempted_at < self.reserved_at:
            raise ValueError("Diagnostic attempt cannot precede reservation")
        if self.assessed_at is not None and (
            self.attempted_at is None or self.assessed_at < self.attempted_at
        ):
            raise ValueError("Diagnostic assessment cannot precede its attempt")
        return self


class DiagnosticInferenceLink(RuntimeValue):
    """Existing inferred evidence plus its original causal path and reservation."""

    evidence_id: UUID
    reservation_id: UUID
    provenance: DiagnosticInferenceProvenance
