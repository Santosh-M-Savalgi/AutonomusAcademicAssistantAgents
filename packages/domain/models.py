"""Pydantic contracts locked for AAA v3 Phase 0."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.domain.enums import LearningEventType, PlannerAction, ReasonCode


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


class PlannerDecision(DomainModel):
    """Planner output constrained to the approved action vocabulary."""

    action: PlannerAction
    target_id: str
    reason_codes: list[ReasonCode]
    evidence_ids: list[UUID]
    confidence: float = Field(ge=0, le=1)
    policy_outcome: Literal["ALLOW", "REQUIRE_CONFIRMATION", "BLOCK"]
    plan_version: int = Field(ge=1)
    planner_policy_version: str
    explanation: str | None = None


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
