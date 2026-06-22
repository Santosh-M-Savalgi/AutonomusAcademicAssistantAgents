"""Offline tests for Agent 3's retrieval, tutoring, quiz, and evaluation flow."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from typing import Any

import pytest

from agents import tutor_quiz_agent
from persistence import vector_store


class FakeCollection:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, list[list[Any]]]:
        self.calls.append(kwargs)
        return {
            "documents": [["high match", "medium match", "boundary", "low match"]],
            "distances": [[0.10, 0.24, 0.25, 0.60]],
        }


def test_retrieve_context_filters_by_cosine_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = FakeCollection()
    monkeypatch.setattr(
        tutor_quiz_agent,
        "get_student_collection",
        lambda student_id: collection,
    )
    monkeypatch.setattr(
        tutor_quiz_agent, "embed_text", lambda text: [0.5] * 768
    )

    documents = tutor_quiz_agent.retrieve_context(
        "student-1", "Binary trees", threshold=0.75
    )

    assert documents == ["high match", "medium match"]
    assert collection.calls == [
        {"query_embeddings": [[0.5] * 768], "n_results": 5}
    ]


def test_teach_topic_uses_flash_and_required_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def generate_content(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(text="Concept -> Example -> Analogy")

    monkeypatch.setattr(
        tutor_quiz_agent,
        "_get_client",
        lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        ),
    )

    lesson = tutor_quiz_agent.teach_topic(
        "Recursion", ["A function may call itself."], "beginner"
    )

    assert lesson == "Concept -> Example -> Analogy"
    assert calls[0]["model"] == "gemini-2.5-flash"
    assert "Concept -> Worked Example -> Real-world Analogy" in calls[0]["contents"]
    assert "A function may call itself." in calls[0]["contents"]


def test_generate_quiz_uses_native_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    quiz = {
        "questions": [
            {"question": f"Question {index}?", "expected_concept": "A concept"}
            for index in range(1, 4)
        ]
    }

    def generate_content(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(quiz))

    monkeypatch.setattr(
        tutor_quiz_agent,
        "_get_client",
        lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        ),
    )

    questions = tutor_quiz_agent.generate_quiz("A complete lesson")

    assert questions == quiz["questions"]
    assert calls[0]["model"] == "gemini-2.5-flash"
    assert calls[0]["config"].response_mime_type == "application/json"
    assert calls[0]["config"].response_schema == tutor_quiz_agent.QUIZ_SCHEMA


def test_evaluate_answers_uses_native_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    evaluation = {
        "score": 80.0,
        "per_question_feedback": ["Correct", "Mostly correct", "Correct"],
        "verdict": "pass",
    }

    def generate_content(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(evaluation))

    monkeypatch.setattr(
        tutor_quiz_agent,
        "_get_client",
        lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        ),
    )
    questions = [
        {"question": f"Question {index}?", "expected_concept": "Concept"}
        for index in range(1, 4)
    ]

    result = tutor_quiz_agent.evaluate_answers(questions, ["A", "B", "C"])

    assert result == evaluation
    assert calls[0]["model"] == "gemini-2.5-flash"
    assert calls[0]["config"].response_mime_type == "application/json"
    assert calls[0]["config"].response_schema == tutor_quiz_agent.EVAL_SCHEMA
    assert "Pass threshold is 70" in calls[0]["contents"]


@pytest.mark.parametrize("topic", ["Recursion", "Binary trees", "SQL joins"])
def test_mocked_teach_quiz_evaluate_flow(
    monkeypatch: pytest.MonkeyPatch, topic: str
) -> None:
    quiz = {
        "questions": [
            {"question": f"How does {topic} work?", "expected_concept": topic},
            {"question": f"Give an example of {topic}.", "expected_concept": topic},
            {"question": f"When is {topic} useful?", "expected_concept": topic},
        ]
    }
    evaluation = {
        "score": 100.0,
        "per_question_feedback": ["Correct"] * 3,
        "verdict": "pass",
    }

    def generate_content(**kwargs: Any) -> SimpleNamespace:
        config = kwargs.get("config")
        if config is None:
            return SimpleNamespace(text=f"Lesson about {topic}")
        if config.response_schema == tutor_quiz_agent.QUIZ_SCHEMA:
            return SimpleNamespace(text=json.dumps(quiz))
        return SimpleNamespace(text=json.dumps(evaluation))

    monkeypatch.setattr(
        tutor_quiz_agent,
        "_get_client",
        lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        ),
    )

    lesson = tutor_quiz_agent.teach_topic(topic, ["Retrieved notes"], "beginner")
    questions = tutor_quiz_agent.generate_quiz(lesson)
    result = tutor_quiz_agent.evaluate_answers(questions, [topic] * 3)

    assert result["verdict"] == "pass"
    assert result["score"] == 100.0


def test_evaluation_requires_one_answer_per_question() -> None:
    questions = [{"question": "Why?", "expected_concept": "Reasoning"}]
    with pytest.raises(ValueError, match="one answer"):
        tutor_quiz_agent.evaluate_answers(questions, [])


def test_retrieval_uses_existing_chroma_singleton() -> None:
    assert vector_store.chroma_client() is vector_store.chroma_client()
    source = inspect.getsource(tutor_quiz_agent.retrieve_context)
    assert "get_student_collection" in source
    assert "PersistentClient" not in source
