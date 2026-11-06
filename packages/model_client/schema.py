"""Deterministic, deliberately small Pydantic-to-provider schema conversion."""

from __future__ import annotations

import json
from itertools import permutations
from typing import Any, cast

from pydantic import BaseModel

from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
)


class StructuredSchemaError(ValueError):
    """The model schema uses constructs outside the Phase 4.3 subset."""


_UNSUPPORTED_KEYS = frozenset(
    {"$defs", "$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else"}
)


def _walk_schema(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        unsupported = sorted(_UNSUPPORTED_KEYS.intersection(value))
        if unsupported:
            joined = ", ".join(unsupported)
            raise StructuredSchemaError(f"unsupported schema construct at {path}: {joined}")
        for key, child in value.items():
            _walk_schema(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_schema(child, f"{path}[{index}]")


def generate_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Generate a stable object schema without weakening Pydantic constraints."""

    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise StructuredSchemaError("structured output requires a Pydantic BaseModel class")
    schema = model.model_json_schema(mode="validation")
    if schema.get("type") != "object":
        raise StructuredSchemaError("structured output schema must have an object root")
    _walk_schema(schema)
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return cast(dict[str, Any], json.loads(canonical))


def generate_question_tag_generation_schema() -> dict[str, Any]:
    """Generate llama.cpp-compatible unique sequences for question-tag-v2."""

    labels = QUESTION_TAG_VOCABULARY.canonical_labels
    sequences = [
        sequence
        for length in (2, 3)
        for sequence in permutations(labels, length)
    ]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "tags": {
                "anyOf": [
                    {
                        "type": "array",
                        "minItems": len(sequence),
                        "maxItems": len(sequence),
                        "prefixItems": [{"const": label} for label in sequence],
                    }
                    for sequence in sequences
                ]
            }
        },
        "required": ["tags"],
        "additionalProperties": False,
    }
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return cast(dict[str, Any], json.loads(canonical))


def generate_subject_neutral_question_tag_generation_schema() -> dict[str, Any]:
    """Generate a compact unique-sequence schema for question-tag-v3."""

    labels = SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.canonical_labels
    alternatives: list[dict[str, Any]] = []
    for first in labels:
        remaining = [label for label in labels if label != first]
        alternatives.append(
            {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [{"const": first}, {"enum": remaining}],
            }
        )
        for second in remaining:
            final_labels = [label for label in remaining if label != second]
            alternatives.append(
                {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "prefixItems": [
                        {"const": first},
                        {"const": second},
                        {"enum": final_labels},
                    ],
                }
            )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"tags": {"anyOf": alternatives}},
        "required": ["tags"],
        "additionalProperties": False,
    }
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return cast(dict[str, Any], json.loads(canonical))


def stable_schema_json(model: type[BaseModel]) -> str:
    """Return canonical JSON useful for request snapshots and schema hashes."""

    return json.dumps(generate_json_schema(model), sort_keys=True, separators=(",", ":"))
