"""Phase 4.6 real-model benchmark suite orchestration."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import httpx

from apps.api.config import Settings
from apps.model_gateway.factory import GatewaySettings, create_model_gateway
from apps.model_gateway.llama_cpp import LlamaCppProvider
from packages.evalkit.contracts import (
    BenchmarkExample,
    BenchmarkPrediction,
    DatasetIdentity,
    DatasetInventoryEntry,
    EmbeddingEvaluationStatus,
    EvaluationSuiteReport,
    QuestionTagExample,
    SyllabusExample,
)
from packages.evalkit.fixtures import (
    grading_fixtures,
    grounding_fixtures,
    question_tag_fixtures,
    question_tag_v3_fixtures,
    syllabus_fixtures,
)
from packages.evalkit.metrics import (
    exact_match_rate,
    grading_metrics,
    grounding_metrics,
    question_tag_detailed_metrics,
    syllabus_detailed_metrics,
)
from packages.evalkit.preflight import PreflightResult, read_server_metrics, run_preflight
from packages.evalkit.prompts import (
    PROMPT_VERSION,
    SUBJECT_NEUTRAL_PROMPT_VERSION,
    grading_prompt,
    grounding_prompt,
    question_tag_prompt,
    subject_neutral_question_tag_prompt,
    syllabus_prompt,
)
from packages.evalkit.reporting import write_reports
from packages.evalkit.runner import (
    BenchmarkRunConfig,
    BenchmarkRunner,
    GatewayTaskAdapter,
    PredictionObserver,
    ValidationDiagnosticSink,
)
from packages.evalkit.tasks import GROUNDING_TASK_SPEC, GroundingResult
from packages.model_client.contracts import ModelMetadata, StructuredValidationDiagnostic
from packages.model_client.runtime import load_model_lock
from packages.model_client.schema import (
    generate_json_schema,
    generate_question_tag_generation_schema,
    generate_subject_neutral_question_tag_generation_schema,
)
from packages.model_client.tasks import (
    GradeResult,
    QuestionTagResult,
    StringListResult,
    SubjectNeutralQuestionTagResult,
    default_task_registry,
)
from packages.model_client.taskspec import TaskSpec
from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
)

BenchmarkEvaluator = Callable[
    [Sequence[BenchmarkExample], Mapping[str, BenchmarkPrediction]],
    Mapping[str, float | None],
]
OutputParser = Callable[[Any], Any]
SuiteStatus = Literal["COMPLETED", "INFRASTRUCTURE_NO_GO", "PARTIAL_DEBUG_RUN"]
SuiteDecision = Literal["GO", "MODEL_NO_GO", "INFRASTRUCTURE_NO_GO", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class BenchmarkDefinition:
    key: str
    benchmark_name: str
    examples: Callable[[], list[BenchmarkExample]]
    expected_output: str
    metric_names: tuple[str, ...]
    task: str
    task_spec: TaskSpec
    prompt_builder: Callable[[BenchmarkExample], str]
    output_parser: OutputParser
    evaluator: BenchmarkEvaluator
    gate_name: str
    additional_gate_names: tuple[str, ...] = ()
    vocabulary_id: str | None = None
    vocabulary_version: str | None = None
    prompt_version: str = PROMPT_VERSION
    schema_id: str = "unspecified"
    scope: Literal["primary", "regression"] = "primary"


def benchmark_definitions() -> tuple[BenchmarkDefinition, ...]:
    registry = default_task_registry()
    return (
        BenchmarkDefinition(
            key="syllabus",
            benchmark_name="syllabus_topic_extraction",
            examples=lambda: list(syllabus_fixtures()),
            expected_output="topic string list",
            metric_names=("topic_precision", "topic_recall", "topic_f1"),
            task="syllabus_unit_extract",
            task_spec=registry.resolve("syllabus_unit_extract"),
            prompt_builder=syllabus_prompt,
            output_parser=_parse_items,
            evaluator=_syllabus_evaluator,
            gate_name="syllabus_topic_f1",
            schema_id="string-list-v1",
        ),
        BenchmarkDefinition(
            key="question-tagging",
            benchmark_name="question_tagging",
            examples=lambda: list(question_tag_fixtures()),
            expected_output="tag string list",
            metric_names=(
                "tag_precision",
                "tag_recall",
                "tag_f1",
                "tag_exact_set_accuracy",
                "tag_true_positive",
                "tag_false_positive",
                "tag_false_negative",
                "question_tag_validation_success_rate",
            ),
            task="question_tag",
            task_spec=registry.resolve("question_tag"),
            prompt_builder=question_tag_prompt,
            output_parser=_parse_tags,
            evaluator=_question_tag_evaluator,
            gate_name="question_tag_precision",
            additional_gate_names=("question_tag_validation_success",),
            vocabulary_id=QUESTION_TAG_VOCABULARY.vocabulary_id,
            vocabulary_version=QUESTION_TAG_VOCABULARY.version,
            schema_id="question-tag-v2-generation-v1",
            scope="regression",
        ),
        BenchmarkDefinition(
            key="question-tagging-v3",
            benchmark_name="question_tagging_v3",
            examples=lambda: list(question_tag_v3_fixtures()),
            expected_output="canonical subject-neutral tag string list",
            metric_names=(
                "tag_precision",
                "tag_recall",
                "tag_f1",
                "tag_exact_set_accuracy",
                "tag_true_positive",
                "tag_false_positive",
                "tag_false_negative",
                "question_tag_validation_success_rate",
            ),
            task="question_tag_v3",
            task_spec=registry.resolve("question_tag_v3"),
            prompt_builder=subject_neutral_question_tag_prompt,
            output_parser=_parse_v3_tags,
            evaluator=_question_tag_evaluator,
            gate_name="question_tag_precision",
            additional_gate_names=("question_tag_validation_success",),
            vocabulary_id=SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.vocabulary_id,
            vocabulary_version=SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.version,
            prompt_version=SUBJECT_NEUTRAL_PROMPT_VERSION,
            schema_id="question-tag-v3-generation-v1",
            scope="primary",
        ),
        BenchmarkDefinition(
            key="grading",
            benchmark_name="rubric_grading",
            examples=lambda: list(grading_fixtures()),
            expected_output="grading label and confidence",
            metric_names=("grader_cohen_kappa", "grader_agreement", "grader_mean_confidence"),
            task="answer_grade_rubric",
            task_spec=registry.resolve("answer_grade_rubric"),
            prompt_builder=grading_prompt,
            output_parser=_parse_grade,
            evaluator=_grading_evaluator,
            gate_name="rubric_grader_kappa",
            schema_id="grade-result-v1",
        ),
        BenchmarkDefinition(
            key="grounding",
            benchmark_name="lesson_grounding",
            examples=lambda: list(grounding_fixtures()),
            expected_output="grounding source ID list",
            metric_names=("grounding_pass_rate",),
            task=GROUNDING_TASK_SPEC.name,
            task_spec=GROUNDING_TASK_SPEC,
            prompt_builder=grounding_prompt,
            output_parser=_parse_source_ids,
            evaluator=_grounding_evaluator,
            gate_name="lesson_grounding",
            schema_id="grounding-result-v1",
        ),
    )


def dataset_inventory(
    definitions: Sequence[BenchmarkDefinition] | None = None,
) -> list[DatasetInventoryEntry]:
    selected = definitions if definitions is not None else benchmark_definitions()
    return [
        DatasetInventoryEntry(
            benchmark_name=definition.benchmark_name,
            dataset=_dataset_for(definition),
            sample_count=len(definition.examples()),
            expected_output=definition.expected_output,
            metric_names=list(definition.metric_names),
        )
        for definition in selected
    ]


async def run_phase46(
    settings: Settings,
    *,
    benchmark_key: str | None = None,
    output_dir: Path = Path("docs"),
    diagnostic_topics: bool = False,
    diagnostic_tags: bool = False,
) -> tuple[EvaluationSuiteReport, tuple[Path, Path]]:
    if diagnostic_tags and benchmark_key not in {"question-tagging", "question-tagging-v3"}:
        raise ValueError(
            "--diagnostic-tags requires benchmark_key='question-tagging' or "
            "'question-tagging-v3'"
        )
    definitions = list(benchmark_definitions())
    selected = [
        definition
        for definition in definitions
        if benchmark_key is None or definition.key == benchmark_key
    ]
    if not selected:
        raise ValueError(f"unknown benchmark: {benchmark_key}")

    timestamp = datetime.now(UTC)
    run_id = uuid.uuid4().hex
    preflight = await run_preflight(settings)
    if preflight.report.status != "PASS":
        report = _suite_report(
            run_id=run_id,
            timestamp=timestamp,
            settings=settings,
            preflight=preflight,
            benchmarks=[],
            selected=selected,
            model=None,
            status="INFRASTRUCTURE_NO_GO",
            decision="INFRASTRUCTURE_NO_GO",
            errors=[preflight.report.error or "runtime preflight failed"],
        )
        return report, write_reports(report, output_dir)

    lock = load_model_lock(Path(settings.model_lock_path))
    provider = LlamaCppProvider(
        base_url=settings.model_base_url,
        model_id=settings.model_id,
        artifact_filename=Path(settings.model_artifact_path).name,
        artifact_sha256=lock.sha256,
        timeout_seconds=settings.model_gateway_timeout_seconds,
    )
    gateway = create_model_gateway(cast(GatewaySettings, settings), llama_provider=provider)
    started = time.perf_counter()
    benchmark_reports = []
    errors: list[str] = []
    try:
        for definition in selected:
            examples = definition.examples()
            adapter = GatewayTaskAdapter(
                gateway,
                task=definition.task,
                task_version=definition.task_spec.version,
                task_spec=definition.task_spec,
                prompt_builder=definition.prompt_builder,
                output_parser=definition.output_parser,
                structured=True,
                provider=provider.name,
                validation_diagnostic_sink=(
                    _question_tag_validation_diagnostic_observer(run_id)
                    if diagnostic_tags
                    and definition.key in {"question-tagging", "question-tagging-v3"}
                    else None
                ),
            )
            dataset = _dataset_for(definition)
            schema_hash = _schema_hash(definition)
            runtime_id = _runtime_identifier(provider.metadata)
            config = BenchmarkRunConfig(
                benchmark_name=definition.benchmark_name,
                benchmark_key=definition.key,
                scope=definition.scope,
                dataset=dataset,
                task=definition.task,
                task_version=definition.task_spec.version,
                prompt_version=definition.prompt_version,
                vocabulary_id=definition.vocabulary_id,
                vocabulary_version=definition.vocabulary_version,
                schema_id=definition.schema_id,
                schema_hash=schema_hash,
                runtime_id=runtime_id,
                model=provider.metadata,
                artifact_version=lock.sha256,
                timestamp=timestamp,
                evaluation_config={
                    "benchmark": definition.benchmark_name,
                    "benchmark_key": definition.key,
                    "scope": definition.scope,
                    "dataset_id": dataset.dataset_id,
                    "dataset_version": dataset.version,
                    "model_id": settings.model_id,
                    "provider": provider.name,
                    "prompt_version": definition.prompt_version,
                    "task": definition.task,
                    "task_version": definition.task_spec.version,
                    "vocabulary_id": definition.vocabulary_id,
                    "vocabulary_version": definition.vocabulary_version,
                    "schema_id": definition.schema_id,
                    "schema_hash": schema_hash,
                    "runtime_id": runtime_id,
                },
            )
            try:
                benchmark_reports.append(
                    await BenchmarkRunner().run(
                        examples,
                        config=config,
                        adapter=adapter,
                        evaluator=definition.evaluator,
                        gates=_gates_for(definition),
                        prediction_observer=(
                            _syllabus_topic_diagnostic_observer(run_id)
                            if diagnostic_topics and definition.key == "syllabus"
                            else (
                                _question_tag_diagnostic_observer(
                                    run_id, benchmark_name=definition.benchmark_name
                                )
                                if diagnostic_tags
                                and definition.key
                                in {"question-tagging", "question-tagging-v3"}
                                else None
                            )
                        ),
                    )
                )
            except Exception as exc:
                errors.append(f"{definition.key}: {type(exc).__name__}")
    finally:
        await provider.aclose()

    server_rates = await _server_rates(settings, preflight, started)
    complete = benchmark_key is None and len(benchmark_reports) == len(definitions)
    decision = _decision(benchmark_reports, complete)
    report = _suite_report(
        run_id=run_id,
        timestamp=timestamp,
        settings=settings,
        preflight=preflight,
        benchmarks=benchmark_reports,
        selected=selected,
        model=provider.metadata,
        status="COMPLETED" if complete else "PARTIAL_DEBUG_RUN",
        decision=decision,
        errors=errors,
        server_rates=server_rates,
    )
    return report, write_reports(report, output_dir)


def _dataset_for(definition: BenchmarkDefinition) -> DatasetIdentity:
    return definition.examples()[0].dataset


def _generation_schema(definition: BenchmarkDefinition) -> dict[str, Any]:
    if definition.key == "question-tagging":
        return generate_question_tag_generation_schema()
    if definition.key == "question-tagging-v3":
        return generate_subject_neutral_question_tag_generation_schema()
    output_model = definition.task_spec.output_model
    if output_model is None:
        return {}
    return generate_json_schema(output_model)


def _schema_hash(definition: BenchmarkDefinition) -> str:
    schema = json.dumps(_generation_schema(definition), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(schema.encode("utf-8")).hexdigest()


def _runtime_identifier(model: ModelMetadata) -> str:
    commit = f"+{model.runtime_commit}" if model.runtime_commit else ""
    return f"{model.runtime}:{model.runtime_version}{commit}"


def _gates_for(definition: BenchmarkDefinition) -> list[Any]:
    from packages.evalkit.gates import PHASE_4_6_GATE_DEFINITIONS

    names = (definition.gate_name, *definition.additional_gate_names)
    return [gate for gate in PHASE_4_6_GATE_DEFINITIONS if gate.name in names]


def _parse_items(value: Any) -> list[str]:
    if not isinstance(value, StringListResult):
        raise ValueError("structured syllabus output is not StringListResult")
    return value.items


def _syllabus_topic_diagnostic_observer(run_id: str) -> PredictionObserver:
    def observe(example: BenchmarkExample, prediction: BenchmarkPrediction) -> None:
        if not isinstance(example, SyllabusExample):
            return
        predicted_topics = (
            list(prediction.output)
            if prediction.success and isinstance(prediction.output, list)
            else None
        )
        print(
            "topic_diagnostic="
            + json.dumps(
                {
                    "benchmark": "syllabus_topic_extraction",
                    "example_id": example.example_id,
                    "expected_topics": list(example.expected_topics),
                    "predicted_topics": predicted_topics,
                    "run_id": run_id,
                    "success": prediction.success,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

    return observe


def _question_tag_diagnostic_observer(
    run_id: str, *, benchmark_name: str = "question_tagging"
) -> PredictionObserver:
    def observe(example: BenchmarkExample, prediction: BenchmarkPrediction) -> None:
        if not isinstance(example, QuestionTagExample):
            return
        predicted_tags = (
            list(prediction.output)
            if prediction.success and isinstance(prediction.output, list)
            else None
        )
        print(
            "tag_diagnostic="
            + json.dumps(
                {
                    "benchmark": benchmark_name,
                    "error_code": prediction.error_category
                    if not prediction.success
                    else None,
                    "example_id": example.example_id,
                    "expected_tags": list(example.expected_tags),
                    "predicted_tags": predicted_tags,
                    "run_id": run_id,
                    "success": prediction.success,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

    return observe


def _question_tag_validation_diagnostic_observer(
    run_id: str,
) -> ValidationDiagnosticSink:
    def observe(example: BenchmarkExample, diagnostic: StructuredValidationDiagnostic) -> None:
        if not isinstance(example, QuestionTagExample):
            return
        record: dict[str, object] = {
            "attempt": diagnostic.attempt,
            "category": diagnostic.category,
            "example_id": example.example_id,
            "locations": list(diagnostic.locations),
            "messages": list(diagnostic.messages),
            "run_id": run_id,
            "success": diagnostic.success,
        }
        if diagnostic.sanitized_tags is not None:
            record.update(
                {
                    "sanitized_tags": list(diagnostic.sanitized_tags),
                    "tag_count": diagnostic.tag_count,
                    "tag_frequencies": dict(diagnostic.tag_frequencies or {}),
                }
            )
        print(
            "tag_validation_diagnostic="
            + json.dumps(record, sort_keys=True, separators=(",", ":")),
            flush=True,
        )

    return observe


def _parse_tags(value: Any) -> list[str]:
    if not isinstance(value, QuestionTagResult):
        raise ValueError("structured tagging output is not QuestionTagResult")
    return [str(tag) for tag in value.tags]


def _parse_v3_tags(value: Any) -> list[str]:
    if not isinstance(value, SubjectNeutralQuestionTagResult):
        raise ValueError("structured v3 tagging output is not SubjectNeutralQuestionTagResult")
    return [str(tag) for tag in value.tags]


def _parse_grade(value: Any) -> GradeResult:
    if not isinstance(value, GradeResult):
        raise ValueError("structured grading output is not GradeResult")
    return value


def _parse_source_ids(value: Any) -> list[str]:
    if not isinstance(value, GroundingResult):
        raise ValueError("structured grounding output is not GroundingResult")
    return value.source_ids


def _syllabus_evaluator(
    examples: Sequence[BenchmarkExample], predictions: Mapping[str, BenchmarkPrediction]
) -> Mapping[str, float | None]:
    values = {
        key: prediction.output
        for key, prediction in predictions.items()
        if prediction.success and isinstance(prediction.output, list)
    }
    return syllabus_detailed_metrics(examples, values)  # type: ignore[arg-type]


def _question_tag_evaluator(
    examples: Sequence[BenchmarkExample], predictions: Mapping[str, BenchmarkPrediction]
) -> Mapping[str, float | None]:
    values = {
        key: prediction.output
        for key, prediction in predictions.items()
        if prediction.success and isinstance(prediction.output, list)
    }
    metrics = dict(question_tag_detailed_metrics(examples, values))  # type: ignore[arg-type]
    validation_values = [
        prediction.success
        for prediction in predictions.values()
        if prediction.first_attempt_valid is not None
    ]
    metrics["question_tag_validation_success_rate"] = (
        sum(validation_values) / len(validation_values) if validation_values else None
    )
    return metrics


def _grading_evaluator(
    examples: Sequence[BenchmarkExample], predictions: Mapping[str, BenchmarkPrediction]
) -> Mapping[str, float | None]:
    labels: dict[str, str] = {}
    confidences: list[float] = []
    for key, prediction in predictions.items():
        if prediction.success and isinstance(prediction.output, GradeResult):
            labels[key] = "correct" if prediction.output.correct else "incorrect"
            confidences.append(prediction.output.confidence)
    metrics = dict(grading_metrics(examples, labels))  # type: ignore[arg-type]
    expected = [
        example.reference_label for example in examples if hasattr(example, "reference_label")
    ]
    actual = [
        labels.get(example.example_id, "")
        for example in examples
        if hasattr(example, "reference_label")
    ]
    metrics["grader_agreement"] = exact_match_rate(actual, expected)
    metrics["grader_mean_confidence"] = (
        sum(confidences) / len(confidences) if confidences else None
    )
    return metrics


def _grounding_evaluator(
    examples: Sequence[BenchmarkExample], predictions: Mapping[str, BenchmarkPrediction]
) -> Mapping[str, float | None]:
    values = {
        key: prediction.output
        for key, prediction in predictions.items()
        if prediction.success and isinstance(prediction.output, list)
    }
    return grounding_metrics(examples, values)  # type: ignore[arg-type]


def _decision(benchmarks: Sequence[Any], complete: bool) -> SuiteDecision:
    if not complete:
        return "NOT_APPLICABLE"
    gates = [gate for report in benchmarks for gate in report.gates]
    blocking_gates = [gate for gate in gates if gate.blocking]
    if any(
        gate.status in {"BLOCKED_PENDING_DECISION", "BLOCKED_PENDING_EVALUATION"}
        for gate in blocking_gates
    ):
        return "NOT_APPLICABLE"
    return (
        "GO"
        if blocking_gates and all(gate.status == "PASS" for gate in blocking_gates)
        else "MODEL_NO_GO"
    )


def _decision_reason(benchmarks: Sequence[Any], complete: bool, decision: SuiteDecision) -> str:
    if not complete:
        return "not all selected benchmarks were run; this is a partial/debug result"
    gates = [gate for report in benchmarks for gate in report.gates]
    blocking_gates = [gate for gate in gates if gate.blocking]
    if any(gate.status == "BLOCKED_PENDING_DECISION" for gate in blocking_gates):
        return (
            "question_tag_validation_success has no threshold in the source specification; "
            "the owner must decide whether it is informational or release-blocking"
        )
    if any(gate.status == "BLOCKED_PENDING_EVALUATION" for gate in blocking_gates):
        return (
            "one or more required metrics are unavailable and need an authorized "
            "benchmark evaluation"
        )
    if any(
        gate.status == "BLOCKED_PENDING_DECISION"
        for gate in gates
        if not gate.blocking
    ):
        return (
            "all blocking gates evaluated; informational validation metric remains pending "
            "owner decision"
        )
    if decision == "GO":
        return "all evaluated gates passed"
    if decision == "MODEL_NO_GO":
        return "one or more evaluated gates failed"
    return "runtime preflight did not produce an applicable benchmark decision"


def _suite_report(
    *,
    run_id: str,
    timestamp: datetime,
    settings: Settings,
    preflight: PreflightResult,
    benchmarks: list[Any],
    selected: Sequence[BenchmarkDefinition],
    model: ModelMetadata | None,
    status: SuiteStatus,
    decision: SuiteDecision,
    errors: list[str],
    server_rates: tuple[float | None, float | None] = (None, None),
) -> EvaluationSuiteReport:
    return EvaluationSuiteReport(
        run_id=run_id,
        suite="phase4.6",
        status=status,
        decision=decision,
        timestamp=timestamp,
        model=model,
        runtime=preflight.report,
        datasets=dataset_inventory(selected),
        benchmarks=benchmarks,
        embedding=EmbeddingEvaluationStatus(
            model_id="BAAI/bge-small-en-v1.5",
            dimension=384,
            status="NOT_RUN",
            reason="No real BGE loader is present in the Phase 4.5 scaffold",
        ),
        prompt_version=(
            next(iter({definition.prompt_version for definition in selected}), PROMPT_VERSION)
            if len({definition.prompt_version for definition in selected}) == 1
            else "mixed"
        ),
        prompt_versions={definition.key: definition.prompt_version for definition in selected},
        dataset_limitation=(
            "These are tiny synthetic evaluation fixtures and are not statistically "
            "strong production validation. Larger curated evaluation sets are required "
            "for meaningful confidence."
        ),
        server_prompt_tokens_per_second=server_rates[0],
        server_generation_tokens_per_second=server_rates[1],
        decision_reason=_decision_reason(benchmarks, status == "COMPLETED", decision),
        errors=errors,
    )


async def _server_rates(
    settings: Settings, preflight: PreflightResult, started: float
) -> tuple[float | None, float | None]:
    if preflight.metrics is None:
        return (None, None)
    async with httpx.AsyncClient(
        base_url=settings.model_base_url,
        timeout=settings.model_gateway_timeout_seconds,
    ) as client:
        finished = await read_server_metrics(client)
    if finished is None:
        return (None, None)
    elapsed = max(0.0, time.perf_counter() - started)
    if not elapsed:
        return (None, None)
    prompt_rate = _counter_rate(
        preflight.metrics.prompt_tokens_total,
        finished.prompt_tokens_total,
        elapsed,
    )
    generation_rate = _counter_rate(
        preflight.metrics.predicted_tokens_total,
        finished.predicted_tokens_total,
        elapsed,
    )
    return prompt_rate, generation_rate


def _counter_rate(start: float | None, end: float | None, elapsed: float) -> float | None:
    if start is None or end is None or end < start:
        return None
    return (end - start) / elapsed
