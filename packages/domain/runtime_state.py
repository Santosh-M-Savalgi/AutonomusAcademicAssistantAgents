"""Additional trusted internal runtime facts; no learner-facing admission API."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from packages.domain.adaptation import PlanningDirective, PrerequisiteGate
from packages.domain.runtime import RuntimeValue, WorkerAttemptIdentity


class TopicWindow(RuntimeValue):
    window_id: UUID
    session_id: UUID
    topic_id: UUID
    graph_version_id: UUID
    version: int = Field(ge=1)
    event_id: UUID
    opened_at: datetime
    closed_at: datetime | None = None
    authorized: bool
    taught: bool = False
    checked: bool = False
    quiz_completed: bool = False
    prerequisites_evaluated: bool = False
    core_concept_ids: tuple[UUID, ...] = Field(min_length=1)
    mandatory_topic_ids: tuple[UUID, ...] = ()
    next_topic_id: UUID | None = None
    prerequisite_gates: tuple[PrerequisiteGate, ...] | None = None
    gate_satisfied: bool | None = None
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)
    gate_evidence_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    deadline_at: datetime | None = None

    @model_validator(mode="after")
    def valid_position(self) -> Self:
        if self.checked and not self.taught:
            raise ValueError("A checked topic must have been taught")
        if self.closed_at is not None and self.closed_at < self.opened_at:
            raise ValueError("Topic window cannot close before it opens")
        if self.next_topic_id == self.topic_id:
            raise ValueError("Topic cannot advance to itself")
        for values in (self.core_concept_ids, self.mandatory_topic_ids):
            if len(set(values)) != len(values):
                raise ValueError("Topic fact identities must be unique")
        return self


class DirectiveState(StrEnum):
    PENDING = "PENDING"
    WITHDRAWN = "WITHDRAWN"
    CONSUMED = "CONSUMED"


class RuntimeDirective(RuntimeValue):
    directive: PlanningDirective
    session_id: UUID
    graph_version_id: UUID
    version: int = Field(ge=1)
    event_id: UUID
    valid_from: datetime
    expires_at: datetime | None = None
    state: DirectiveState = DirectiveState.PENDING

    @model_validator(mode="after")
    def expiration(self) -> Self:
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("Directive expiry must follow validity start")
        return self


class AssessmentKind(StrEnum):
    CHECK = "CHECK"
    QUIZ = "QUIZ"


class AssessmentBatch(RuntimeValue):
    batch_id: UUID
    window_id: UUID
    event_id: UUID
    kind: AssessmentKind
    attempt_ids: tuple[UUID, ...] = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    completed_at: datetime
    failing_concept_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def items(self) -> Self:
        if len(set(self.attempt_ids)) != len(self.attempt_ids):
            raise ValueError("A batch cannot count one learner attempt twice")
        if len(set(self.failing_concept_ids)) != len(self.failing_concept_ids):
            raise ValueError("Assessment failure concepts must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Assessment evidence IDs must be unique")
        return self


class WorkerExecutionLink(RuntimeValue):
    worker: WorkerAttemptIdentity
    execution_id: UUID
