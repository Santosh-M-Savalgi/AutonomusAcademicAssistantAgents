"""CPU-oriented embedder contracts and deterministic retrieval comparison."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from packages.evalkit.contracts import (
    DatasetIdentity,
    EmbedderComparison,
    EmbedderConfig,
    EmbeddingBenchmarkResult,
    RetrievalExample,
)
from packages.evalkit.metrics import latency_stats, mean_recall_at_k

BGE_SMALL_CONFIG = EmbedderConfig()
Clock = Callable[[], float]


class Embedder(Protocol):
    """Small interface that keeps evaluation independent of an embedding library."""

    @property
    def config(self) -> EmbedderConfig: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def _validate_vector(vector: Sequence[float], dimension: int) -> tuple[float, ...]:
    if len(vector) != dimension:
        raise ValueError(f"expected vector dimension {dimension}, got {len(vector)}")
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding vectors must contain finite values")
    return values


class FakeEmbedder:
    """Deterministic embedder with optional exact text-to-vector fixtures.

    Unknown text is mapped from a stable digest.  This is only a test double;
    it never downloads or loads a model.
    """

    def __init__(
        self,
        *,
        config: EmbedderConfig | None = None,
        vectors: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        self._config = config or EmbedderConfig(installed=False)
        self._vectors = {
            text: _validate_vector(vector, self._config.dimension)
            for text, vector in (vectors or {}).items()
        }

    @property
    def config(self) -> EmbedderConfig:
        return self._config

    def _fallback(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [digest[index % len(digest)] / 255.0 for index in range(self._config.dimension)]
        norm = math.sqrt(sum(value * value for value in values))
        return tuple(value / norm for value in values) if norm else tuple(values)

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple(self._vectors.get(text, self._fallback(text)) for text in texts)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding vectors must have equal dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def rank_candidates(
    query_vector: Sequence[float],
    candidates: Sequence[tuple[str, Sequence[float]]],
) -> list[str]:
    """Rank candidates by cosine similarity with deterministic ID tie-breaking."""

    ranked = sorted(
        candidates,
        key=lambda item: (-cosine_similarity(query_vector, item[1]), item[0]),
    )
    return [document_id for document_id, _ in ranked]


def evaluate_embedder(
    embedder: Embedder,
    examples: Sequence[RetrievalExample],
    *,
    clock: Clock | None = None,
) -> EmbeddingBenchmarkResult:
    """Evaluate Recall@1/5 over a local retrieval fixture."""

    now = clock or time.perf_counter
    latencies: list[float] = []
    ranked_results: list[tuple[Sequence[str], Sequence[str]]] = []
    for example in examples:
        started = now()
        texts = [example.input_material] + [candidate.text for candidate in example.candidates]
        vectors = embedder.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError("embedder returned a different number of vectors than inputs")
        ranked = rank_candidates(
            vectors[0],
            [
                (candidate.document_id, vector)
                for candidate, vector in zip(example.candidates, vectors[1:], strict=True)
            ],
        )
        latencies.append(max(0.0, (now() - started) * 1000))
        ranked_results.append((ranked, example.relevant_document_ids))

    identity = examples[0].dataset if examples else DatasetIdentity(dataset_id="empty", version="0")
    return EmbeddingBenchmarkResult(
        config=embedder.config,
        dataset=identity,
        sample_count=len(examples),
        recall_at_1=mean_recall_at_k(ranked_results, 1),
        recall_at_5=mean_recall_at_k(ranked_results, 5),
        latency=latency_stats(latencies),
    )


def compare_embedders(
    baseline: EmbeddingBenchmarkResult,
    challenger: EmbeddingBenchmarkResult | None,
    *,
    improvement_threshold: float = 0.03,
) -> EmbedderComparison:
    if improvement_threshold < 0:
        raise ValueError("improvement threshold cannot be negative")
    improvement = (
        challenger.recall_at_5 - baseline.recall_at_5
        if challenger is not None
        and challenger.recall_at_5 is not None
        and baseline.recall_at_5 is not None
        else None
    )
    return EmbedderComparison(
        baseline=baseline,
        challenger=challenger,
        recall_at_5_improvement=improvement,
        improvement_threshold=improvement_threshold,
        meets_improvement_threshold=improvement is not None
        and improvement >= improvement_threshold,
    )
