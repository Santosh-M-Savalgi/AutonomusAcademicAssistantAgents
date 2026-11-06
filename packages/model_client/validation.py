"""Deterministic validation of untrusted structured provider output."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from packages.model_client.contracts import (
    StructuredGenerationResponse,
    StructuredValidationCategory,
    StructuredValidationDiagnostic,
    StructuredValidationInfo,
)
from packages.model_client.errors import StructuredOutputValidationError
from packages.model_client.taskspec import TaskSpec
from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
    QuestionTagVocabulary,
)

ValidationDiagnosticObserver = Callable[[StructuredValidationDiagnostic], None]


def _errors(exc: ValidationError | json.JSONDecodeError) -> list[str]:
    if isinstance(exc, json.JSONDecodeError):
        return [f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"]
    return [f"{error['loc']}: {error['msg']}" for error in exc.errors()]


def _validation_category(exc: ValidationError) -> StructuredValidationCategory:
    errors = exc.errors()
    messages = [str(error["msg"]).lower() for error in errors]
    types = {str(error["type"]) for error in errors}
    if any("must be unique" in message for message in messages):
        return "duplicate_label"
    if types.intersection({"too_short", "too_long"}):
        return "cardinality_failure"
    if "literal_error" in types:
        return "enum_violation"
    return "pydantic_validation_failure"


def _safe_question_tag_summary(
    candidate: Any,
    spec: TaskSpec,
) -> tuple[list[str], int, dict[str, int]] | None:
    vocabulary = _question_tag_vocabulary(spec)
    if vocabulary is None or not isinstance(candidate, dict):
        return None
    raw_tags = candidate.get("tags")
    if not isinstance(raw_tags, list):
        return None

    canonical = set(vocabulary.canonical_labels)
    sanitized = [
        value
        if isinstance(value, str) and value in canonical
        else "<noncanonical>"
        if isinstance(value, str)
        else "<nonstring>"
        for value in raw_tags
    ]
    return sanitized, len(sanitized), dict(Counter(sanitized))


def _question_tag_vocabulary(spec: TaskSpec) -> QuestionTagVocabulary | None:
    if (
        spec.name == "question_tag"
        and spec.version == "question-tag-v2"
        and spec.metadata.get("vocabulary_version") == QUESTION_TAG_VOCABULARY.version
    ):
        return QUESTION_TAG_VOCABULARY
    if (
        spec.name == "question_tag_v3"
        and spec.version == "question-tag-v3"
        and spec.metadata.get("vocabulary_version")
        == SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.version
    ):
        return SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY
    return None


def _notify(
    observer: ValidationDiagnosticObserver | None,
    diagnostic: StructuredValidationDiagnostic,
) -> None:
    if observer is None:
        return
    try:
        observer(diagnostic)
    except Exception:
        # Diagnostics must never alter validation or retry behavior.
        return


def validate_structured_response(
    response: StructuredGenerationResponse,
    spec: TaskSpec,
    *,
    attempts: int,
    task_id: str | None = None,
    diagnostic_observer: ValidationDiagnosticObserver | None = None,
) -> StructuredGenerationResponse:
    """Decode and strictly revalidate one raw response against its TaskSpec."""

    assert spec.output_model is not None
    candidate: Any = None
    try:
        candidate = json.loads(response.raw_text)
        result = spec.output_model.model_validate(candidate, strict=spec.validation.strict)
    except (json.JSONDecodeError, ValidationError) as exc:
        errors = _errors(exc)
        category: StructuredValidationCategory = (
            "json_decoding_failure"
            if isinstance(exc, json.JSONDecodeError)
            else _validation_category(exc)
        )
        locations = [] if isinstance(exc, json.JSONDecodeError) else [
            str(error["loc"]) for error in exc.errors()
        ]
        tag_summary = _safe_question_tag_summary(candidate, spec)
        _notify(
            diagnostic_observer,
            StructuredValidationDiagnostic(
                attempt=attempts,
                category=category,
                locations=locations,
                messages=[
                    f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
                ]
                if isinstance(exc, json.JSONDecodeError)
                else [str(error["msg"]) for error in exc.errors()],
                success=False,
                sanitized_tags=tag_summary[0] if tag_summary is not None else None,
                tag_count=tag_summary[1] if tag_summary is not None else None,
                tag_frequencies=tag_summary[2] if tag_summary is not None else None,
            ),
        )
        raise StructuredOutputValidationError(
            task=spec.name, attempts=attempts, errors=errors
        ) from exc
    validation = StructuredValidationInfo(
        valid=True,
        attempts=attempts,
        task=task_id or spec.name,
        task_version=spec.version,
    )
    tag_summary = _safe_question_tag_summary(candidate, spec)
    _notify(
        diagnostic_observer,
        StructuredValidationDiagnostic(
            attempt=attempts,
            category="success",
            success=True,
            sanitized_tags=tag_summary[0] if tag_summary is not None else None,
            tag_count=tag_summary[1] if tag_summary is not None else None,
            tag_frequencies=tag_summary[2] if tag_summary is not None else None,
        ),
    )
    provenance = response.provenance.model_copy(update={"task_version": spec.version})
    return response.model_copy(
        update={"data": result, "provenance": provenance, "validation": validation}
    )
