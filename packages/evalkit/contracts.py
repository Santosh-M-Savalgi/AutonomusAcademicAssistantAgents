"""Versioned, serializable contracts for AAA benchmark datasets and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.model_client.contracts import ModelMetadata, UsageStats


class DatasetIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class BenchmarkExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str = Field(min_length=1)
    dataset: DatasetIdentity
    input_material: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)


class SyllabusExample(BenchmarkExample):
    expected_topics: list[str] = Field(min_length=1)


class QuestionTagExample(BenchmarkExample):
    expected_tags: list[str] = Field(min_length=1)


class GradingExample(BenchmarkExample):
    reference_label: str = Field(min_length=1)


class GroundingSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class GroundingExample(BenchmarkExample):
    reference_source_ids: list[str] = Field(min_length=1)
    source_context: list[GroundingSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_context(self) -> GroundingExample:
        context_ids = [source.source_id for source in self.source_context]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("grounding source_context IDs must be unique")
        missing = set(self.reference_source_ids) - set(context_ids)
        if missing:
            missing_ids = ", ".join(sorted(missing))
            raise ValueError(
                "grounding source_context must include every reference source ID: "
                f"{missing_ids}"
            )
        return self


class RetrievalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RetrievalExample(BenchmarkExample):
    candidates: list[RetrievalCandidate] = Field(min_length=1)
    relevant_document_ids: list[str] = Field(min_length=1)


EvaluationExample = (
    SyllabusExample
    | QuestionTagExample
    | GradingExample
    | GroundingExample
    | RetrievalExample
    | BenchmarkExample
)


class BenchmarkDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: DatasetIdentity
    examples: list[EvaluationExample] = Field(min_length=1)


class BenchmarkRunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_name: str = Field(min_length=1)
    benchmark_key: str | None = None
    scope: Literal["primary", "regression"] | None = None
    dataset: DatasetIdentity
    evaluation_code_version: str = "evalkit-v1"
    provider: str | None = None
    model: ModelMetadata | None = None
    task: str | None = None
    task_version: str | None = None
    prompt_version: str | None = None
    vocabulary_id: str | None = None
    vocabulary_version: str | None = None
    schema_id: str | None = None
    schema_hash: str | None = None
    runtime_id: str | None = None
    artifact_version: str | None = None
    timestamp: datetime
    configuration_fingerprint: str = Field(min_length=1)
    random_seed: int | None = None
    sample_count: int = Field(ge=0)
    successful_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class LatencyStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(ge=0)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    p99_ms: float | None = Field(default=None, ge=0)


class ThroughputStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_count: int = Field(ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    prompts_per_second: float | None = Field(default=None, ge=0)
    prompt_tokens_per_second: float | None = Field(default=None, ge=0)
    generation_tokens_per_second: float | None = Field(default=None, ge=0)


class StructuredOutputStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_count: int = Field(ge=0)
    first_attempt_validity_rate: float | None = Field(default=None, ge=0, le=1)
    retry_recovery_rate: float | None = Field(default=None, ge=0, le=1)
    final_validation_success_rate: float | None = Field(default=None, ge=0, le=1)


class GateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    minimum: float | None
    blocking: bool = True


class GateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    metric_name: str
    value: float | None
    threshold: float | None
    available: bool
    passed: bool
    explanation: str
    dataset: DatasetIdentity
    sample_count: int = Field(ge=0)
    model: ModelMetadata | None = None
    blocking: bool = True
    status: Literal[
        "PASS",
        "FAIL",
        "BLOCKED_PENDING_DECISION",
        "BLOCKED_PENDING_EVALUATION",
        "NOT_APPLICABLE",
    ] | None = None


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: BenchmarkRunMetadata
    metrics: dict[str, float | None] = Field(default_factory=dict)
    latency: LatencyStats
    throughput: ThroughputStats
    structured_output: StructuredOutputStats | None = None
    gates: list[GateEvaluation] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BenchmarkPrediction(BaseModel):
    """Internal prediction envelope; reports omit raw output by default."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    example_id: str
    output: Any = None
    success: bool
    latency_ms: float = Field(ge=0)
    provenance: ModelMetadata | None = None
    usage: UsageStats | None = None
    error_category: str | None = None
    first_attempt_valid: bool | None = None
    recovered_on_retry: bool | None = None


class EmbedderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = "BAAI/bge-small-en-v1.5"
    dimension: int = Field(default=384, ge=1)
    device: Literal["cpu"] = "cpu"
    installed: bool = False


class EmbeddingBenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: EmbedderConfig
    dataset: DatasetIdentity
    sample_count: int = Field(ge=0)
    recall_at_1: float | None = Field(default=None, ge=0, le=1)
    recall_at_5: float | None = Field(default=None, ge=0, le=1)
    latency: LatencyStats


class EmbedderComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: EmbeddingBenchmarkResult
    challenger: EmbeddingBenchmarkResult | None = None
    recall_at_5_improvement: float | None = None
    improvement_threshold: float = 0.03
    meets_improvement_threshold: bool = False


class RuntimePreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASS", "FAIL"]
    provider: str
    endpoint: str
    model_id: str
    artifact_path: str
    artifact_sha256: str
    artifact_verified: bool
    health_ok: bool
    models_endpoint_ok: bool
    returned_model_ids: list[str] = Field(default_factory=list)
    model_identity_consistent: bool
    server_metrics_available: bool = False
    error: str | None = None


class DatasetInventoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_name: str
    dataset: DatasetIdentity
    sample_count: int = Field(ge=0)
    expected_output: str
    metric_names: list[str]


class EmbeddingEvaluationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    dimension: int = Field(ge=1)
    status: Literal["NOT_RUN", "COMPLETED"]
    recall_at_1: float | None = Field(default=None, ge=0, le=1)
    recall_at_5: float | None = Field(default=None, ge=0, le=1)
    latency: LatencyStats | None = None
    reason: str | None = None


class EvaluationSuiteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "aaa.evalkit.phase4.6.v1"
    run_id: str
    suite: str
    status: Literal["COMPLETED", "INFRASTRUCTURE_NO_GO", "PARTIAL_DEBUG_RUN"]
    decision: Literal["GO", "MODEL_NO_GO", "INFRASTRUCTURE_NO_GO", "NOT_APPLICABLE"]
    timestamp: datetime
    model: ModelMetadata | None = None
    runtime: RuntimePreflightReport
    datasets: list[DatasetInventoryEntry]
    benchmarks: list[BenchmarkReport] = Field(default_factory=list)
    embedding: EmbeddingEvaluationStatus
    challenger: EmbeddingEvaluationStatus | None = None
    prompt_version: str
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    dataset_limitation: str
    decision_reason: str | None = None
    server_prompt_tokens_per_second: float | None = Field(default=None, ge=0)
    server_generation_tokens_per_second: float | None = Field(default=None, ge=0)
    errors: list[str] = Field(default_factory=list)
