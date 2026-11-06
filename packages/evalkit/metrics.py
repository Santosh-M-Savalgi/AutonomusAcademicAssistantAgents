"""Pure, deterministic benchmark metrics.

These functions intentionally accept plain values and return no model/provider
objects.  Missing denominators are represented by ``None`` so gates can fail
closed instead of turning an empty benchmark into a passing result.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from packages.evalkit.contracts import (
    GradingExample,
    GroundingExample,
    LatencyStats,
    QuestionTagExample,
    RetrievalExample,
    StructuredOutputStats,
    SyllabusExample,
    ThroughputStats,
)


class ClassificationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


def _as_set(values: Iterable[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value.strip()}


def _as_syllabus_topic_set(values: Iterable[str]) -> set[str]:
    normalized_values = {
        " ".join(value.replace("_", " ").casefold().split()) for value in values
    }
    return {value for value in normalized_values if value}


def precision_recall_f1(
    predicted: Iterable[str], expected: Iterable[str]
) -> ClassificationMetrics:
    """Calculate set precision/recall/F1 for one example."""

    predicted_set = _as_set(predicted)
    expected_set = _as_set(expected)
    true_positive = len(predicted_set & expected_set)
    precision = (
        true_positive / len(predicted_set)
        if predicted_set
        else (1.0 if not expected_set else 0.0)
    )
    recall = (
        true_positive / len(expected_set)
        if expected_set
        else (1.0 if not predicted_set else 0.0)
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationMetrics(precision=precision, recall=recall, f1=f1)


def aggregate_precision_recall_f1(
    pairs: Iterable[tuple[Iterable[str], Iterable[str]]],
    *,
    normalizer: Callable[[Iterable[str]], set[str]] = _as_set,
) -> ClassificationMetrics | None:
    """Calculate micro set precision/recall/F1 over a collection of examples."""

    predicted_total = 0
    expected_total = 0
    true_positive_total = 0
    count = 0
    for predicted, expected in pairs:
        predicted_set = normalizer(predicted)
        expected_set = normalizer(expected)
        predicted_total += len(predicted_set)
        expected_total += len(expected_set)
        true_positive_total += len(predicted_set & expected_set)
        count += 1
    if count == 0:
        return None
    precision = true_positive_total / predicted_total if predicted_total else 0.0
    recall = true_positive_total / expected_total if expected_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationMetrics(precision=precision, recall=recall, f1=f1)


def set_confusion_counts(
    pairs: Iterable[tuple[Iterable[str], Iterable[str]]],
    *,
    normalizer: Callable[[Iterable[str]], set[str]] = _as_set,
) -> tuple[int, int, int]:
    """Return micro true-positive, false-positive, and false-negative counts."""

    true_positive = 0
    false_positive = 0
    false_negative = 0
    for predicted, expected in pairs:
        predicted_set = normalizer(predicted)
        expected_set = normalizer(expected)
        true_positive += len(predicted_set & expected_set)
        false_positive += len(predicted_set - expected_set)
        false_negative += len(expected_set - predicted_set)
    return true_positive, false_positive, false_negative


def exact_set_accuracy(
    pairs: Iterable[tuple[Iterable[str], Iterable[str]]],
    *,
    normalizer: Callable[[Iterable[str]], set[str]] = _as_set,
) -> float | None:
    """Return the fraction of examples whose normalized sets match exactly."""

    values = [normalizer(predicted) == normalizer(expected) for predicted, expected in pairs]
    return sum(values) / len(values) if values else None


def detailed_set_metrics(
    pairs: Iterable[tuple[Iterable[str], Iterable[str]]],
    *,
    prefix: str,
    normalizer: Callable[[Iterable[str]], set[str]] = _as_set,
) -> dict[str, float | None]:
    """Return aggregate metrics plus counts and exact-set accuracy."""

    materialized = list(pairs)
    result = aggregate_precision_recall_f1(materialized, normalizer=normalizer)
    true_positive, false_positive, false_negative = set_confusion_counts(
        materialized, normalizer=normalizer
    )
    return {
        f"{prefix}_precision": result.precision if result else None,
        f"{prefix}_recall": result.recall if result else None,
        f"{prefix}_f1": result.f1 if result else None,
        f"{prefix}_exact_set_accuracy": exact_set_accuracy(
            materialized, normalizer=normalizer
        ),
        f"{prefix}_true_positive": float(true_positive),
        f"{prefix}_false_positive": float(false_positive),
        f"{prefix}_false_negative": float(false_negative),
    }


def exact_match_rate(predicted: Sequence[str], expected: Sequence[str]) -> float | None:
    if not predicted and not expected:
        return None
    if len(predicted) != len(expected):
        raise ValueError("predicted and expected sequences must have equal length")
    return sum(
        left == right for left, right in zip(predicted, expected, strict=True)
    ) / len(expected)


def cohen_kappa(predicted: Sequence[str], expected: Sequence[str]) -> float | None:
    """Calculate Cohen's kappa without relying on category ordering."""

    if len(predicted) != len(expected):
        raise ValueError("predicted and expected sequences must have equal length")
    if not expected:
        return None
    categories = set(predicted) | set(expected)
    observed = sum(
        left == right for left, right in zip(predicted, expected, strict=True)
    ) / len(expected)
    expected_agreement = sum(
        (predicted.count(category) / len(predicted))
        * (expected.count(category) / len(expected))
        for category in categories
    )
    if math.isclose(expected_agreement, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected_agreement) / (1.0 - expected_agreement)


def grounding_pass_rate(results: Sequence[bool]) -> float | None:
    if not results:
        return None
    return sum(results) / len(results)


def recall_at_k(
    retrieved_document_ids: Sequence[str],
    relevant_document_ids: Iterable[str],
    k: int,
) -> float | None:
    if k < 1:
        raise ValueError("k must be positive")
    relevant = _as_set(relevant_document_ids)
    if not relevant:
        return None
    unique_retrieved = list(dict.fromkeys(retrieved_document_ids))
    return len(set(unique_retrieved[:k]) & relevant) / len(relevant)


def mean_recall_at_k(
    examples: Iterable[tuple[Sequence[str], Iterable[str]]], k: int
) -> float | None:
    values = [
        value
        for retrieved, relevant in examples
        if (value := recall_at_k(retrieved, relevant, k)) is not None
    ]
    return sum(values) / len(values) if values else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def latency_stats(latencies_ms: Sequence[float]) -> LatencyStats:
    if any(value < 0 for value in latencies_ms):
        raise ValueError("latencies cannot be negative")
    return LatencyStats(
        sample_count=len(latencies_ms),
        p50_ms=_percentile(latencies_ms, 50),
        p95_ms=_percentile(latencies_ms, 95),
        p99_ms=_percentile(latencies_ms, 99),
    )


def throughput_stats(
    durations_seconds: Sequence[float],
    prompt_tokens: Sequence[int] = (),
    completion_tokens: Sequence[int] = (),
) -> ThroughputStats:
    if any(value < 0 for value in durations_seconds):
        raise ValueError("durations cannot be negative")
    if len(prompt_tokens) not in (0, len(durations_seconds)):
        raise ValueError("prompt token count must match duration count")
    if len(completion_tokens) not in (0, len(durations_seconds)):
        raise ValueError("completion token count must match duration count")
    elapsed = sum(durations_seconds)
    prompts = len(durations_seconds)
    prompt_total = sum(prompt_tokens)
    completion_total = sum(completion_tokens)
    return ThroughputStats(
        prompt_count=prompts,
        prompts_per_second=prompts / elapsed if elapsed else None,
        prompt_tokens_per_second=prompt_total / elapsed if prompt_tokens and elapsed else None,
        generation_tokens_per_second=completion_total / elapsed
        if completion_tokens and elapsed
        else None,
    )


def structured_output_stats(
    first_attempt_valid: Sequence[bool | None],
    recovered_on_retry: Sequence[bool | None],
    final_validation_success: Sequence[bool | None],
) -> StructuredOutputStats:
    if not (
        len(first_attempt_valid)
        == len(recovered_on_retry)
        == len(final_validation_success)
    ):
        raise ValueError("structured output sequences must have equal length")

    def rate(values: Sequence[bool | None]) -> float | None:
        known = [value for value in values if value is not None]
        return sum(known) / len(known) if known else None

    return StructuredOutputStats(
        total_count=len(first_attempt_valid),
        first_attempt_validity_rate=rate(first_attempt_valid),
        retry_recovery_rate=rate(recovered_on_retry),
        final_validation_success_rate=rate(final_validation_success),
    )


def syllabus_metrics(
    examples: Sequence[SyllabusExample], predictions: Mapping[str, Iterable[str]]
) -> dict[str, float | None]:
    result = aggregate_precision_recall_f1(
        (
            (predictions.get(example.example_id, ()), example.expected_topics)
            for example in examples
        ),
        normalizer=_as_syllabus_topic_set,
    )
    return {
        "topic_precision": result.precision if result else None,
        "topic_recall": result.recall if result else None,
        "topic_f1": result.f1 if result else None,
    }


def syllabus_detailed_metrics(
    examples: Sequence[SyllabusExample], predictions: Mapping[str, Iterable[str]]
) -> dict[str, float | None]:
    return detailed_set_metrics(
        (
            (predictions.get(example.example_id, ()), example.expected_topics)
            for example in examples
        ),
        prefix="topic",
        normalizer=_as_syllabus_topic_set,
    )


def question_tag_metrics(
    examples: Sequence[QuestionTagExample], predictions: Mapping[str, Iterable[str]]
) -> dict[str, float | None]:
    result = aggregate_precision_recall_f1(
        (predictions.get(example.example_id, ()), example.expected_tags)
        for example in examples
    )
    return {
        "tag_precision": result.precision if result else None,
        "tag_recall": result.recall if result else None,
        "tag_f1": result.f1 if result else None,
    }


def question_tag_detailed_metrics(
    examples: Sequence[QuestionTagExample], predictions: Mapping[str, Iterable[str]]
) -> dict[str, float | None]:
    """Return tag metrics with counts and metadata-group breakdowns."""

    base_pairs = [
        (predictions.get(example.example_id, ()), example.expected_tags) for example in examples
    ]
    metrics = detailed_set_metrics(base_pairs, prefix="tag")
    for group_name in ("subject", "question_type"):
        groups = sorted(
            {
                example.metadata[group_name]
                for example in examples
                if group_name in example.metadata
            }
        )
        for group in groups:
            slug = "_".join(group.casefold().replace("-", " ").split())
            group_pairs = [
                (predictions.get(example.example_id, ()), example.expected_tags)
                for example in examples
                if example.metadata.get(group_name) == group
            ]
            metrics.update(
                detailed_set_metrics(
                    group_pairs,
                    prefix=f"tag_{group_name}_{slug}",
                )
            )
    return metrics


def grading_metrics(
    examples: Sequence[GradingExample], predictions: Mapping[str, str]
) -> dict[str, float | None]:
    expected = [example.reference_label for example in examples]
    actual = [predictions.get(example.example_id, "") for example in examples]
    return {"grader_cohen_kappa": cohen_kappa(actual, expected)}


def grounding_metrics(
    examples: Sequence[GroundingExample], predictions: Mapping[str, Iterable[str]]
) -> dict[str, float | None]:
    for example in examples:
        context_ids = {source.source_id for source in example.source_context}
        if not context_ids:
            raise ValueError("grounding scoring requires visible source context")
        if not set(example.reference_source_ids).issubset(context_ids):
            raise ValueError("grounding scoring requires reference IDs in source context")
    results = [
        bool(
            _as_set(predictions.get(example.example_id, ()))
            & _as_set(example.reference_source_ids)
        )
        for example in examples
    ]
    return {"grounding_pass_rate": grounding_pass_rate(results)}


def retrieval_metrics(
    examples: Sequence[RetrievalExample], predictions: Mapping[str, Sequence[str]]
) -> dict[str, float | None]:
    pairs = (
        (predictions.get(example.example_id, ()), example.relevant_document_ids)
        for example in examples
    )
    return {
        "retrieval_recall_at_1": mean_recall_at_k(pairs, 1),
        "retrieval_recall_at_5": mean_recall_at_k(
            (
                (predictions.get(example.example_id, ()), example.relevant_document_ids)
                for example in examples
            ),
            5,
        ),
    }
