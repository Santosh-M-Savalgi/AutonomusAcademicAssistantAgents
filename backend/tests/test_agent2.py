"""Offline validation for Agent 2 and the shared vector-store boundary."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from agents import search_agent
from persistence import vector_store


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)


def test_search_summarizes_embeds_and_stores_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tavily = SimpleNamespace(
        search=lambda **_kwargs: {
            "results": [
                {
                    "url": "https://example.test/linear-algebra",
                    "content": "Vectors have magnitude and direction.",
                    "score": 0.91,
                },
                {
                    "url": "https://example.test/matrices",
                    "content": "Matrices represent linear transformations.",
                    "score": 0.84,
                },
            ]
        }
    )
    collection = FakeCollection()
    monkeypatch.setattr(search_agent, "_get_tavily_client", lambda: tavily)
    monkeypatch.setattr(
        search_agent,
        "summarize_with_gemini",
        lambda content, topic: f"{topic}: {content}",
    )
    monkeypatch.setattr(search_agent, "embed_text", lambda _text: [0.25] * 768)
    monkeypatch.setattr(
        search_agent, "get_student_collection", lambda _student_id: collection
    )

    stored = search_agent.search_and_store_topic("student-1", "Linear algebra")

    assert len(stored) == 2
    assert stored[0]["source_url"] == "https://example.test/linear-algebra"
    assert stored[0]["score"] == 0.91
    assert len(collection.upserts) == 2
    assert len(collection.upserts[0]["embeddings"][0]) == 768
    assert collection.upserts[0]["metadatas"][0]["topic_name"] == "Linear algebra"


def test_tavily_failure_uses_model_knowledge_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTavily:
        def search(self, **_kwargs: Any) -> dict[str, Any]:
            raise ConnectionError("Tavily unavailable")

    fallback_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        search_agent, "_get_tavily_client", lambda: FailingTavily()
    )
    monkeypatch.setattr(
        search_agent,
        "fallback_to_model_knowledge",
        lambda topic, error: (
            fallback_calls.append((topic, error))
            or [
                {
                    "source_url": "model_internal_knowledge",
                    "summary": "Fallback notes",
                    "score": 0.0,
                }
            ]
        ),
    )

    stored = search_agent.search_and_store_topic("student-1", "Graph theory")

    assert stored[0]["source_url"] == "model_internal_knowledge"
    assert fallback_calls == [("Graph theory", "Tavily unavailable")]


def test_fallback_calls_flash_lite(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def generate_content(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(text="Internal model notes")

    monkeypatch.setattr(
        search_agent,
        "_get_gemini_client",
        lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        ),
    )

    result = search_agent.fallback_to_model_knowledge("Recursion", "timeout")

    assert calls[0]["model"] == "gemini-2.5-flash-lite"
    assert result == [
        {
            "source_url": "model_internal_knowledge",
            "summary": "Internal model notes",
            "score": 0.0,
        }
    ]


def test_embedding_model_and_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def embed_content(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1] * 768)]
        )

    monkeypatch.setattr(
        vector_store,
        "_get_gemini_client",
        lambda: SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)),
    )

    embedding = vector_store.embed_text("A non-empty document")

    assert len(embedding) == 768
    assert calls[0]["model"] == "gemini-embedding-001"
    assert calls[0]["config"].output_dimensionality == 768


def test_chroma_client_is_module_singleton() -> None:
    assert vector_store.chroma_client() is vector_store.chroma_client()
    assert "PersistentClient" not in inspect.getsource(
        search_agent.search_and_store_topic
    )
