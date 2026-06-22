"""ChromaDB access and Gemini embedding generation."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from google import genai
from google.genai import types

from config import settings


# Required singleton: one persistent Chroma client is reused for the process.
settings.chroma_db_path.mkdir(parents=True, exist_ok=True)
_chroma_client = chromadb.PersistentClient(path=str(settings.chroma_db_path))


@lru_cache(maxsize=1)
def _get_gemini_client() -> genai.Client:
    """Create Gemini lazily so imports and offline tests do not require a key."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required to generate embeddings")
    return genai.Client(api_key=settings.gemini_api_key)


def get_student_collection(student_id: str) -> Collection:
    """Return the isolated cosine-distance collection for one student."""
    if not student_id.strip():
        raise ValueError("student_id must not be empty")
    return _chroma_client.get_or_create_collection(
        name=f"student_{student_id}",
        configuration={"hnsw": {"space": "cosine"}},
    )


def embed_text(text: str) -> list[float]:
    """Embed text with Gemini using the required 768-dimensional output."""
    if not text.strip():
        raise ValueError("text must not be empty")

    result = _get_gemini_client().models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=types.EmbedContentConfig(
            output_dimensionality=settings.embedding_dimensions
        ),
    )
    if not result.embeddings or result.embeddings[0].values is None:
        raise RuntimeError("Gemini returned no embedding values")
    return [float(value) for value in result.embeddings[0].values]


def chroma_client() -> Any:
    """Expose the singleton client for health checks and administrative code."""
    return _chroma_client
