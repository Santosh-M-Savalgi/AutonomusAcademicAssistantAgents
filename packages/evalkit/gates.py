"""Closed-fail metric gate evaluation for benchmark reports."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Literal

from packages.evalkit.contracts import (
    DatasetIdentity,
    GateDefinition,
    GateEvaluation,
)
from packages.model_client.contracts import ModelMetadata

GateStatus = Literal[
    "PASS",
    "FAIL",
    "BLOCKED_PENDING_DECISION",
    "BLOCKED_PENDING_EVALUATION",
    "NOT_APPLICABLE",
]

PHASE_4_6_GATE_DEFINITIONS: tuple[GateDefinition, ...] = (
    GateDefinition(name="syllabus_topic_f1", metric_name="topic_f1", minimum=0.80),
    GateDefinition(name="question_tag_precision", metric_name="tag_precision", minimum=0.85),
    GateDefinition(
        name="question_tag_validation_success",
        metric_name="question_tag_validation_success_rate",
        minimum=None,
        blocking=False,
    ),
    GateDefinition(name="rubric_grader_kappa", metric_name="grader_cohen_kappa", minimum=0.60),
    GateDefinition(name="lesson_grounding", metric_name="grounding_pass_rate", minimum=0.85),
    GateDefinition(name="retrieval_recall_at_5", metric_name="retrieval_recall_at_5", minimum=0.85),
)


def evaluate_gates(
    definitions: Iterable[GateDefinition],
    metrics: Mapping[str, float | None],
    *,
    dataset: DatasetIdentity,
    sample_count: int = 0,
    model: ModelMetadata | None = None,
) -> list[GateEvaluation]:
    """Evaluate gates without inferring or imputing missing metric values."""

    evaluations: list[GateEvaluation] = []
    for definition in definitions:
        value = metrics.get(definition.metric_name)
        available = value is not None and math.isfinite(value)
        passed = bool(
            definition.minimum is not None
            and available
            and value is not None
            and value >= definition.minimum
        )
        if definition.minimum is None:
            status: GateStatus = "BLOCKED_PENDING_DECISION"
            explanation = (
                "no threshold is defined in the source specification; owner decision required "
                "(owner approval) on whether this validation metric is informational or "
                "release-blocking"
            )
        elif not available:
            status = "BLOCKED_PENDING_EVALUATION"
            explanation = (
                "metric unavailable; benchmark evaluation evidence is required and the gate "
                "is fail-closed"
            )
        elif passed:
            status = "PASS"
            explanation = f"{value:.6f} meets minimum {definition.minimum:.6f}"
        else:
            status = "FAIL"
            explanation = f"{value:.6f} is below minimum {definition.minimum:.6f}"
        evaluations.append(
            GateEvaluation(
                name=definition.name,
                metric_name=definition.metric_name,
                value=value,
                threshold=definition.minimum,
                available=available,
                passed=passed,
                explanation=explanation,
                dataset=dataset,
                sample_count=sample_count,
                model=model,
                status=status,
                blocking=definition.blocking,
            )
        )
    return evaluations


def all_gates_pass(evaluations: Iterable[GateEvaluation]) -> bool:
    """Return false for an empty gate set and for every unavailable metric."""

    values = list(evaluations)
    return bool(values) and all(
        evaluation.status == "PASS"
        or (
            evaluation.status is None
            and evaluation.threshold is not None
            and evaluation.available
            and evaluation.passed
        )
        for evaluation in values
    )
