"""Adaptive Learning Engine — deterministic, explainable adaptive learning.

Sprint 8: Mastery classification, evaluation, root-cause diagnosis,
remediation planning, learning path adaptation, and personalized
recommendations.

All routing and adaptive decisions are **deterministic** — no LLM calls.
LLMs remain responsible only for lesson and quiz generation.

Architecture:
    models.py       — domain dataclasses (AdaptiveDecision, MasteryState, etc.)
    schemas.py      — Pydantic API schemas
    rules.py        — configurable adaptive rules engine
    engine.py       — mastery evaluation engine
    diagnostics.py  — root-cause diagnosis via Knowledge Graph traversal
    planner.py      — learning path planner + remediation planner
    recommendations.py — enhanced recommendation engine with explanations
"""

from __future__ import annotations

from app.adaptive.engine import AdaptiveEngine
from app.adaptive.diagnostics import DiagnosisEngine
from app.adaptive.planner import AdaptivePlanner, RemediationPlanner
from app.adaptive.recommendations import AdaptiveRecommender
from app.adaptive.rules import AdaptiveRuleEngine
from app.adaptive.models import (
    AdaptiveDecision,
    DecisionType,
    DiagnosisReport,
    Explanation,
    LearningPlan,
    MasteryState,
    PlanStep,
    Recommendation,
    RemediationPlan,
)
from app.adaptive.schemas import (
    AdaptiveStatusResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    EvaluateRequest,
    EvaluateResponse,
    LearningPlanResponse,
    PathRequest,
    PathResponse,
    RecommendationResponse,
    RemediateRequest,
    RemediateResponse,
)

__all__ = [
    # Engine
    "AdaptiveEngine",
    "AdaptiveRuleEngine",
    "DiagnosisEngine",
    "AdaptivePlanner",
    "RemediationPlanner",
    "AdaptiveRecommender",
    # Domain models
    "AdaptiveDecision",
    "DecisionType",
    "DiagnosisReport",
    "Explanation",
    "LearningPlan",
    "MasteryState",
    "PlanStep",
    "Recommendation",
    "RemediationPlan",
    # API schemas
    "AdaptiveStatusResponse",
    "DiagnosisRequest",
    "DiagnosisResponse",
    "EvaluateRequest",
    "EvaluateResponse",
    "LearningPlanResponse",
    "PathRequest",
    "PathResponse",
    "RecommendationResponse",
    "RemediateRequest",
    "RemediateResponse",
]
