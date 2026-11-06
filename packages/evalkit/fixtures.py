"""Small synthetic, non-production fixtures for deterministic evalkit tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from packages.evalkit.contracts import (
    DatasetIdentity,
    GradingExample,
    GroundingExample,
    GroundingSource,
    QuestionTagExample,
    RetrievalCandidate,
    RetrievalExample,
    SyllabusExample,
)
from packages.model_client.tasks import SubjectNeutralQuestionTagResult

QUESTION_TAG_V3_DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "data/datasets/question_tags_mixed_subject_v1.json"
)


def syllabus_fixtures() -> list[SyllabusExample]:
    dataset = DatasetIdentity(dataset_id="synthetic-syllabus", version="1.0.0")
    return [
        SyllabusExample(
            example_id="syllabus-001",
            dataset=dataset,
            input_material="A lesson introduces fractions with visual models.",
            expected_topics=["fractions", "visual models"],
            provenance={"source": "synthetic"},
        ),
        SyllabusExample(
            example_id="syllabus-002",
            dataset=dataset,
            input_material="A lesson compares equivalent fractions on a number line.",
            expected_topics=["equivalent fractions", "number line"],
            provenance={"source": "synthetic"},
        ),
    ]


def question_tag_fixtures() -> list[QuestionTagExample]:
    dataset = DatasetIdentity(dataset_id="synthetic-question-tags", version="1.0.0")
    return [
        QuestionTagExample(
            example_id="question-001",
            dataset=dataset,
            input_material="Which fraction is larger: one half or one third?",
            expected_tags=["fractions", "comparison"],
            provenance={"source": "synthetic"},
        ),
        QuestionTagExample(
            example_id="question-002",
            dataset=dataset,
            input_material="Place three quarters on a number line.",
            expected_tags=["fractions", "number line"],
            provenance={"source": "synthetic"},
        ),
    ]


def question_tag_v3_fixtures(
    path: Path = QUESTION_TAG_V3_DATASET_PATH,
) -> list[QuestionTagExample]:
    """Load and validate the source-backed subject-neutral v3 dataset."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("question-tag v3 dataset root must be an object")
    expected_manifest = {
        "dataset_id": "synthetic-question-tags-mixed-subject",
        "version": "1.0.0",
        "task": "question_tag_v3",
        "task_version": "question-tag-v3",
        "vocabulary_id": "question-tags",
        "vocabulary_version": "2.0.0",
    }
    for key, expected in expected_manifest.items():
        if payload.get(key) != expected:
            raise ValueError(f"question-tag v3 dataset has invalid {key}")

    raw_examples = payload.get("examples")
    if not isinstance(raw_examples, list) or len(raw_examples) != 24:
        raise ValueError("question-tag v3 dataset must contain exactly 24 examples")

    dataset = DatasetIdentity(
        dataset_id=expected_manifest["dataset_id"], version=expected_manifest["version"]
    )
    examples: list[QuestionTagExample] = []
    seen_ids: set[str] = set()
    for raw in raw_examples:
        if not isinstance(raw, dict):
            raise ValueError("question-tag v3 examples must be objects")
        example_id = raw.get("example_id")
        subject = raw.get("subject")
        question_type = raw.get("question_type")
        input_material = raw.get("input_material")
        expected_tags = raw.get("expected_tags")
        if not isinstance(example_id, str):
            raise ValueError("question-tag v3 example_id must be a string")
        if not isinstance(subject, str):
            raise ValueError(f"subject must be a string for {example_id}")
        if not isinstance(question_type, str):
            raise ValueError(f"question_type must be a string for {example_id}")
        if not isinstance(input_material, str):
            raise ValueError("question-tag v3 example identity and text fields must be strings")
        if example_id in seen_ids:
            raise ValueError(f"duplicate question-tag v3 example id: {example_id}")
        seen_ids.add(example_id)
        if not isinstance(expected_tags, list) or not all(
            isinstance(tag, str) for tag in expected_tags
        ):
            raise ValueError(f"invalid expected tags for {example_id}")
        try:
            SubjectNeutralQuestionTagResult.model_validate(
                {"tags": expected_tags}, strict=True
            )
        except ValueError as exc:
            raise ValueError(f"invalid canonical expected tags for {example_id}") from exc
        raw_provenance = raw.get("provenance", {})
        if not isinstance(raw_provenance, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_provenance.items()
        ):
            raise ValueError(f"invalid provenance for {example_id}")
        examples.append(
            QuestionTagExample(
                example_id=example_id,
                dataset=dataset,
                input_material=input_material,
                expected_tags=expected_tags,
                metadata={"subject": subject, "question_type": question_type},
                provenance=raw_provenance,
            )
        )

    subject_counts = Counter(example.metadata["subject"] for example in examples)
    if subject_counts != Counter(
        {"mathematics": 5, "computer science": 5, "physics": 5, "chemistry": 5, "biology": 4}
    ):
        raise ValueError("question-tag v3 subject distribution is inconsistent")
    question_type_counts = Counter(example.metadata["question_type"] for example in examples)
    if question_type_counts != Counter(
        {
            "comparison": 8,
            "calculation_application": 8,
            "representation_interpretation": 8,
        }
    ):
        raise ValueError("question-tag v3 question-type distribution is inconsistent")
    return examples


def grading_fixtures() -> list[GradingExample]:
    dataset = DatasetIdentity(dataset_id="synthetic-grading", version="1.0.0")
    return [
        GradingExample(
            example_id="grade-001",
            dataset=dataset,
            input_material="Response correctly identifies the numerator.",
            reference_label="correct",
            provenance={"source": "synthetic"},
        ),
        GradingExample(
            example_id="grade-002",
            dataset=dataset,
            input_material="Response gives an unrelated answer.",
            reference_label="incorrect",
            provenance={"source": "synthetic"},
        ),
    ]


def grounding_fixtures() -> list[GroundingExample]:
    dataset = DatasetIdentity(dataset_id="synthetic-grounding", version="1.0.0")
    return [
        GroundingExample(
            example_id="grounding-001",
            dataset=dataset,
            input_material="Explain the numerator using the supplied lesson note.",
            reference_source_ids=["lesson-note-1"],
            source_context=[
                GroundingSource(
                    source_id="lesson-note-1",
                    content="The numerator is the top number in a fraction.",
                ),
                GroundingSource(
                    source_id="lesson-note-2",
                    content="The denominator is the bottom number in a fraction.",
                ),
            ],
            provenance={"source": "synthetic"},
        ),
        GroundingExample(
            example_id="grounding-002",
            dataset=dataset,
            input_material="Explain the denominator using the supplied lesson note.",
            reference_source_ids=["lesson-note-2"],
            source_context=[
                GroundingSource(
                    source_id="lesson-note-1",
                    content="The numerator is the top number in a fraction.",
                ),
                GroundingSource(
                    source_id="lesson-note-2",
                    content="The denominator is the bottom number in a fraction.",
                ),
            ],
            provenance={"source": "synthetic"},
        ),
    ]


def retrieval_fixtures() -> list[RetrievalExample]:
    dataset = DatasetIdentity(dataset_id="synthetic-retrieval", version="1.0.0")
    candidates = [
        RetrievalCandidate(document_id="doc-fractions", text="fraction lesson"),
        RetrievalCandidate(document_id="doc-number-line", text="number line lesson"),
        RetrievalCandidate(document_id="doc-decimals", text="decimal lesson"),
        RetrievalCandidate(document_id="doc-shapes", text="shapes lesson"),
        RetrievalCandidate(document_id="doc-measurement", text="measurement lesson"),
    ]
    return [
        RetrievalExample(
            example_id="retrieval-001",
            dataset=dataset,
            input_material="fraction lesson",
            candidates=candidates,
            relevant_document_ids=["doc-fractions"],
            provenance={"source": "synthetic"},
        ),
        RetrievalExample(
            example_id="retrieval-002",
            dataset=dataset,
            input_material="number line lesson",
            candidates=candidates,
            relevant_document_ids=["doc-number-line"],
            provenance={"source": "synthetic"},
        ),
    ]
