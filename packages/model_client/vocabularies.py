"""Versioned closed vocabularies used by model task contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionTagRole = Literal["topic", "skill", "representation"]
QuestionTagCanonical = Literal["fractions", "comparison", "number line"]
SubjectNeutralQuestionTagCanonical = Literal[
    "fractions",
    "equations",
    "algorithms",
    "data structures",
    "forces",
    "waves",
    "matter",
    "chemical reactions",
    "cells",
    "genetics",
    "comparison",
    "calculation",
    "number line",
    "diagram",
]


class QuestionTagVocabularyEntry(BaseModel):
    """One canonical question-tag label and its compatibility-only aliases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    role: QuestionTagRole
    aliases: tuple[str, ...] = ()


class QuestionTagVocabulary(BaseModel):
    """A partial, versioned question-tag vocabulary manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vocabulary_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    exhaustive: bool = False
    entries: tuple[QuestionTagVocabularyEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> QuestionTagVocabulary:
        labels = [entry.label for entry in self.entries]
        if len(labels) != len(set(labels)):
            raise ValueError("question-tag vocabulary labels must be unique")
        aliases = [alias for entry in self.entries for alias in entry.aliases]
        if len(aliases) != len(set(aliases)):
            raise ValueError("question-tag vocabulary aliases must be unique")
        if set(labels) & set(aliases):
            raise ValueError("question-tag vocabulary aliases cannot be canonical labels")
        return self

    @property
    def canonical_labels(self) -> tuple[str, ...]:
        return tuple(entry.label for entry in self.entries)

    @property
    def alias_map(self) -> Mapping[str, str]:
        """Return compatibility mappings without making them live-output rules."""

        return {
            alias: entry.label for entry in self.entries for alias in entry.aliases
        }


QUESTION_TAG_VOCABULARY = QuestionTagVocabulary(
    vocabulary_id="question-tags",
    version="1.0.0",
    scope="Phase 4.6 synthetic benchmark seed; partial and non-exhaustive",
    exhaustive=False,
    entries=(
        QuestionTagVocabularyEntry(
            label="fractions",
            role="topic",
            aliases=("fraction",),
        ),
        QuestionTagVocabularyEntry(
            label="comparison",
            role="skill",
            aliases=("compare", "comparing"),
        ),
        QuestionTagVocabularyEntry(
            label="number line",
            role="representation",
            aliases=("number-line", "numberline"),
        ),
    ),
)


SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY = QuestionTagVocabulary(
    vocabulary_id="question-tags",
    version="2.0.0",
    scope="Phase 4.6 subject-neutral synthetic benchmark seed; partial and non-exhaustive",
    exhaustive=False,
    entries=(
        QuestionTagVocabularyEntry(label="fractions", role="topic", aliases=("fraction",)),
        QuestionTagVocabularyEntry(label="equations", role="topic"),
        QuestionTagVocabularyEntry(label="algorithms", role="topic"),
        QuestionTagVocabularyEntry(label="data structures", role="topic"),
        QuestionTagVocabularyEntry(label="forces", role="topic"),
        QuestionTagVocabularyEntry(label="waves", role="topic"),
        QuestionTagVocabularyEntry(label="matter", role="topic"),
        QuestionTagVocabularyEntry(label="chemical reactions", role="topic"),
        QuestionTagVocabularyEntry(label="cells", role="topic"),
        QuestionTagVocabularyEntry(label="genetics", role="topic"),
        QuestionTagVocabularyEntry(
            label="comparison",
            role="skill",
            aliases=("compare", "comparing"),
        ),
        QuestionTagVocabularyEntry(label="calculation", role="skill"),
        QuestionTagVocabularyEntry(
            label="number line",
            role="representation",
            aliases=("number-line", "numberline"),
        ),
        QuestionTagVocabularyEntry(label="diagram", role="representation"),
    ),
)
