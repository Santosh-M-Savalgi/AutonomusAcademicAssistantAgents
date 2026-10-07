"""Pydantic contracts locked for AAA v3 Phase 0."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.domain.enums import (
    JobLane,
    JobStatus,
    JobType,
    LearningEventType,
    PlannerAction,
    PlannerRule,
    ReasonCode,
)


class DomainModel(BaseModel):
    """Base model that rejects undeclared contract fields."""

    model_config = ConfigDict(extra="forbid")


class BlockValidation(DomainModel):
    """Results of deterministic lesson-block validation."""

    citation_ok: bool
    length_ok: bool
    reading_level: bool
    duplicate_of: UUID | None = None


class VersionStamp(DomainModel):
    """Versions needed to reproduce an AI-generated artifact."""

    model_id: str
    adapter_version: str
    prompt_version: str
    retrieval_version: str
    mastery_policy_version: str
    planner_policy_version: str


class AnswerKey(DomainModel):
    """Validated answer representation for deterministic or rubric grading."""

    kind: Literal["exact", "numeric", "regex", "rubric"]
    value: str | float | list[str]
    tolerance: float | None = Field(default=None, ge=0)


class RubricItem(DomainModel):
    """One independently gradable criterion for a free-text answer."""

    criterion_id: str
    description: str
    points: float = Field(gt=0)
    required: bool = True


class PlannerDecisionProvenance(DomainModel):
    """Detached audit context; contains identifiers and facts, never execution handles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: PlannerRule
    learner_id: UUID
    course_id: UUID
    session_id: UUID
    state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_version_id: UUID | None = None
    directive_id: UUID | None = None
    remediation_frame_id: UUID | None = None
    return_to_topic_id: UUID | None = None
    diagnostic_run_id: UUID | None = None
    diagnostic_policy_version: str | None = None
    question_version_ids: tuple[UUID, ...] = ()
    source_event_ids: tuple[UUID, ...] = ()
    prerequisite_edge_ids: tuple[UUID, ...] = ()
    projection_revision_id: UUID | None = None
    evidence_set_digest: str | None = None
    review_reasons: tuple[Literal["MASTERY_BELOW_THRESHOLD", "REVIEW_OVERDUE"], ...] = ()
    state_issue: str | None = None


class PlannerDecision(DomainModel):
    """Planner output constrained to the approved action vocabulary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: PlannerAction
    target_id: str
    reason_codes: tuple[ReasonCode, ...]
    evidence_ids: tuple[UUID, ...]
    confidence: float = Field(ge=0, le=1)
    policy_outcome: Literal["ALLOW", "REQUIRE_CONFIRMATION", "BLOCK"]
    plan_version: int = Field(ge=1)
    planner_policy_version: str
    explanation: str | None = None
    provenance: PlannerDecisionProvenance | None = None

    def canonical_bytes(self) -> bytes:
        """Stable JSON bytes; tuples retain the existing JSON array representation."""

        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")


class LessonBlock(DomainModel):
    """A grounded or explicitly ungrounded unit of lesson content."""

    block_type: Literal[
        "OVERVIEW",
        "EXPLANATION",
        "INTUITION",
        "EXAMPLE",
        "ANALOGY",
        "CODE",
        "MATH",
        "DIAGRAM",
        "TABLE",
        "WARNING",
        "MISCONCEPTION",
        "PRACTICE",
        "CHECKPOINT",
        "SUMMARY",
        "RESOURCE",
    ]
    concept_ids: list[str]
    content_md: str
    difficulty: Literal["easy", "medium", "hard"]
    source_chunk_ids: list[UUID]
    grounded: bool
    validation: BlockValidation
    versions: VersionStamp


class Question(DomainModel):
    """Assessment item with closed-vocabulary concept and provenance fields."""

    question_id: UUID
    course_id: UUID
    topic_id: str
    concept_ids: list[str]
    prerequisite_concept_ids: list[str]
    learning_objective_ids: list[str]
    question_type: Literal["MCQ", "TRUE_FALSE", "NUMERIC", "SHORT_TEXT", "CODE"]
    cognitive_skill: Literal["remember", "understand", "apply", "analyze"]
    difficulty: Literal[1, 2, 3, 4, 5]
    stem: str
    options: list[str] | None
    answer_key: AnswerKey
    rubric: list[RubricItem] | None
    expected_misconception_ids: list[str]
    source_chunk_ids: list[UUID]
    lesson_block_ids: list[UUID]
    tag_confidence: float = Field(ge=0, le=1)
    fingerprint_embedding_id: UUID
    status: Literal["ACTIVE", "QUARANTINED", "RETIRED"]


class AnswerEvidence(DomainModel):
    """Idempotent evidence produced by grading an answer attempt."""

    evidence_id: UUID
    student_id: UUID
    question_id: UUID
    attempt_id: UUID
    correct: float = Field(ge=0, le=1)
    grader_level: Literal["L0_RULE", "L1_TESTS", "L2_LLM_RUBRIC", "L3_ESCALATED"]
    grader_confidence: float = Field(ge=0, le=1)
    hints_used: int = Field(ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    kind: Literal["DIRECT", "INFERRED"]
    concept_credit: dict[str, float]
    applied_at: datetime | None = None


class LearningEvent(DomainModel):
    """Append-only event envelope for learning state changes."""

    event_id: UUID
    type: LearningEventType
    student_id: UUID
    course_id: UUID
    session_id: UUID | None = None
    payload: dict[str, Any]
    causation_id: UUID | None = None
    correlation_id: UUID
    created_at: datetime
    versions: VersionStamp


EventEnvelope = LearningEvent


class JobContract(DomainModel):
    """Serializable contract for a durable, idempotent worker job."""

    id: UUID
    type: JobType
    payload: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    priority: int = 0
    lane: JobLane = JobLane.BATCH
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    run_after: datetime
    locked_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    idempotency_key: str = Field(min_length=1)
    parent_job_id: UUID | None = None
    result_ref: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
