"""Focused Phase 4.3 TaskSpec, schema, and structured gateway tests."""

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.model_gateway.gateway import ModelGateway
from packages.model_client.contracts import StructuredGenerationRequest
from packages.model_client.errors import StructuredOutputValidationError
from packages.model_client.fake import FakeProvider
from packages.model_client.schema import (
    StructuredSchemaError,
    generate_json_schema,
    stable_schema_json,
)
from packages.model_client.tasks import default_task_registry
from packages.model_client.taskspec import (
    TaskGenerationDefaults,
    TaskSpec,
    TaskSpecError,
    TaskSpecRegistry,
    ValidationPolicy,
)


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["KNOWN", "UNKNOWN"]
    score: float = Field(ge=0.0, le=1.0)


class OptionalNestedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nested: ClassificationResult | None = None


def spec(
    *,
    name: str = "classification",
    version: str = "classification-v1",
    max_retries: Literal[0, 1] = 1,
) -> TaskSpec:
    return TaskSpec(
        name=name,
        version=version,
        output_mode="structured",
        output_model=ClassificationResult,
        generation=TaskGenerationDefaults(temperature=0.0, max_tokens=64, timeout_seconds=5.0),
        validation=ValidationPolicy(max_retries=max_retries, strict=True),
    )


def structured_request(task: str = "classification") -> StructuredGenerationRequest:
    return StructuredGenerationRequest(task=task, prompt="classify this")


def test_task_registry_registers_looks_up_and_lists_deterministically() -> None:
    registry = TaskSpecRegistry()
    registry.register(spec(name="z_task"))
    registry.register(spec(name="a_task", version="a-v2"))
    registry.register(
        TaskSpec(
            name="lesson_block",
            version="lesson-v1",
            output_mode="text",
            family_prefix="lesson_block_",
        )
    )

    assert registry.get("z_task").version == "classification-v1"
    assert registry.resolve("lesson_block_example").name == "lesson_block"
    assert registry.list_names() == ("a_task", "lesson_block_*", "z_task")
    assert registry.get("a_task").version == "a-v2"


def test_task_registry_rejects_duplicates_and_invalid_definitions() -> None:
    registry = TaskSpecRegistry((spec(),))

    with pytest.raises(TaskSpecError):
        registry.register(spec())
    with pytest.raises(TaskSpecError):
        registry.get("missing")
    with pytest.raises(ValidationError):
        TaskSpec(name="bad*", version="v1", output_mode="text")
    with pytest.raises(ValidationError):
        TaskSpec(name="missing_schema", version="v1", output_mode="structured")
    with pytest.raises(ValidationError):
        TaskSpec(
            name="text_with_schema",
            version="v1",
            output_mode="text",
            output_model=ClassificationResult,
        )


def test_default_registry_contains_initial_tasks_and_explicit_family() -> None:
    registry = default_task_registry()

    assert registry.resolve("syllabus_unit_extract").output_mode == "structured"
    assert registry.resolve("lesson_block_explanation").name == "lesson_block"
    assert "lesson_block_*" in registry.list_names()
    assert registry.resolve("decision_explain").output_mode == "text"


def test_schema_generation_is_stable_and_preserves_constraints_and_enum() -> None:
    first = generate_json_schema(ClassificationResult)
    second = generate_json_schema(ClassificationResult)

    assert first == second
    assert first["required"] == ["label", "score"]
    assert first["properties"]["label"]["enum"] == ["KNOWN", "UNKNOWN"]
    assert first["properties"]["score"]["minimum"] == 0.0
    assert first["properties"]["score"]["maximum"] == 1.0
    assert first["additionalProperties"] is False
    assert stable_schema_json(ClassificationResult) == stable_schema_json(ClassificationResult)


def test_schema_generation_rejects_unsupported_nested_union() -> None:
    with pytest.raises(StructuredSchemaError, match=r"\$defs|anyOf"):
        generate_json_schema(OptionalNestedResult)


def test_task_spec_version_is_explicit_and_retry_limit_is_bounded() -> None:
    task = spec(version="classification-v7", max_retries=0)

    assert task.task_id == "classification"
    assert task.task_version == "classification-v7"
    assert task.structured is True
    assert task.retry_limit == 0

    with pytest.raises(ValidationError):
        ValidationPolicy(max_retries=2)


@pytest.mark.asyncio
async def test_gateway_builds_schema_validates_and_preserves_task_provenance() -> None:
    provider = FakeProvider(
        structured_raw_responses={"classification": ['{"label":"KNOWN","score":0.9}']}
    )
    gateway = ModelGateway(
        {"fake": provider}, default_provider="fake", task_registry=TaskSpecRegistry((spec(),))
    )

    response = await gateway.generate_structured(structured_request())

    assert isinstance(response.data, ClassificationResult)
    assert response.data.label == "KNOWN"
    assert response.validation is not None
    assert response.validation.valid is True
    assert response.validation.attempts == 1
    assert response.validation.task_version == "classification-v1"
    assert response.provenance.task_version == "classification-v1"
    assert provider.requests[0].schema_spec is not None
    assert provider.requests[0].schema_spec["properties"]["label"]["enum"] == [
        "KNOWN",
        "UNKNOWN",
    ]


@pytest.mark.asyncio
async def test_gateway_retries_once_then_returns_typed_result() -> None:
    provider = FakeProvider(
        structured_raw_responses={
            "classification": [
                '{"label":"INVALID","score":0.9}',
                '{"label":"UNKNOWN","score":0.2}',
            ]
        }
    )
    gateway = ModelGateway(
        {"fake": provider}, default_provider="fake", task_registry=TaskSpecRegistry((spec(),))
    )

    response = await gateway.generate_structured(structured_request())

    assert isinstance(response.data, ClassificationResult)
    assert response.data.label == "UNKNOWN"
    assert response.validation is not None
    assert response.validation.attempts == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_gateway_rejects_stale_task_version_before_provider_call() -> None:
    provider = FakeProvider(
        structured_responses={"classification": {"label": "KNOWN", "score": 1.0}}
    )
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        task_registry=TaskSpecRegistry((spec(),)),
    )

    with pytest.raises(TaskSpecError, match="version mismatch"):
        await gateway.generate_structured(
            structured_request().model_copy(update={"task_version": "classification-v0"})
        )
    assert provider.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_text",
    [
        "not json",
        '{"score":0.5}',
        '{"label":"INVALID","score":0.5}',
        '{"label":"KNOWN","score":2.0}',
    ],
)
async def test_gateway_exhausts_validation_attempts_without_coercion(raw_text: str) -> None:
    provider = FakeProvider(
        structured_raw_responses={"classification": [raw_text, raw_text]}
    )
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        task_registry=TaskSpecRegistry((spec(),)),
    )

    with pytest.raises(StructuredOutputValidationError) as error:
        await gateway.generate_structured(structured_request())

    assert error.value.code == "MODEL_VALIDATION_ERROR"
    assert error.value.attempts == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_gateway_respects_zero_retry_policy() -> None:
    provider = FakeProvider(structured_raw_responses={"classification": ["{}", "{}"]})
    gateway = ModelGateway(
        {"fake": provider},
        default_provider="fake",
        task_registry=TaskSpecRegistry((spec(max_retries=0),)),
    )

    with pytest.raises(StructuredOutputValidationError) as error:
        await gateway.generate_structured(structured_request())

    assert error.value.attempts == 1
    assert len(provider.requests) == 1
