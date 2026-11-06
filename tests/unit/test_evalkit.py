"""Deterministic Phase 4.5 evaluation contracts, metrics, and seams."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.model_gateway.gateway import ModelGateway
from packages.evalkit.canonical import configuration_fingerprint
from packages.evalkit.contracts import (
    BenchmarkExample,
    DatasetIdentity,
    EmbedderConfig,
    GateDefinition,
    GroundingExample,
    GroundingSource,
    QuestionTagExample,
    SyllabusExample,
)
from packages.evalkit.embeddings import FakeEmbedder, compare_embedders, evaluate_embedder
from packages.evalkit.fixtures import grounding_fixtures, retrieval_fixtures
from packages.evalkit.gates import all_gates_pass, evaluate_gates
from packages.evalkit.metrics import (
    cohen_kappa,
    grounding_metrics,
    precision_recall_f1,
    question_tag_detailed_metrics,
    recall_at_k,
    set_confusion_counts,
    syllabus_metrics,
)
from packages.evalkit.runner import BenchmarkRunConfig, BenchmarkRunner, GatewayTaskAdapter
from packages.model_client.fake import FakeProvider


def test_metrics_are_deterministic_and_missing_gates_fail_closed() -> None:
    result = precision_recall_f1(
        ["fractions", "number line", "extra"],
        ["fractions", "number line", "missing"],
    )
    assert result.precision == pytest.approx(2 / 3)
    assert result.recall == pytest.approx(2 / 3)
    assert result.f1 == pytest.approx(2 / 3)
    assert cohen_kappa(["correct", "incorrect"], ["correct", "incorrect"]) == 1.0
    assert recall_at_k(["a", "a", "b"], ["b"], 2) == 1.0

    dataset = DatasetIdentity(dataset_id="synthetic", version="1")
    evaluations = evaluate_gates(
        [GateDefinition(name="quality", metric_name="quality", minimum=0.8)],
        {"quality": None},
        dataset=dataset,
    )
    assert not evaluations[0].available
    assert evaluations[0].status == "BLOCKED_PENDING_EVALUATION"
    assert not all_gates_pass(evaluations)


def test_grounding_contract_exposes_source_context_and_validates_expected_ids() -> None:
    examples = grounding_fixtures()
    assert {source.source_id for source in examples[0].source_context} == {
        "lesson-note-1",
        "lesson-note-2",
    }
    assert set(examples[0].reference_source_ids).issubset(
        {source.source_id for source in examples[0].source_context}
    )
    assert grounding_metrics(
        examples,
        {"grounding-001": ["lesson-note-1"], "grounding-002": ["lesson-note-2"]},
    ) == {"grounding_pass_rate": 1.0}

    dataset = DatasetIdentity(dataset_id="grounding", version="1")
    with pytest.raises(ValueError, match="source_context"):
        GroundingExample(
            example_id="missing-context",
            dataset=dataset,
            input_material="grounding input",
            reference_source_ids=["source-1"],
            source_context=[],
        )
    with pytest.raises(ValueError, match="reference source ID"):
        GroundingExample(
            example_id="missing-id",
            dataset=dataset,
            input_material="grounding input",
            reference_source_ids=["source-1"],
            source_context=[GroundingSource(source_id="source-2", content="other")],
        )


def test_topic_matching_is_casefolded_but_remains_exact_and_set_based() -> None:
    casefolded = precision_recall_f1(
        [" Visual Models ", "Equivalent Fractions"],
        ["visual models", "equivalent fractions"],
    )
    assert casefolded.precision == 1.0
    assert casefolded.recall == 1.0
    assert casefolded.f1 == 1.0

    reordered = precision_recall_f1(
        ["number line", "visual models"],
        ["Visual Models", "Number Line"],
    )
    assert reordered.f1 == 1.0

    duplicates = precision_recall_f1(
        ["visual models", "Visual Models", "number line"],
        ["visual models", "number line"],
    )
    assert duplicates.precision == 1.0
    assert duplicates.recall == 1.0
    assert duplicates.f1 == 1.0

    punctuation = precision_recall_f1(["number line."], ["number line"])
    assert punctuation.precision == 0.0
    assert punctuation.recall == 0.0
    assert punctuation.f1 == 0.0

    different = precision_recall_f1(["fractions"], ["decimals"])
    assert different.precision == 0.0
    assert different.recall == 0.0
    assert different.f1 == 0.0

    empty_prediction = precision_recall_f1([], ["fractions"])
    assert empty_prediction.precision == 0.0
    assert empty_prediction.recall == 0.0
    assert empty_prediction.f1 == 0.0

    empty_both = precision_recall_f1([], [])
    assert empty_both.precision == 1.0
    assert empty_both.recall == 1.0
    assert empty_both.f1 == 1.0


def test_syllabus_topic_matching_normalizes_natural_language_labels() -> None:
    dataset = DatasetIdentity(dataset_id="syllabus", version="1")
    examples = [
        SyllabusExample(
            example_id="one",
            dataset=dataset,
            input_material="lesson",
            expected_topics=["visual models", "equivalent fractions"],
        )
    ]

    normalized = syllabus_metrics(
        examples,
        {"one": [" visual__models ", "Equivalent_Fractions"]},
    )
    assert normalized == {"topic_precision": 1.0, "topic_recall": 1.0, "topic_f1": 1.0}

    reordered_and_deduplicated = syllabus_metrics(
        examples,
        {"one": ["EQUIVALENT FRACTIONS", "visual models", "visual__models"]},
    )
    assert reordered_and_deduplicated == {
        "topic_precision": 1.0,
        "topic_recall": 1.0,
        "topic_f1": 1.0,
    }

    punctuation = syllabus_metrics(examples, {"one": ["number_line."]})
    assert punctuation == {"topic_precision": 0.0, "topic_recall": 0.0, "topic_f1": 0.0}

    different = syllabus_metrics(examples, {"one": ["fractions"]})
    assert different == {"topic_precision": 0.0, "topic_recall": 0.0, "topic_f1": 0.0}


def test_question_tag_detailed_metrics_report_counts_exact_sets_and_breakdowns() -> None:
    dataset = DatasetIdentity(dataset_id="tags", version="1")
    examples = [
        BenchmarkExample(
            example_id="math-1",
            dataset=dataset,
            input_material="math",
            metadata={"subject": "mathematics", "question_type": "comparison"},
        ),
        BenchmarkExample(
            example_id="cs-1",
            dataset=dataset,
            input_material="cs",
            metadata={"subject": "computer science", "question_type": "calculation"},
        ),
    ]
    tagged = [
        QuestionTagExample.model_validate(
            {**example.model_dump(), "expected_tags": expected}
        )
        for example, expected in zip(
            examples, [["fractions", "comparison"], ["algorithms"]], strict=True
        )
    ]
    metrics = question_tag_detailed_metrics(
        tagged,
        {"math-1": ["fractions", "comparison"], "cs-1": ["algorithms", "extra"]},
    )

    assert metrics["tag_true_positive"] == 3.0
    assert metrics["tag_false_positive"] == 1.0
    assert metrics["tag_false_negative"] == 0.0
    assert metrics["tag_exact_set_accuracy"] == 0.5
    assert metrics["tag_subject_mathematics_exact_set_accuracy"] == 1.0
    assert metrics["tag_subject_computer_science_false_positive"] == 1.0
    assert set_confusion_counts([(["a", "b"], ["a"])]) == (1, 1, 0)


def test_canonical_configuration_fingerprint_ignores_mapping_order() -> None:
    assert configuration_fingerprint({"b": 2, "a": 1}) == configuration_fingerprint(
        {"a": 1, "b": 2}
    )


def test_fake_embedder_supports_recall_and_explicit_challenger_comparison() -> None:
    examples = retrieval_fixtures()
    vectors = {
        "fraction lesson": (1.0, 0.0, 0.0, 0.0, 0.0),
        "number line lesson": (0.0, 1.0, 0.0, 0.0, 0.0),
        "decimal lesson": (0.0, 0.0, 1.0, 0.0, 0.0),
        "shapes lesson": (0.0, 0.0, 0.0, 1.0, 0.0),
        "measurement lesson": (0.0, 0.0, 0.0, 0.0, 1.0),
    }
    baseline = evaluate_embedder(
        FakeEmbedder(
            config=EmbedderConfig(model_id="baseline", dimension=5),
            vectors=vectors,
        ),
        examples,
        clock=lambda: 1.0,
    )
    comparison = compare_embedders(baseline, baseline)
    assert baseline.recall_at_1 == 1.0
    assert baseline.recall_at_5 == 1.0
    assert comparison.recall_at_5_improvement == 0.0
    assert not comparison.meets_improvement_threshold


@pytest.mark.asyncio
async def test_runner_calls_model_gateway_and_emits_sanitized_report() -> None:
    dataset = DatasetIdentity(dataset_id="synthetic-run", version="1")
    examples = [
        BenchmarkExample(
            example_id="example-1",
            dataset=dataset,
            input_material="A synthetic prompt",
        )
    ]
    gateway = ModelGateway(
        {"fake": FakeProvider(response_text="synthetic answer")},
        default_provider="fake",
    )
    adapter = GatewayTaskAdapter(
        gateway,
        task="plain",
        prompt_builder=lambda example: example.input_material,
    )
    report = await BenchmarkRunner().run(
        examples,
        config=BenchmarkRunConfig(
            benchmark_name="synthetic-run",
            dataset=dataset,
            evaluation_config={"temperature": 0},
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        adapter=adapter,
        evaluator=lambda items, predictions: {"quality": float(len(predictions)) / len(items)},
    )
    assert report.metadata.successful_count == 1
    assert report.metrics == {"quality": 1.0}
    assert report.metadata.provider == "fake"
    assert "synthetic prompt" not in report.model_dump_json()


@pytest.mark.asyncio
async def test_structured_adapter_reports_first_attempt_validity() -> None:
    dataset = DatasetIdentity(dataset_id="synthetic-structured", version="1")
    example = BenchmarkExample(
        example_id="structured-1",
        dataset=dataset,
        input_material="Extract the topic.",
    )
    gateway = ModelGateway(
        {"fake": FakeProvider(structured_response={"items": ["fractions"]})},
        default_provider="fake",
    )
    report = await BenchmarkRunner().run(
        [example],
        config=BenchmarkRunConfig(benchmark_name="structured", dataset=dataset),
        adapter=GatewayTaskAdapter(
            gateway,
            task="concept_extract",
            prompt_builder=lambda item: item.input_material,
            structured=True,
        ),
        evaluator=lambda items, predictions: {
            "valid": float(predictions[example.example_id].success)
        },
    )
    assert report.structured_output is not None
    assert report.structured_output.first_attempt_validity_rate == 1.0
    assert report.structured_output.final_validation_success_rate == 1.0
