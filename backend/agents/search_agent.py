"""Agent 2: retrieve, summarize, embed, and persist teaching sources."""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from google import genai
from tavily import TavilyClient

from config import settings
from persistence.vector_store import embed_text, get_student_collection


class SearchResult(TypedDict):
    source_url: str
    summary: str
    score: float


@lru_cache(maxsize=1)
def _get_gemini_client() -> genai.Client:
    """Create one Gemini client lazily for search summarization calls."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for search summarization")
    return genai.Client(api_key=settings.gemini_api_key)


@lru_cache(maxsize=1)
def _get_tavily_client() -> TavilyClient:
    """Create one Tavily client lazily so imports work without API keys."""
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    return TavilyClient(api_key=settings.tavily_api_key)


def summarize_with_gemini(content: str, topic_name: str) -> str:
    """Condense a search result into source-grounded notes for the tutor."""
    response = _get_gemini_client().models.generate_content(
        model=settings.search_model,
        contents=(
            f'Summarize the following source for teaching "{topic_name}". '
            "Keep the important concepts, definitions, and examples. "
            "Do not add claims that are absent from the source.\n\n"
            f"Source content:\n{content}"
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty search summary")
    return response.text


def fallback_to_model_knowledge(topic_name: str, error: str) -> list[SearchResult]:
    """Return tutor notes from Gemini when Tavily is unavailable."""
    response = _get_gemini_client().models.generate_content(
        model=settings.search_model,
        contents=(
            f"Summarize key concepts for teaching '{topic_name}' to a student, "
            "as if briefing a tutor."
        ),
    )
    if not response.text:
        raise RuntimeError(
            f"Gemini fallback returned an empty response after Tavily failed: {error}"
        )
    return [
        {
            "source_url": "model_internal_knowledge",
            "summary": response.text,
            "score": 0.0,
        }
    ]


def search_and_store_topic(
    student_id: str, topic_name: str
) -> list[SearchResult]:
    """Search for a topic and store summarized sources in the student's collection."""
    if not student_id.strip():
        raise ValueError("student_id must not be empty")
    if not topic_name.strip():
        raise ValueError("topic_name must not be empty")

    try:
        results = _get_tavily_client().search(
            query=f"{topic_name} tutorial explanation",
            max_results=5,
        )
    except Exception as exc:
        return fallback_to_model_knowledge(topic_name, error=str(exc))

    collection = get_student_collection(student_id)
    stored: list[SearchResult] = []
    for result in results.get("results", []):
        source_url = str(result.get("url", "")).strip()
        content = str(result.get("content", "")).strip()
        if not source_url or not content:
            continue

        summary = summarize_with_gemini(content, topic_name)
        vector = embed_text(summary)
        score = float(result.get("score", 0.0))
        entry_id = f"{topic_name}_{source_url}"
        collection.upsert(
            ids=[entry_id],
            embeddings=[vector],
            metadatas=[
                {
                    "topic_name": topic_name,
                    "source_url": source_url,
                    "score": score,
                }
            ],
            documents=[summary],
        )
        stored.append(
            {"source_url": source_url, "summary": summary, "score": score}
        )
    return stored
