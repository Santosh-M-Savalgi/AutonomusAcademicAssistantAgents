"""Offline validation for Agent 1's Gemini request and PDF input path."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agents import syllabus_parser


SAMPLE_CASES = [
    (
        "I want to learn machine learning",
        ["Python fundamentals", "Linear algebra", "Machine learning"],
    ),
    (
        "teach me web development",
        ["HTML", "CSS", "JavaScript"],
    ),
    (
        "I want to learn data structures and algorithms",
        ["Programming fundamentals", "Data structures", "Algorithms"],
    ),
]


def _topic(name: str, prerequisite: str | None) -> dict[str, Any]:
    return {
        "topic_name": name,
        "subtopics": [f"{name} basics"],
        "difficulty": "beginner",
        "prerequisite": prerequisite,
    }


class FakeModels:
    def __init__(self, topic_names: list[str]) -> None:
        self.calls: list[dict[str, Any]] = []
        topics = [
            _topic(name, topic_names[index - 1] if index else None)
            for index, name in enumerate(topic_names)
        ]
        self.response_text = json.dumps({"topics": topics})

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.response_text)


@pytest.mark.parametrize(("raw_input", "topic_names"), SAMPLE_CASES)
def test_parse_sample_syllabi(
    monkeypatch: pytest.MonkeyPatch,
    raw_input: str,
    topic_names: list[str],
) -> None:
    models = FakeModels(topic_names)
    monkeypatch.setattr(
        syllabus_parser,
        "_get_client",
        lambda: SimpleNamespace(models=models),
    )

    topics = syllabus_parser.parse_syllabus(raw_input=raw_input)

    ordered_names = [topic["topic_name"] for topic in topics]
    print(f"{raw_input}: {ordered_names}")
    assert ordered_names == topic_names

    call = models.calls[0]
    assert call["model"] == "gemini-2.5-flash-lite"
    assert raw_input in call["contents"]
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema == syllabus_parser.SYLLABUS_SCHEMA
    assert call["config"].temperature == 0.3

    prerequisite_schema = syllabus_parser.SYLLABUS_SCHEMA["properties"]["topics"]["items"]["properties"]["prerequisite"]
    assert prerequisite_schema == {"type": "STRING", "nullable": True}


def test_pdf_text_uses_the_same_parse_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    models = FakeModels(["Variables", "Functions"])
    monkeypatch.setattr(
        syllabus_parser,
        "_get_client",
        lambda: SimpleNamespace(models=models),
    )
    monkeypatch.setattr(
        syllabus_parser,
        "extract_text_from_pdf",
        lambda _path: "Variables followed by functions",
    )

    topics = syllabus_parser.parse_syllabus(
        raw_input="Teach this course",
        pdf_path="syllabus.pdf",
    )

    assert [topic["topic_name"] for topic in topics] == ["Variables", "Functions"]
    assert "Teach this course" in models.calls[0]["contents"]
    assert "Variables followed by functions" in models.calls[0]["contents"]
    assert len(models.calls) == 1


def test_parse_syllabus_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="raw_input or a PDF"):
        syllabus_parser.parse_syllabus()
