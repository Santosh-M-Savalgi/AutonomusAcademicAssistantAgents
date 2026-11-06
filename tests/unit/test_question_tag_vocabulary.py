"""Controlled-vocabulary contracts for the Phase 4.6 question-tag task."""

from __future__ import annotations

import json
from collections import Counter
from itertools import permutations, product
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.model_gateway.gateway import ModelGateway
from packages.evalkit.contracts import BenchmarkPrediction, DatasetIdentity
from packages.evalkit.fixtures import question_tag_fixtures, question_tag_v3_fixtures
from packages.evalkit.gates import (
    PHASE_4_6_GATE_DEFINITIONS,
    all_gates_pass,
    evaluate_gates,
)
from packages.evalkit.runner import BenchmarkRunConfig, BenchmarkRunner, GatewayTaskAdapter
from packages.evalkit.suite import _gates_for, benchmark_definitions
from packages.model_client.contracts import StructuredGenerationRequest
from packages.model_client.fake import FakeProvider
from packages.model_client.schema import (
    generate_json_schema,
    generate_question_tag_generation_schema,
    generate_subject_neutral_question_tag_generation_schema,
)
from packages.model_client.tasks import (
    GradeResult,
    QuestionTagResult,
    SubjectNeutralQuestionTagResult,
    default_task_registry,
)
from packages.model_client.taskspec import TaskSpecError
from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
)


def test_question_tag_vocabulary_is_partial_and_versioned() -> None:
    assert QUESTION_TAG_VOCABULARY.vocabulary_id == "question-tags"
    assert QUESTION_TAG_VOCABULARY.version == "1.0.0"
    assert QUESTION_TAG_VOCABULARY.exhaustive is False
    assert QUESTION_TAG_VOCABULARY.canonical_labels == (
        "fractions",
        "comparison",
        "number line",
    )
    assert QUESTION_TAG_VOCABULARY.alias_map == {
        "fraction": "fractions",
        "compare": "comparison",
        "comparing": "comparison",
        "number-line": "number line",
        "numberline": "number line",
    }
    assert [entry.role for entry in QUESTION_TAG_VOCABULARY.entries] == [
        "topic",
        "skill",
        "representation",
    ]


def test_question_tag_schema_exposes_only_canonical_labels() -> None:
    schema = generate_json_schema(QuestionTagResult)
    tags_schema = schema["properties"]["tags"]

    assert tags_schema["minItems"] == 2
    assert tags_schema["maxItems"] == 3
    assert tags_schema["items"]["enum"] == ["fractions", "comparison", "number line"]


def test_question_tag_generation_schema_enumerates_all_distinct_sequences() -> None:
    schema = generate_question_tag_generation_schema()
    alternatives = schema["properties"]["tags"]["anyOf"]
    expected = {
        sequence
        for length in (2, 3)
        for sequence in permutations(QUESTION_TAG_VOCABULARY.canonical_labels, length)
    }
    actual = {
        tuple(item["const"] for item in alternative["prefixItems"])
        for alternative in alternatives
    }

    assert actual == expected
    assert len(alternatives) == 12
    assert all(
        alternative["minItems"] == len(alternative["prefixItems"])
        and alternative["maxItems"] == len(alternative["prefixItems"])
        for alternative in alternatives
    )
    assert all(len(sequence) == len(set(sequence)) for sequence in actual)


def test_question_tag_generation_schema_rejects_duplicate_candidates() -> None:
    schema = generate_question_tag_generation_schema()
    alternatives = schema["properties"]["tags"]["anyOf"]

    def matches(candidate: list[str], alternative: dict[str, object]) -> bool:
        prefix_items = alternative["prefixItems"]
        assert isinstance(prefix_items, list)
        return candidate == [item["const"] for item in prefix_items]

    duplicate_candidates = [
        list(candidate)
        for length in (2, 3)
        for candidate in product(QUESTION_TAG_VOCABULARY.canonical_labels, repeat=length)
        if len(candidate) != len(set(candidate))
    ]

    assert not any(
        matches(candidate, alternative)
        for candidate in duplicate_candidates
        for alternative in alternatives
    )


def test_subject_neutral_vocabulary_is_versioned_and_role_complete() -> None:
    vocabulary = SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY

    assert vocabulary.vocabulary_id == "question-tags"
    assert vocabulary.version == "2.0.0"
    assert vocabulary.exhaustive is False
    assert len(vocabulary.canonical_labels) == 14
    assert len(vocabulary.canonical_labels) == len(set(vocabulary.canonical_labels))
    assert [entry.role for entry in vocabulary.entries].count("topic") == 10
    assert [entry.role for entry in vocabulary.entries].count("skill") == 2
    assert [entry.role for entry in vocabulary.entries].count("representation") == 2
    assert set(vocabulary.canonical_labels).isdisjoint(vocabulary.alias_map)


def _subject_neutral_schema_sequences(schema: dict[str, object]) -> list[tuple[str, ...]]:
    properties = schema["properties"]
    assert isinstance(properties, dict)
    tags = properties["tags"]
    assert isinstance(tags, dict)
    alternatives = tags["anyOf"]
    assert isinstance(alternatives, list)
    sequences: list[tuple[str, ...]] = []
    for alternative in alternatives:
        assert isinstance(alternative, dict)
        prefix_items = alternative["prefixItems"]
        assert isinstance(prefix_items, list)
        first = prefix_items[0]
        assert isinstance(first, dict) and "const" in first
        second = prefix_items[1]
        assert isinstance(second, dict)
        if "enum" in second:
            second_values = second["enum"]
            assert isinstance(second_values, list)
            for second_value in second_values:
                sequences.append((first["const"], second_value))
            continue
        assert "const" in second
        third = prefix_items[2]
        assert isinstance(third, dict)
        third_values = third["enum"]
        assert isinstance(third_values, list)
        for third_value in third_values:
            sequences.append((first["const"], second["const"], third_value))
    return sequences


def test_subject_neutral_generation_schema_covers_every_distinct_sequence_once() -> None:
    schema = generate_subject_neutral_question_tag_generation_schema()
    labels = SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.canonical_labels
    expected = {
        sequence
        for length in (2, 3)
        for sequence in permutations(labels, length)
    }
    actual = _subject_neutral_schema_sequences(schema)
    actual_set = set(actual)
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"))

    assert actual_set == expected
    assert len(actual) == 182 + 2184
    assert len(actual) == len(actual_set)
    assert len(schema["properties"]["tags"]["anyOf"]) == 196
    assert len(encoded) == 51312


def test_subject_neutral_schema_uses_only_pinned_runtime_constructs() -> None:
    schema = generate_subject_neutral_question_tag_generation_schema()
    encoded = json.dumps(schema)

    assert "uniqueItems" not in encoded
    assert all(
        set(alternative["prefixItems"][0]) == {"const"}
        for alternative in schema["properties"]["tags"]["anyOf"]
    )


def test_subject_neutral_result_rejects_noncanonical_and_duplicate_labels() -> None:
    valid = SubjectNeutralQuestionTagResult.model_validate(
        {"tags": ["algorithms", "calculation"]}, strict=True
    )
    assert valid.tags == ["algorithms", "calculation"]

    for tags in (
        ["algorithms", "algorithm"],
        ["algorithms", "algorithms"],
        ["algorithms"],
        ["algorithms", "calculation", "diagram", "cells"],
    ):
        with pytest.raises(ValidationError):
            SubjectNeutralQuestionTagResult.model_validate({"tags": tags}, strict=True)


def test_question_tag_generation_constraint_does_not_change_other_task_schemas() -> None:
    schema = generate_json_schema(GradeResult)

    assert schema["properties"]["correct"] == {"title": "Correct", "type": "boolean"}
    assert schema["properties"]["confidence"]["minimum"] == 0.0
    assert "anyOf" not in schema


def test_question_tag_result_accepts_valid_unique_canonical_labels() -> None:
    result = QuestionTagResult.model_validate(
        {"tags": ["fractions", "comparison"]}, strict=True
    )

    assert result.tags == ["fractions", "comparison"]


@pytest.mark.parametrize(
    "tags",
    [
        ["fractions", "fraction"],
        ["fractions", "unknown"],
        ["fractions", "fractions"],
        ["fractions"],
        ["fractions", "comparison", "number line", "unknown"],
    ],
)
def test_question_tag_result_rejects_aliases_unknowns_duplicates_and_bad_counts(
    tags: list[str],
) -> None:
    with pytest.raises(ValidationError):
        QuestionTagResult.model_validate({"tags": tags}, strict=True)


def test_question_tag_task_spec_records_vocabulary_provenance() -> None:
    spec = default_task_registry().resolve("question_tag")

    assert spec.version == "question-tag-v2"
    assert spec.output_model is QuestionTagResult
    assert spec.metadata == {
        "vocabulary_id": "question-tags",
        "vocabulary_version": "1.0.0",
    }


def test_subject_neutral_task_spec_is_separate_from_v2() -> None:
    registry = default_task_registry()
    v2 = registry.resolve("question_tag")
    v3 = registry.resolve("question_tag_v3")

    assert v2.version == "question-tag-v2"
    assert v2.metadata["vocabulary_version"] == "1.0.0"
    assert v3.version == "question-tag-v3"
    assert v3.output_model is SubjectNeutralQuestionTagResult
    assert v3.metadata == {
        "vocabulary_id": "question-tags",
        "vocabulary_version": "2.0.0",
    }


@pytest.mark.asyncio
async def test_question_tag_task_versions_are_exactly_compatible() -> None:
    provider = FakeProvider()
    gateway = ModelGateway({"fake": provider}, default_provider="fake")

    with pytest.raises(TaskSpecError, match="version mismatch"):
        await gateway.generate_structured(
            StructuredGenerationRequest(
                task="question_tag",
                task_version="question-tag-v3",
                prompt="Return tags",
            )
        )
    with pytest.raises(TaskSpecError, match="version mismatch"):
        await gateway.generate_structured(
            StructuredGenerationRequest(
                task="question_tag_v3",
                task_version="question-tag-v2",
                prompt="Return tags",
            )
        )

    assert provider.requests == []


def test_subject_neutral_dataset_has_fixed_identity_and_balanced_annotations() -> None:
    path = Path(__file__).resolve().parents[2] / "data/datasets/question_tags_mixed_subject_v1.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))

    assert dataset["dataset_id"] == "synthetic-question-tags-mixed-subject"
    assert dataset["version"] == "1.0.0"
    assert dataset["task_version"] == "question-tag-v3"
    assert dataset["vocabulary_version"] == "2.0.0"
    assert dataset["provenance"]["reference_labels_status"] == "authored_before_model_inference"
    assert len(dataset["examples"]) == 24
    assert {example["subject"] for example in dataset["examples"]} == {
        "mathematics",
        "computer science",
        "physics",
        "chemistry",
        "biology",
    }
    assert Counter(example["subject"] for example in dataset["examples"]) == Counter(
        {
            "mathematics": 5,
            "computer science": 5,
            "physics": 5,
            "chemistry": 5,
            "biology": 4,
        }
    )
    assert Counter(example["question_type"] for example in dataset["examples"]) == Counter(
        {
            "comparison": 8,
            "calculation_application": 8,
            "representation_interpretation": 8,
        }
    )
    assert all(2 <= len(example["expected_tags"]) <= 3 for example in dataset["examples"])
    assert all(
        set(example["expected_tags"]).issubset(
            set(SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.canonical_labels)
        )
        for example in dataset["examples"]
    )
    assert all(
        len(example["expected_tags"]) == len(set(example["expected_tags"]))
        for example in dataset["examples"]
    )


def test_evalkit_v3_loader_preserves_dataset_identity_and_group_metadata() -> None:
    examples = question_tag_v3_fixtures()

    assert len(examples) == 24
    assert len({example.example_id for example in examples}) == 24
    assert {example.dataset.model_dump_json() for example in examples} == {
        '{"dataset_id":"synthetic-question-tags-mixed-subject","version":"1.0.0"}'
    }
    assert Counter(example.metadata["subject"] for example in examples) == Counter(
        {
            "mathematics": 5,
            "computer science": 5,
            "physics": 5,
            "chemistry": 5,
            "biology": 4,
        }
    )
    assert Counter(example.metadata["question_type"] for example in examples) == Counter(
        {
            "comparison": 8,
            "calculation_application": 8,
            "representation_interpretation": 8,
        }
    )


def test_evalkit_v3_loader_rejects_task_identity_mismatch(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "data/datasets/question_tags_mixed_subject_v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["task_version"] = "question-tag-v2"
    invalid_path = tmp_path / "invalid-v3.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="task_version"):
        question_tag_v3_fixtures(invalid_path)


def test_question_tag_definition_records_vocabulary_and_both_gates() -> None:
    definition = next(item for item in benchmark_definitions() if item.key == "question-tagging")
    gates = _gates_for(definition)
    gate_names = {gate.name for gate in gates}

    assert definition.task_spec.version == "question-tag-v2"
    assert definition.vocabulary_id == "question-tags"
    assert definition.vocabulary_version == "1.0.0"
    assert gate_names == {"question_tag_precision", "question_tag_validation_success"}


def test_validation_success_gate_is_pending_without_invented_threshold() -> None:
    definition = next(
        gate
        for gate in PHASE_4_6_GATE_DEFINITIONS
        if gate.name == "question_tag_validation_success"
    )
    evaluations = evaluate_gates(
        [definition],
        {"question_tag_validation_success_rate": 1.0},
        dataset=DatasetIdentity(dataset_id="synthetic", version="1.0.0"),
    )

    assert evaluations[0].threshold is None
    assert evaluations[0].available
    assert not evaluations[0].passed
    assert definition.blocking is False
    assert evaluations[0].blocking is False
    assert evaluations[0].status == "BLOCKED_PENDING_DECISION"
    assert "owner approval" in evaluations[0].explanation
    assert not all_gates_pass(evaluations)


def test_question_tag_evaluator_emits_validation_success_metric() -> None:
    definition = next(item for item in benchmark_definitions() if item.key == "question-tagging")
    examples = definition.examples()
    predictions = {
        examples[0].example_id: BenchmarkPrediction(
            example_id=examples[0].example_id,
            output=["fractions", "comparison"],
            success=True,
            latency_ms=1.0,
            first_attempt_valid=True,
        ),
        examples[1].example_id: BenchmarkPrediction(
            example_id=examples[1].example_id,
            output=None,
            success=False,
            latency_ms=1.0,
            first_attempt_valid=False,
            error_category="STRUCTURED_OUTPUT_VALIDATION_ERROR",
        ),
    }

    metrics = definition.evaluator(examples, predictions)

    assert metrics["question_tag_validation_success_rate"] == 0.5


@pytest.mark.asyncio
async def test_unknown_first_response_recovers_on_bounded_retry_and_reports_provenance() -> None:
    example = question_tag_fixtures()[0]
    provider = FakeProvider(
        structured_raw_responses={
            "question_tag": (
                '{"tags":["fractions","unknown"]}',
                '{"tags":["fractions","comparison"]}',
            )
        }
    )
    gateway = ModelGateway({"fake": provider}, default_provider="fake")
    spec = default_task_registry().resolve("question_tag")
    adapter = GatewayTaskAdapter(
        gateway,
        task="question_tag",
        task_version=spec.version,
        task_spec=spec,
        prompt_builder=lambda item: item.input_material,
        structured=True,
        output_parser=lambda value: value.tags,
        provider="fake",
    )

    report = await BenchmarkRunner().run(
        [example],
        config=BenchmarkRunConfig(
            benchmark_name="question_tagging",
            dataset=example.dataset,
            task="question_tag",
            task_version=spec.version,
            vocabulary_id=QUESTION_TAG_VOCABULARY.vocabulary_id,
            vocabulary_version=QUESTION_TAG_VOCABULARY.version,
            evaluation_config={
                "vocabulary_id": QUESTION_TAG_VOCABULARY.vocabulary_id,
                "vocabulary_version": QUESTION_TAG_VOCABULARY.version,
            },
        ),
        adapter=adapter,
        evaluator=lambda _examples, _predictions: {"tag_precision": 1.0},
    )

    assert len(provider.requests) == 2
    assert report.metadata.task_version == "question-tag-v2"
    assert report.metadata.vocabulary_id == "question-tags"
    assert report.metadata.vocabulary_version == "1.0.0"
    assert report.metadata.successful_count == 1
    assert report.structured_output is not None
    assert report.structured_output.first_attempt_validity_rate == 0.0
    assert report.structured_output.retry_recovery_rate == 1.0
    assert report.structured_output.final_validation_success_rate == 1.0
