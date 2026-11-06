"""Initial Phase 4 task registry entries with deliberately small schemas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.model_client.taskspec import (
    TaskGenerationDefaults,
    TaskSpec,
    TaskSpecRegistry,
    ValidationPolicy,
)
from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
    QuestionTagCanonical,
    SubjectNeutralQuestionTagCanonical,
)


class StringListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(min_length=1, max_length=128)


class PrerequisiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[dict[str, str]] = Field(max_length=128)


class QuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)


class TagResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(max_length=32)


class QuestionTagResult(BaseModel):
    """Strict canonical output for the versioned question-tag task."""

    model_config = ConfigDict(extra="forbid")

    tags: list[QuestionTagCanonical] = Field(min_length=2, max_length=3)

    @field_validator("tags")
    @classmethod
    def validate_unique_tags(cls, value: list[QuestionTagCanonical]) -> list[QuestionTagCanonical]:
        if len(value) != len(set(value)):
            raise ValueError("question tags must be unique")
        return value


class SubjectNeutralQuestionTagResult(BaseModel):
    """Strict canonical output for the subject-neutral question-tag task."""

    model_config = ConfigDict(extra="forbid")

    tags: list[SubjectNeutralQuestionTagCanonical] = Field(min_length=2, max_length=3)

    @field_validator("tags")
    @classmethod
    def validate_unique_tags(
        cls, value: list[SubjectNeutralQuestionTagCanonical]
    ) -> list[SubjectNeutralQuestionTagCanonical]:
        if len(value) != len(set(value)):
            raise ValueError("question tags must be unique")
        return value


class GradeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool
    confidence: float = Field(ge=0.0, le=1.0)


class MisconceptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["NONE", "POSSIBLE", "CONFIRMED"]


class UncertaintyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


def _structured(
    name: str,
    version: str,
    model: type[BaseModel],
    *,
    metadata: Mapping[str, str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        name=name,
        version=version,
        output_mode="structured",
        output_model=model,
        generation=TaskGenerationDefaults(model_id="meta-llama/Llama-3.2-3B-Instruct"),
        validation=ValidationPolicy(max_retries=1, strict=True),
        metadata=dict(metadata or {}),
    )


def default_task_registry() -> TaskSpecRegistry:
    """Return a fresh registry so callers cannot mutate global state."""

    return TaskSpecRegistry(
        (
            _structured("answer_grade_rubric", "answer-grade-rubric-v1", GradeResult),
            _structured("concept_extract", "concept-extract-v1", StringListResult),
            _structured("diagnose_uncertain", "diagnose-uncertain-v1", UncertaintyResult),
            TaskSpec(
                name="decision_explain",
                version="decision-explain-v1",
                output_mode="text",
            ),
            _structured("misconception_classify", "misconception-classify-v1", MisconceptionResult),
            _structured("objective_extract", "objective-extract-v1", StringListResult),
            _structured("prereq_propose", "prereq-propose-v1", PrerequisiteResult),
            _structured("question_generate", "question-generate-v1", QuestionResult),
            _structured(
                "question_tag",
                "question-tag-v2",
                QuestionTagResult,
                metadata={
                    "vocabulary_id": QUESTION_TAG_VOCABULARY.vocabulary_id,
                    "vocabulary_version": QUESTION_TAG_VOCABULARY.version,
                },
            ),
            _structured(
                "question_tag_v3",
                "question-tag-v3",
                SubjectNeutralQuestionTagResult,
                metadata={
                    "vocabulary_id": SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.vocabulary_id,
                    "vocabulary_version": SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY.version,
                },
            ),
            _structured("syllabus_unit_extract", "syllabus-unit-extract-v1", StringListResult),
            TaskSpec(
                name="lesson_block",
                version="lesson-block-v1",
                output_mode="text",
                family_prefix="lesson_block_",
            ),
            TaskSpec(
                name="lesson_hard",
                version="lesson-hard-v1",
                output_mode="structured",
                output_model=UncertaintyResult,
            ),
        )
    )
