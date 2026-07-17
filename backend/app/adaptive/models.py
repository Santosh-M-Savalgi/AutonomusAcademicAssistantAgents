"""Adaptive Learning Engine — domain dataclasses.

All types are pure, deterministic dataclasses. No LLM calls, no DB I/O.
These are the internal representations used by the adaptive engine.

Reference: Sprint 8 Parts 2-8, 10.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime


# ── Mastery Classification (Part 2) ────────────────────────────────────────


class MasteryState(str, enum.Enum):
    """Deterministic mastery classification levels.

    A topic transitions through these states according to deterministic rules:
    - NOT_STARTED → LEARNING on first lesson view.
    - LEARNING → PRACTICING on first quiz attempt.
    - PRACTICING → MASTERED when score >= threshold with confidence.
    - MASTERED → REVIEW_REQUIRED when score drops below threshold on review.
    - MASTERED → REGRESSED when repeated failures on downstream dependent topics.
    """

    NOT_STARTED = "not_started"
    LEARNING = "learning"
    PRACTICING = "practicing"
    MASTERED = "mastered"
    REVIEW_REQUIRED = "review_required"
    REGRESSED = "regressed"


class DecisionType(str, enum.Enum):
    """Types of adaptive decisions the engine can emit."""

    ADVANCE = "advance"            # proceed to next topic
    REVIEW = "review"               # review current topic
    RETEACH = "reteach"             # re-teach the current topic
    PRACTICE = "practice"           # do a practice session
    QUIZ_RETRY = "quiz_retry"       # retake the quiz
    PREREQUISITE = "prerequisite"   # go back to a prerequisite
    REMEDIATE = "remediate"         # execute a remediation plan
    HOLD = "hold"                   # wait (no action available)
    COMPLETE = "complete"           # all topics mastered


class RecommendationType(str, enum.Enum):
    """Types of recommendations the engine can generate."""

    NEXT_LESSON = "next_lesson"
    REVIEW_LESSON = "review_lesson"
    PREREQUISITE_LESSON = "prerequisite_lesson"
    PRACTICE_SESSION = "practice_session"
    QUIZ_RETRY = "quiz_retry"
    REVISION_SCHEDULE = "revision_schedule"
    REMEDIATION = "remediation"


# ── Explanation (Part 10) ──────────────────────────────────────────────────


@dataclass
class Explanation:
    """Structured explanation for every adaptive decision.

    Provides full transparency and debuggability for every routing choice.
    """

    decision: str
    """What decision was made (e.g. 'advance', 'review', 'remediate')."""

    reason: str
    """Human-readable reason for the decision."""

    evidence: list[str] = field(default_factory=list)
    """List of specific evidence items that contributed to the decision."""

    metrics_used: dict[str, float] = field(default_factory=dict)
    """Key-value map of the metrics used in the decision."""

    confidence: float = 1.0
    """Confidence in this decision (0.0–1.0)."""

    rules_triggered: list[str] = field(default_factory=list)
    """Names of rules that were triggered to reach this decision."""

    prerequisites_examined: list[str] = field(default_factory=list)
    """Names of prerequisite topics examined during diagnosis."""


# ── Mastery Evaluation Result (Part 3) ─────────────────────────────────────


@dataclass
class MasteryEvaluation:
    """Result of evaluating a topic's mastery using multiple factors."""

    topic_id: uuid.UUID
    topic_name: str
    mastery_state: MasteryState
    score: float                      # 0.0–1.0 aggregate score
    confidence: float                 # 0.0–1.0 confidence in the score
    quiz_scores: list[float] = field(default_factory=list)
    attempt_count: int = 0
    time_since_last_study_hours: float = 0.0
    historical_trend: float = 0.0     # positive = improving, negative = declining
    repeated_failures: int = 0        # consecutive sub-threshold quiz attempts
    trend_direction: str = "stable"   # improving | declining | stable
    recent_activity: bool = False     # active in the last 7 days
    factors: dict[str, float] = field(default_factory=dict)
    """Individual factor scores that contributed to the aggregate."""


# ── Diagnosis (Part 4) ─────────────────────────────────────────────────────


@dataclass
class DiagnosisReport:
    """Root-cause diagnosis when a learner repeatedly fails on a topic."""

    topic_id: uuid.UUID
    topic_name: str
    root_concept_id: uuid.UUID | None
    """The deepest prerequisite concept found to be weak."""

    root_concept_name: str | None = None
    supporting_concepts: list[uuid.UUID] = field(default_factory=list)
    """All prerequisite concepts that support the failing topic."""

    missing_prerequisites: list[uuid.UUID] = field(default_factory=list)
    """Prerequisites that are below mastery threshold."""

    reasoning_chain: list[str] = field(default_factory=list)
    """Step-by-step reasoning from the failing topic to the root cause."""

    confidence: float = 0.0
    """Confidence in the diagnosis (0.0–1.0)."""

    explanation: Explanation | None = None
    """Structured explanation of the diagnosis."""


# ── Learning Plan (Part 5) ─────────────────────────────────────────────────


@dataclass
class PlanStep:
    """A single step in an adaptive learning plan."""

    topic_id: uuid.UUID
    topic_name: str
    action: DecisionType
    priority: int = 0                # lower = higher priority
    estimated_minutes: int = 15
    reason: str = ""


@dataclass
class LearningPlan:
    """A personalized learning plan generated by the planner."""

    user_id: uuid.UUID
    steps: list[PlanStep] = field(default_factory=list)
    total_estimated_minutes: int = 0
    completion_path: list[uuid.UUID] = field(default_factory=list)
    """Ordered list of topic IDs in the estimated completion path."""
    explanation: Explanation | None = None


# ── Remediation Plan (Part 7) ──────────────────────────────────────────────


@dataclass
class RemediationPlan:
    """A focused remediation plan for a struggling learner."""

    topic_id: uuid.UUID
    topic_name: str
    weak_concepts: list[str] = field(default_factory=list)
    """Names of concepts the learner is weak on."""

    practice_recommendations: list[str] = field(default_factory=list)
    """Human-readable practice suggestions."""

    suggested_review_sequence: list[uuid.UUID] = field(default_factory=list)
    """Ordered list of topic IDs to review."""

    estimated_remediation_minutes: int = 0
    required_quizzes: int = 0
    target_mastery: float = 0.75
    explanation: Explanation | None = None


# ── Recommendation (Part 8) ────────────────────────────────────────────────


@dataclass
class Recommendation:
    """A single adaptive recommendation with explanation."""

    type: RecommendationType
    topic_id: uuid.UUID | None = None
    topic_name: str | None = None
    priority: int = 0
    reason: str = ""
    explanation: Explanation | None = None


# ── Adaptive Decision (unified) ────────────────────────────────────────────


@dataclass
class AdaptiveDecision:
    """Unified adaptive decision returned by the engine.

    Combines evaluation, diagnosis, plan, and recommendations into one
    coherent result for the API layer.
    """

    user_id: uuid.UUID
    topic_id: uuid.UUID
    evaluated_at: datetime = field(default_factory=datetime.utcnow)
    evaluation: MasteryEvaluation | None = None
    diagnosis: DiagnosisReport | None = None
    plan: LearningPlan | None = None
    recommendations: list[Recommendation] = field(default_factory=list)
    explanation: Explanation | None = None
    decision: DecisionType = DecisionType.HOLD


# ── Adaptive Status ────────────────────────────────────────────────────────


@dataclass
class AdaptiveStatus:
    """Overview of a learner's adaptive state across all topics."""

    user_id: uuid.UUID
    total_topics: int = 0
    mastered_topics: int = 0
    current_topic_id: uuid.UUID | None = None
    current_state: MasteryState = MasteryState.NOT_STARTED
    topics_by_state: dict[MasteryState, int] = field(default_factory=dict)
    last_activity: datetime | None = None
    active_rules: list[str] = field(default_factory=list)
