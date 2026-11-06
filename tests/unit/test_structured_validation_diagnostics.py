"""Opt-in, sanitized diagnostics for structured-output validation."""

from __future__ import annotations

import json

import pytest

from apps.model_gateway.gateway import ModelGateway
from packages.evalkit.contracts import BenchmarkExample, DatasetIdentity
from packages.evalkit.fixtures import question_tag_fixtures
from packages.evalkit.runner import GatewayTaskAdapter
from packages.evalkit.suite import _question_tag_validation_diagnostic_observer
from packages.model_client.contracts import (
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredValidationDiagnostic,
)
from packages.model_client.errors import StructuredOutputValidationError
from packages.model_client.fake import FakeProvider
from packages.model_client.tasks import default_task_registry
from packages.model_client.validation import validate_structured_response


def _response(raw_text: str) -> StructuredGenerationResponse:
    return StructuredGenerationResponse(
        raw_text=raw_text,
        model_id="diagnostic-model",
        provider="diagnostic",
        provenance=ModelMetadata(
            provider="diagnostic",
            model_id="diagnostic-model",
            runtime="diagnostic",
            runtime_version="test",
        ),
    )


@pytest.mark.parametrize(
    ("raw_text", "category", "success"),
    [
        ('{"tags":["fractions","comparison"]}', "success", True),
        ("not json", "json_decoding_failure", False),
        ('{"tags":["fractions","quarters"]}', "enum_violation", False),
        ('{"tags":["fractions","fractions"]}', "duplicate_label", False),
        ('{"tags":["fractions"]}', "cardinality_failure", False),
        (
            '{"tags":["fractions","comparison","number line","fractions"]}',
            "cardinality_failure",
            False,
        ),
    ],
)
def test_validation_diagnostics_classify_sanitized_attempts(
    raw_text: str, category: str, success: bool
) -> None:
    diagnostics: list[StructuredValidationDiagnostic] = []
    spec = default_task_registry().resolve("question_tag")

    if success:
        result = validate_structured_response(
            _response(raw_text),
            spec,
            attempts=1,
            diagnostic_observer=diagnostics.append,
        )
        assert result.validation is not None and result.validation.valid
    else:
        with pytest.raises(StructuredOutputValidationError):
            validate_structured_response(
                _response(raw_text),
                spec,
                attempts=1,
                diagnostic_observer=diagnostics.append,
            )

    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.category == category
    assert diagnostic.success is success
    assert diagnostic.attempt == 1
    assert all(raw_text not in message for message in diagnostic.messages)


def test_duplicate_diagnostic_reports_canonical_frequency_without_raw_output() -> None:
    diagnostics: list[StructuredValidationDiagnostic] = []
    spec = default_task_registry().resolve("question_tag")

    with pytest.raises(StructuredOutputValidationError):
        validate_structured_response(
            _response('{"tags":["fractions","fractions"]}'),
            spec,
            attempts=1,
            diagnostic_observer=diagnostics.append,
        )

    diagnostic = diagnostics[0]
    assert diagnostic.category == "duplicate_label"
    assert diagnostic.sanitized_tags == ["fractions", "fractions"]
    assert diagnostic.tag_count == 2
    assert diagnostic.tag_frequencies == {"fractions": 2}


@pytest.mark.parametrize(
    "raw_text",
    [
        '{"tags":["Fractions","fractions"]}',
        '{"tags":["fractions ","fractions"]}',
        '{"tags":["fraction","fractions"]}',
    ],
)
def test_duplicate_check_does_not_casefold_strip_or_resolve_aliases(raw_text: str) -> None:
    diagnostics: list[StructuredValidationDiagnostic] = []
    spec = default_task_registry().resolve("question_tag")

    with pytest.raises(StructuredOutputValidationError):
        validate_structured_response(
            _response(raw_text),
            spec,
            attempts=1,
            diagnostic_observer=diagnostics.append,
        )

    assert diagnostics[0].category == "enum_violation"


def test_diagnostic_observer_failures_do_not_change_validation() -> None:
    spec = default_task_registry().resolve("question_tag")

    def broken_observer(_diagnostic: StructuredValidationDiagnostic) -> None:
        raise RuntimeError("diagnostic sink failed")

    result = validate_structured_response(
        _response('{"tags":["fractions","comparison"]}'),
        spec,
        attempts=1,
        diagnostic_observer=broken_observer,
    )

    assert result.data.tags == ["fractions", "comparison"]


@pytest.mark.asyncio
async def test_gateway_diagnostics_cover_retry_recovery_without_changing_retry_behavior() -> None:
    provider = FakeProvider(
        structured_raw_responses={
            "question_tag": (
                '{"tags":["fractions","quarters"]}',
                '{"tags":["fractions","comparison"]}',
            )
        }
    )
    gateway = ModelGateway({"fake": provider}, default_provider="fake")
    diagnostics: list[StructuredValidationDiagnostic] = []

    response = await gateway.generate_structured(
        StructuredGenerationRequest(task="question_tag", prompt="diagnostic"),
        validation_observer=diagnostics.append,
    )

    assert len(provider.requests) == 2
    assert response.data.tags == ["fractions", "comparison"]
    assert [(item.attempt, item.category, item.success) for item in diagnostics] == [
        (1, "enum_violation", False),
        (2, "success", True),
    ]


@pytest.mark.asyncio
async def test_gateway_diagnostics_cover_retry_exhaustion_without_changing_error() -> None:
    provider = FakeProvider(
        structured_raw_responses={
            "question_tag": (
                '{"tags":["fractions","fractions"]}',
                '{"tags":["fractions"]}',
            )
        }
    )
    gateway = ModelGateway({"fake": provider}, default_provider="fake")
    diagnostics: list[StructuredValidationDiagnostic] = []

    with pytest.raises(StructuredOutputValidationError) as error:
        await gateway.generate_structured(
            StructuredGenerationRequest(task="question_tag", prompt="diagnostic"),
            validation_observer=diagnostics.append,
        )

    assert len(provider.requests) == 2
    assert error.value.code == "MODEL_VALIDATION_ERROR"
    assert error.value.attempts == 2
    assert [(item.attempt, item.category, item.success) for item in diagnostics] == [
        (1, "duplicate_label", False),
        (2, "cardinality_failure", False),
    ]


@pytest.mark.asyncio
async def test_adapter_diagnostics_are_disabled_by_default_and_opt_in() -> None:
    example = BenchmarkExample(
        example_id="diagnostic-001",
        dataset=DatasetIdentity(dataset_id="diagnostic", version="1"),
        input_material="A diagnostic question",
    )
    provider = FakeProvider(
        structured_raw_responses={
            "question_tag": (
                '{"tags":["fractions","quarters"]}',
                '{"tags":["fractions","comparison"]}',
            )
        }
    )
    gateway = ModelGateway({"fake": provider}, default_provider="fake")
    spec = default_task_registry().resolve("question_tag")

    default_adapter = GatewayTaskAdapter(
        gateway,
        task="question_tag",
        task_version=spec.version,
        task_spec=spec,
        prompt_builder=lambda item: item.input_material,
        structured=True,
        output_parser=lambda value: value.tags,
        provider="fake",
    )
    default_prediction = await default_adapter.predict(example)

    assert default_prediction.success
    assert not hasattr(default_prediction, "validation_diagnostics")

    opt_in_diagnostics: list[StructuredValidationDiagnostic] = []
    opt_in_provider = FakeProvider(
        structured_raw_responses={
            "question_tag": (
                '{"tags":["fractions","quarters"]}',
                '{"tags":["fractions","comparison"]}',
            )
        }
    )
    opt_in_gateway = ModelGateway({"fake": opt_in_provider}, default_provider="fake")
    opt_in_adapter = GatewayTaskAdapter(
        opt_in_gateway,
        task="question_tag",
        task_version=spec.version,
        task_spec=spec,
        prompt_builder=lambda item: item.input_material,
        structured=True,
        output_parser=lambda value: value.tags,
        provider="fake",
        validation_diagnostic_sink=lambda _item, diagnostic: opt_in_diagnostics.append(diagnostic),
    )
    opt_in_prediction = await opt_in_adapter.predict(example)

    assert opt_in_prediction.success
    assert [(item.attempt, item.category) for item in opt_in_diagnostics] == [
        (1, "enum_violation"),
        (2, "success"),
    ]


def test_diagnostic_record_contains_no_raw_output() -> None:
    diagnostic = StructuredValidationDiagnostic(
        attempt=1,
        category="enum_violation",
        locations=["('tags', 1)"],
        messages=["Input does not match the controlled enum"],
        success=False,
    )

    encoded = json.dumps(diagnostic.model_dump(), sort_keys=True)

    assert "student question text" not in encoded
    assert "raw_text" not in encoded
    assert "provider envelope" not in encoded


def test_opt_in_tag_diagnostic_output_contains_only_safe_fields(capsys) -> None:
    observer = _question_tag_validation_diagnostic_observer("run-diagnostic")
    observer(
        question_tag_fixtures()[0],
        StructuredValidationDiagnostic(
            attempt=1,
            category="enum_violation",
            locations=["('tags', 1)"],
            messages=["Input should match the controlled enum"],
            success=False,
            sanitized_tags=["<noncanonical>", "fractions"],
            tag_count=2,
            tag_frequencies={"<noncanonical>": 1, "fractions": 1},
        ),
    )

    output = capsys.readouterr().out.strip()
    assert output.startswith("tag_validation_diagnostic=")
    assert "A lesson compares equivalent fractions" not in output
    assert "raw_text" not in output
    assert '"attempt":1' in output
    assert '"category":"enum_violation"' in output
    assert '"sanitized_tags":["<noncanonical>","fractions"]' in output
    assert '"tag_count":2' in output
    assert '"tag_frequencies":{"<noncanonical>":1,"fractions":1}' in output
    assert '"success":false' in output
