"""Gemini embedding provider — wraps Google's embedding API.

Follows the Sprint 3 GeminiProvider pattern (lazy client init,
async via asyncio.to_thread) but implements the EmbeddingProvider
interface instead of BaseProvider.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from app.ingestion.embedding.base import (
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingResult,
)


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using Google's Gemini embedding models.

    Uses ``text-embedding-004`` by default (768 dimensions, matching
    the existing ChromaDB collection schema).

    Configuration via environment:
    - ``GEMINI_API_KEY``: Google AI API key
    - ``EMBEDDING_PROVIDER``: set to ``gemini`` to activate
    - ``EMBEDDING_MODEL``: override the embedding model name
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        super().__init__(config)
        self._client = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def embedding_dimensions(self) -> int:
        return self.config.embedding_dimensions

    def _get_client(self):
        """Lazy initialization of the Google AI client."""
        if self._client is None:
            try:
                from google import genai

                import os

                api_key = os.environ.get("GEMINI_API_KEY", "")
                self._client = genai.Client(api_key=api_key)
            except ImportError:
                raise EmbeddingError(
                    "google-genai package not installed",
                    provider="gemini",
                )
            except Exception as exc:
                raise EmbeddingError(
                    f"Failed to create Gemini client: {exc}",
                    provider="gemini",
                )
        return self._client

    async def embed_text(self, text: str) -> EmbeddingResult:
        """Embed a single text string using Gemini."""
        try:
            client = self._get_client()
            result = await asyncio.to_thread(
                client.models.embed_content,
                model=self.config.model_name,
                contents=text,
            )
            embedding = list(result.embeddings[0].values)

            return EmbeddingResult(
                text=text,
                embedding=embedding,
                model_used=self.config.model_name,
                dimensions=len(embedding),
            )
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(
                f"Gemini embedding failed: {exc}",
                provider="gemini",
                cause=exc,
            )

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts using Gemini.

        Processes texts in batches of ``config.batch_size`` to respect
        provider limits.
        """
        results: list[EmbeddingResult] = []
        batch_size = self.config.batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_results = await self._embed_batch_inner(batch)
            results.extend(batch_results)

        return results

    async def _embed_batch_inner(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed one batch of texts."""
        try:
            client = self._get_client()
            result = await asyncio.to_thread(
                client.models.embed_content,
                model=self.config.model_name,
                contents=texts,
            )
            embeddings = [list(e.values) for e in result.embeddings]

            return [
                EmbeddingResult(
                    text=text,
                    embedding=emb,
                    model_used=self.config.model_name,
                    dimensions=len(emb),
                )
                for text, emb in zip(texts, embeddings, strict=False)
            ]
        except Exception as exc:
            raise EmbeddingError(
                f"Gemini batch embedding failed: {exc}",
                provider="gemini",
                cause=exc,
            )
