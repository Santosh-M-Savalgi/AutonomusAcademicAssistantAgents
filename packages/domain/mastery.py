"""Immutable contracts shared by the pure Sprint 3.4 mastery engine."""

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.domain.adaptation import DiagnosticInferenceProvenance


class FrozenDomainModel(BaseModel):
    """Strict immutable model used for data crossing the mastery boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


EvidenceKind = Literal["DIRECT", "INFERRED"]
GraderLevel = Literal["L0_RULE", "L1_TESTS", "L2_LLM_RUBRIC", "L3_ESCALATED"]
QuestionType = Literal["MCQ", "TRUE_FALSE", "NUMERIC", "SHORT_TEXT", "CODE"]
ConceptRole = Literal["PRIMARY", "PREREQUISITE"]
MasteryStatus = Literal["UNASSESSED", "WEAK", "DEVELOPING", "PROFICIENT", "MASTERED"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Mastery timestamps must be timezone-aware")
    return value.astimezone(UTC)


class ConceptRoleSnapshot(FrozenDomainModel):
    """Immutable role attribution captured with one evidence item."""

    stable_concept_id: UUID
    role: ConceptRole


class QuestionVersionSnapshot(FrozenDomainModel):
    """Question metadata copied into an attempt/evidence source snapshot."""

    question_id: UUID
    question_version_id: UUID
    course_id: UUID
    graph_version_id: UUID
    difficulty: Literal[1, 2, 3, 4, 5]
    question_type: QuestionType
    n_options: int | None = Field(default=None, ge=2)
    tag_confidence: float = Field(ge=0, le=1)
    is_review: bool
    available_at: datetime

    @model_validator(mode="after")
    def validate_options(self) -> Self:
        if self.question_type == "MCQ" and self.n_options is None:
            raise ValueError("MCQ question versions require n_options")
        if self.question_type != "MCQ" and self.n_options is not None:
            raise ValueError("Only MCQ question versions may define n_options")
        return self

    @model_validator(mode="after")
    def normalize_timestamp(self) -> Self:
        object.__setattr__(self, "available_at", _utc(self.available_at))
        return self


class AttemptSnapshot(FrozenDomainModel):
    """Immutable attempt context used to validate and replay evidence."""

    attempt_id: UUID
    learner_id: UUID
    actor_id: UUID | None = None
    question_version_id: UUID
    course_id: UUID
    graph_version_id: UUID
    occurred_at: datetime
    is_review: bool

    @model_validator(mode="after")
    def normalize_timestamp(self) -> Self:
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        return self


class WeightSnapshot(FrozenDomainModel):
    """Exact factors used by the engine, retained for deterministic replay."""

    correct_difficulty_weight: float = Field(gt=0)
    incorrect_difficulty_weight: float = Field(gt=0)
    type_weight: float = Field(gt=0)
    correct_hint_factor: float = Field(gt=0)
    tag_confidence: float = Field(ge=0.5, le=1.0)
    w_correct: float = Field(gt=0)
    w_incorrect: float = Field(gt=0)


class EvidenceInput(FrozenDomainModel):
    """Validated immutable evidence input before server receipt timestamps."""

    evidence_id: UUID
    learner_id: UUID
    actor_id: UUID | None = None
    course_id: UUID
    question_id: UUID
    question_version_id: UUID
    attempt_id: UUID
    correct: float = Field(ge=0, le=1)
    difficulty: Literal[1, 2, 3, 4, 5]
    question_type: QuestionType
    n_options: int | None = Field(default=None, ge=2)
    hints_used: int = Field(ge=0)
    grader_level: GraderLevel
    grader_confidence: float = Field(ge=0, le=1)
    kind: EvidenceKind
    occurred_at: datetime
    graph_version_id: UUID
    concept_roles: tuple[ConceptRoleSnapshot, ...] = Field(min_length=1)
    tag_confidence: float = Field(ge=0, le=1)
    is_review: bool
    idempotency_key: str = Field(min_length=1, max_length=255)
    diagnostic_provenance: DiagnosticInferenceProvenance | None = None

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        if self.question_type == "MCQ" and self.n_options is None:
            raise ValueError("MCQ evidence requires n_options")
        if self.question_type != "MCQ" and self.n_options is not None:
            raise ValueError("Only MCQ evidence may define n_options")
        concept_ids = [item.stable_concept_id for item in self.concept_roles]
        if len(set(concept_ids)) != len(concept_ids):
            raise ValueError("Evidence cannot contain duplicate concept role snapshots")
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        return self


class EvidenceRecord(EvidenceInput):
    """Evidence with immutable database receipt/application timestamps."""

    recorded_at: datetime
    applied_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_receipts(self) -> Self:
        object.__setattr__(self, "recorded_at", _utc(self.recorded_at))
        if self.applied_at is not None:
            object.__setattr__(self, "applied_at", _utc(self.applied_at))
        return self


class MasteryState(FrozenDomainModel):
    """Posterior and counters for one learner/course/concept key."""

    alpha: float = Field(ge=0)
    beta: float = Field(ge=0)
    n_direct: int = Field(default=0, ge=0)
    distinct_direct_question_ids: tuple[UUID, ...] = ()
    review_successes: int = Field(default=0, ge=0)
    review_rung: int = Field(default=0, ge=0, le=5)
    has_qualifying_review: bool = False
    self_report_prior_applied: bool = False
    last_occurred_at: datetime | None = None
    last_successful_review_at: datetime | None = None
    last_successful_review_evidence_id: UUID | None = None
    last_successful_review_event_id: UUID | None = None

    @model_validator(mode="after")
    def normalize_timestamp(self) -> Self:
        if self.alpha + self.beta <= 0:
            raise ValueError("Beta posterior must have a positive denominator")
        if self.last_occurred_at is not None:
            object.__setattr__(self, "last_occurred_at", _utc(self.last_occurred_at))
        if self.last_successful_review_at is not None:
            object.__setattr__(
                self, "last_successful_review_at", _utc(self.last_successful_review_at),
            )
        if len(set(self.distinct_direct_question_ids)) != len(self.distinct_direct_question_ids):
            raise ValueError("Distinct direct question IDs must be unique")
        return self


class MasteryMetrics(FrozenDomainModel):
    """Derived Beta values and status at a requested projection time."""

    n_eff: float = Field(ge=0)
    mastery: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    status: MasteryStatus


class ConceptMastery(FrozenDomainModel):
    stable_concept_id: UUID
    state: MasteryState
    metrics: MasteryMetrics


class EvidenceContribution(FrozenDomainModel):
    """Auditable per-concept effect of one evidence item."""

    evidence_id: UUID
    stable_concept_id: UUID
    alpha_delta: float = Field(ge=0)
    beta_delta: float = Field(ge=0)
    applied: bool
    reason: str | None = None


class ReplayResult(FrozenDomainModel):
    """Pure replay output; persistence decides how and when to store it."""

    projections: tuple[ConceptMastery, ...]
    contributions: tuple[EvidenceContribution, ...]
    evidence_set_digest: str
    evidence_count: int = Field(ge=0)
    max_occurred_at: datetime | None = None
    max_evidence_id: UUID | None = None
    as_of: datetime
    self_report_prior_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def normalize_timestamps(self) -> Self:
        object.__setattr__(self, "as_of", _utc(self.as_of))
        if self.max_occurred_at is not None:
            object.__setattr__(self, "max_occurred_at", _utc(self.max_occurred_at))
        return self


class MasteryUpdateResult(FrozenDomainModel):
    """Logical result returned by an evidence application or exact replay."""

    evidence_id: UUID
    projection_ids: tuple[UUID, ...]
    projections: tuple[ConceptMastery, ...]
    duplicate: bool = False
