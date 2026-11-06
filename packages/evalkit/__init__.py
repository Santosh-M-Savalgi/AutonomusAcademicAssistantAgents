"""Isolated, deterministic benchmark contracts and runners for Phase 4.5."""

from packages.evalkit.contracts import (
    BenchmarkDataset,
    BenchmarkExample,
    BenchmarkPrediction,
    BenchmarkReport,
    BenchmarkRunMetadata,
    DatasetIdentity,
    EmbedderComparison,
    EmbedderConfig,
    EmbeddingBenchmarkResult,
    GradingExample,
    GroundingExample,
    GroundingSource,
    QuestionTagExample,
    RetrievalExample,
    SyllabusExample,
)
from packages.evalkit.embeddings import BGE_SMALL_CONFIG, Embedder, FakeEmbedder
from packages.evalkit.gates import PHASE_4_6_GATE_DEFINITIONS, all_gates_pass, evaluate_gates
from packages.evalkit.runner import BenchmarkRunConfig, BenchmarkRunner, GatewayTaskAdapter

__all__ = [
    "BGE_SMALL_CONFIG",
    "BenchmarkExample",
    "BenchmarkDataset",
    "BenchmarkPrediction",
    "BenchmarkReport",
    "BenchmarkRunConfig",
    "BenchmarkRunMetadata",
    "BenchmarkRunner",
    "DatasetIdentity",
    "Embedder",
    "EmbedderComparison",
    "EmbedderConfig",
    "EmbeddingBenchmarkResult",
    "FakeEmbedder",
    "GatewayTaskAdapter",
    "GroundingExample",
    "GroundingSource",
    "GradingExample",
    "PHASE_4_6_GATE_DEFINITIONS",
    "QuestionTagExample",
    "RetrievalExample",
    "SyllabusExample",
    "all_gates_pass",
    "evaluate_gates",
]
