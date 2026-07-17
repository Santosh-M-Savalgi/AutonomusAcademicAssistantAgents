"""Adaptive Learning Engine — Pydantic API schemas.

Request/response schemas for the adaptive API endpoints (Part 9).
All schemas map 1:1 to domain models in ``models.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.adaptive.models import (
    DecisionType,
    MasteryState,
    RecommendationType,
)


# ── Explanation Schema ─────────────────────────────────────────────────────


class ExplanationSchema(BaseModel):
    """Structured explanation for every adaptive decision."""

    decision: str
    reason: str
    evidence: list[str] = Field(default_factory=list)
    metrics_used: dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0
    rules_triggered: list[str] = Field(default_factory=list)
    prerequisites_examined: list[str] = Field(default_factory=list)


# ── Evaluate ───────────────────────────────────────────────────────────────


class EvaluateRequest(BaseModel):
    """Request to evaluate mastery for one or more topics."""

    topic_id: uuid.UUID | None = None
    """Optional: evaluate a specific topic. If None, evaluates current topic."""

    session_id: uuid.UUID | None = None
    """Optional: session context for evaluation."""


class MasteryEvaluationSchema(BaseModel):
    """Schema for mastery evaluation result."""

    topic_id: uuid.UUID
    topic_name: str
    mastery_state: MasteryState
    score: float
    confidence: float
    quiz_scores: list[float] = Field(default_factory=list)
    attempt_count: int = 0
    time_since_last_study_hours: float = 0.0
    historical_trend: float = 0.0
    repeated_failures: int = 0
    trend_direction: str = "stable"
    recent_activity: bool = False
    factors: dict[str, float] = Field(default_factory=dict)


class EvaluateResponse(BaseModel):
    """Response for mastery evaluation."""

    evaluation: MasteryEvaluationSchema
    decision: DecisionType
    explanation: ExplanationSchema | None = None


# ── Diagnosis ──────────────────────────────────────────────────────────────


class DiagnosisRequest(BaseModel):
    """Request root-cause diagnosis for a topic."""

    topic_id: uuid.UUID
    """The topic the learner is failing on."""


class DiagnosisResponse(BaseModel):
    """Response for root-cause diagnosis."""

    topic_id: uuid.UUID
    topic_name: str
    root_concept_id: uuid.UUID | None = None
    root_concept_name: str | None = None
    supporting_concepts: list[uuid.UUID] = Field(default_factory=list)
    missing_prerequisites: list[uuid.UUID] = Field(default_factory=list)
    reasoning_chain: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    explanation: ExplanationSchema | None = None


# ── Plan ───────────────────────────────────────────────────────────────────


class PlanStepSchema(BaseModel):
    """Schema for a single plan step."""

    topic_id: uuid.UUID
    topic_name: str
    action: DecisionType
    priority: int = 0
    estimated_minutes: int = 15
    reason: str = ""


class LearningPlanResponse(BaseModel):
    """Response for learning plan generation."""

    user_id: uuid.UUID
    steps: list[PlanStepSchema] = Field(default_factory=list)
    total_estimated_minutes: int = 0
    completion_path: list[uuid.UUID] = Field(default_factory=list)
    explanation: ExplanationSchema | None = None


# ── Recommendations ────────────────────────────────────────────────────────


class RecommendationSchema(BaseModel):
    """Schema for a single recommendation."""

    type: RecommendationType
    topic_id: uuid.UUID | None = None
    topic_name: str | None = None
    priority: int = 0
    reason: str = ""
    explanation: ExplanationSchema | None = None


class RecommendationResponse(BaseModel):
    """Response for recommendations."""

    user_id: uuid.UUID
    recommendations: list[RecommendationSchema] = Field(default_factory=list)
    explanation: ExplanationSchema | None = None


# ── Remediate ──────────────────────────────────────────────────────────────


class RemediateRequest(BaseModel):
    """Request remediation for a topic the learner is struggling on."""

    topic_id: uuid.UUID


class RemediateResponse(BaseModel):
    """Response for remediation plan."""

    topic_id: uuid.UUID
    topic_name: str
    weak_concepts: list[str] = Field(default_factory=list)
    practice_recommendations: list[str] = Field(default_factory=list)
    suggested_review_sequence: list[uuid.UUID] = Field(default_factory=list)
    estimated_remediation_minutes: int = 0
    required_quizzes: int = 0
    target_mastery: float = 0.75
    explanation: ExplanationSchema | None = None


# ── Status ─────────────────────────────────────────────────────────────────


class AdaptiveStatusResponse(BaseModel):
    """Response for adaptive status overview."""

    user_id: uuid.UUID
    total_topics: int = 0
    mastered_topics: int = 0
    current_topic_id: uuid.UUID | None = None
    current_state: MasteryState = MasteryState.NOT_STARTED
    topics_by_state: dict[str, int] = Field(default_factory=dict)
    last_activity: datetime | None = None
    active_rules: list[str] = Field(default_factory=list)


# ── Path ───────────────────────────────────────────────────────────────────


class PathRequest(BaseModel):
    """Request to retrieve the adaptive learning path."""

    mode: str = "standard"
    """Learning mode: beginner | standard | fast_track."""


class PathStepSchema(BaseModel):
    """Schema for a path step."""

    topic_id: uuid.UUID
    topic_name: str
    topic_slug: str
    difficulty: str
    mastery_state: MasteryState
    score: float = 0.0
    is_blocked: bool = False
    unmet_prerequisites: list[uuid.UUID] = Field(default_factory=list)
    estimated_minutes: int = 15


class PathResponse(BaseModel):
    """Response for adaptive learning path."""

    user_id: uuid.UUID
    steps: list[PathStepSchema] = Field(default_factory=list)
    total_topics: int = 0
    completed_topics: int = 0
    remaining_topics: int = 0
    next_topic_id: uuid.UUID | None = None
    explanation: ExplanationSchema | None = None
