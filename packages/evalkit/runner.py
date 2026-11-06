"""ModelGateway-based benchmark adapters and reproducible run orchestration."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from apps.model_gateway.gateway import ModelGateway
from packages.evalkit.canonical import configuration_fingerprint
from packages.evalkit.contracts import (
    BenchmarkExample,
    BenchmarkPrediction,
    BenchmarkReport,
    BenchmarkRunMetadata,
    DatasetIdentity,
    GateDefinition,
)
from packages.evalkit.gates import evaluate_gates
from packages.evalkit.metrics import latency_stats, structured_output_stats, throughput_stats
from packages.model_client.contracts import (
    GenerationRequest,
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredValidationDiagnostic,
)
from packages.model_client.errors import ModelClientError, StructuredOutputValidationError
from packages.model_client.taskspec import TaskSpec
from packages.model_client.validation import ValidationDiagnosticObserver

Clock = Callable[[], float]
PromptBuilder = Callable[[BenchmarkExample], str]
MetricEvaluator = Callable[
    [Sequence[BenchmarkExample], Mapping[str, BenchmarkPrediction]],
    Mapping[str, float | None],
]
OutputParser = Callable[[Any], Any]
ValidationDiagnosticSink = Callable[[BenchmarkExample, StructuredValidationDiagnostic], None]
PredictionObserver = Callable[[BenchmarkExample, BenchmarkPrediction], None]


class BenchmarkParseError(ValueError):
    """A model response could not be converted to benchmark output."""


class BenchmarkAdapter(Protocol):
    async def predict(self, example: BenchmarkExample) -> BenchmarkPrediction: ...


class BenchmarkRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_name: str = Field(min_length=1)
    benchmark_key: str | None = None
    scope: Literal["primary", "regression"] | None = None
    dataset: DatasetIdentity
    evaluation_config: dict[str, Any] = Field(default_factory=dict)
    evaluation_code_version: str = "evalkit-v1"
    artifact_version: str | None = None
    task: str | None = None
    task_version: str | None = None
    prompt_version: str | None = None
    vocabulary_id: str | None = None
    vocabulary_version: str | None = None
    schema_id: str | None = None
    schema_hash: str | None = None
    runtime_id: str | None = None
    model: ModelMetadata | None = None
    random_seed: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GatewayTaskAdapter:
    """Turn examples into provider-neutral requests through ModelGateway."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        task: str,
        prompt_builder: PromptBuilder,
        structured: bool = False,
        task_version: str | None = None,
        task_spec: TaskSpec | None = None,
        output_parser: OutputParser | None = None,
        provider: str | None = None,
        validation_diagnostic_sink: ValidationDiagnosticSink | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._gateway = gateway
        self._task = task
        self._prompt_builder = prompt_builder
        self._structured = structured
        self._task_version = task_version
        self._task_spec = task_spec
        self._output_parser = output_parser
        self._provider = provider
        self._validation_diagnostic_sink = validation_diagnostic_sink
        self._clock = clock or time.perf_counter

    async def predict(self, example: BenchmarkExample) -> BenchmarkPrediction:
        started = self._clock()
        try:
            prompt = self._prompt_builder(example)
            if not prompt.strip():
                raise ValueError("benchmark prompt builder returned an empty prompt")
            if self._structured:
                structured_request = StructuredGenerationRequest(
                    task=self._task,
                    prompt=prompt,
                    task_version=self._task_version,
                )
                validation_observer: ValidationDiagnosticObserver | None = None
                if self._validation_diagnostic_sink is not None:
                    diagnostic_sink = self._validation_diagnostic_sink

                    def observe_validation(
                        diagnostic: StructuredValidationDiagnostic,
                    ) -> None:
                        diagnostic_sink(example, diagnostic)

                    validation_observer = observe_validation
                structured_response = await self._gateway.generate_structured(
                    structured_request,
                    provider=self._provider,
                    task_spec=self._task_spec,
                    validation_observer=validation_observer,
                )
                validation = structured_response.validation
                parsed_output = structured_response.data
                if self._output_parser is not None:
                    try:
                        parsed_output = self._output_parser(parsed_output)
                    except Exception as exc:
                        raise BenchmarkParseError from exc
                return BenchmarkPrediction(
                    example_id=example.example_id,
                    output=parsed_output,
                    success=validation is not None and validation.valid,
                    latency_ms=max(0.0, (self._clock() - started) * 1000),
                    provenance=structured_response.provenance,
                    usage=structured_response.usage,
                    error_category=None
                    if validation is None or validation.valid
                    else "structured_validation",
                    first_attempt_valid=validation is not None
                    and validation.valid
                    and validation.attempts == 1
                    if validation is not None
                    else None,
                    recovered_on_retry=validation is not None
                    and validation.valid
                    and validation.attempts > 1
                    if validation is not None
                    else None,
                )
            generation_request = GenerationRequest(task=self._task, prompt=prompt)
            generation_response = await self._gateway.generate(
                generation_request, provider=self._provider
            )
            parsed_generation: Any = generation_response.text
            if self._output_parser is not None:
                try:
                    parsed_generation = self._output_parser(parsed_generation)
                except Exception as exc:
                    raise BenchmarkParseError from exc
            return BenchmarkPrediction(
                example_id=example.example_id,
                output=parsed_generation,
                success=True,
                latency_ms=max(0.0, (self._clock() - started) * 1000),
                provenance=generation_response.provenance,
                usage=generation_response.usage,
            )
        except StructuredOutputValidationError as exc:
            return BenchmarkPrediction(
                example_id=example.example_id,
                output=None,
                success=False,
                latency_ms=max(0.0, (self._clock() - started) * 1000),
                error_category=exc.code,
                first_attempt_valid=False,
                recovered_on_retry=False if exc.attempts > 1 else None,
            )
        except ModelClientError as exc:
            return BenchmarkPrediction(
                example_id=example.example_id,
                output=None,
                success=False,
                latency_ms=max(0.0, (self._clock() - started) * 1000),
                error_category=exc.code,
            )
        except BenchmarkParseError:
            return BenchmarkPrediction(
                example_id=example.example_id,
                output=None,
                success=False,
                latency_ms=max(0.0, (self._clock() - started) * 1000),
                error_category="BENCHMARK_PARSE_ERROR",
            )
        except Exception as exc:
            return BenchmarkPrediction(
                example_id=example.example_id,
                output=None,
                success=False,
                latency_ms=max(0.0, (self._clock() - started) * 1000),
                error_category=type(exc).__name__,
            )


class BenchmarkRunner:
    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or time.perf_counter

    async def run(
        self,
        examples: Sequence[BenchmarkExample],
        *,
        config: BenchmarkRunConfig,
        adapter: BenchmarkAdapter,
        evaluator: MetricEvaluator,
        gates: Sequence[GateDefinition] = (),
        prediction_observer: PredictionObserver | None = None,
    ) -> BenchmarkReport:
        if any(example.dataset != config.dataset for example in examples):
            raise ValueError("every benchmark example must belong to the configured dataset")

        predictions: list[BenchmarkPrediction] = []
        for example in examples:
            prediction = await adapter.predict(example)
            predictions.append(prediction)
            if prediction_observer is not None:
                prediction_observer(example, prediction)
        by_id = {prediction.example_id: prediction for prediction in predictions}
        metrics = dict(evaluator(examples, by_id))
        successful = [prediction for prediction in predictions if prediction.success]
        provenance = next(
            (prediction.provenance for prediction in successful if prediction.provenance), None
        )
        durations = [prediction.latency_ms / 1000 for prediction in successful]
        usage = [prediction.usage for prediction in successful]
        known_usage = [item for item in usage if item is not None]
        throughput = throughput_stats(durations).model_copy(
            update={
                "prompt_tokens": sum(item.prompt_tokens for item in known_usage),
                "completion_tokens": sum(item.completion_tokens for item in known_usage),
                "total_tokens": sum(item.total_tokens for item in known_usage),
            }
        )
        validation_values = [prediction.first_attempt_valid for prediction in predictions]
        recovery_values = [prediction.recovered_on_retry for prediction in predictions]
        final_values = [
            prediction.success if prediction.first_attempt_valid is not None else None
            for prediction in predictions
        ]
        has_structured_values = any(
            value is not None for value in validation_values + recovery_values + final_values
        )
        errors = [
            f"{category}:{count}"
            for category, count in sorted(
                Counter(
                    prediction.error_category
                    for prediction in predictions
                    if prediction.error_category is not None
                ).items()
            )
        ]
        model = provenance or config.model
        metadata = BenchmarkRunMetadata(
            benchmark_name=config.benchmark_name,
            benchmark_key=config.benchmark_key,
            scope=config.scope,
            dataset=config.dataset,
            evaluation_code_version=config.evaluation_code_version,
            provider=model.provider if model else None,
            model=model,
            task=config.task,
            task_version=config.task_version,
            prompt_version=config.prompt_version,
            vocabulary_id=config.vocabulary_id,
            vocabulary_version=config.vocabulary_version,
            schema_id=config.schema_id,
            schema_hash=config.schema_hash,
            runtime_id=config.runtime_id,
            artifact_version=config.artifact_version,
            timestamp=config.timestamp,
            configuration_fingerprint=configuration_fingerprint(config.evaluation_config),
            random_seed=config.random_seed,
            sample_count=len(examples),
            successful_count=len(successful),
            failed_count=len(examples) - len(successful),
        )
        return BenchmarkReport(
            metadata=metadata,
            metrics=metrics,
            latency=latency_stats([prediction.latency_ms for prediction in predictions]),
            throughput=throughput,
            structured_output=structured_output_stats(
                validation_values, recovery_values, final_values
            )
            if has_structured_values
            else None,
            gates=evaluate_gates(
                gates,
                metrics,
                dataset=config.dataset,
                sample_count=len(examples),
                model=model,
            ),
            errors=errors,
        )
