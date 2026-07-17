"""Mock embedding provider — deterministic embeddings for testing.

Produces reproducible embedding vectors without any network calls.
Uses a deterministic hash-based approach so same text always produces
the same embedding, enabling predictable test assertions.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from app.ingestion.embedding.base import (
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingResult,
)


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for testing.

    Produces repeatable embeddings using SHA-256 based seeding.
    Embeddings are normalized (unit length) and match the configured
    dimensionality.

    Usage::

        provider = MockEmbeddingProvider()
        result = await provider.embed_text("Hello, world!")
        assert len(result.embedding) == 768  # default dimensions
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        super().__init__(config)
        self._call_count: int = 0
        self._call_history: list[str] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def embedding_dimensions(self) -> int:
        return self.config.embedding_dimensions

    @property
    def call_count(self) -> int:
        """Number of embed calls made."""
        return self._call_count

    @property
    def call_history(self) -> list[str]:
        """List of texts that have been embedded (in order)."""
        return list(self._call_history)

    def reset(self) -> None:
        """Reset call count and history."""
        self._call_count = 0
        self._call_history.clear()

    async def embed_text(self, text: str) -> EmbeddingResult:
        """Embed a single text using deterministic hashing."""
        self._call_count += 1
        self._call_history.append(text)

        embedding = self._deterministic_embedding(text, self.config.embedding_dimensions)

        return EmbeddingResult(
            text=text,
            embedding=embedding,
            model_used=f"mock-{self.config.model_name}",
            dimensions=len(embedding),
        )

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts."""
        results = []
        for text in texts:
            result = await self.embed_text(text)
            results.append(result)
        return results

    def _deterministic_embedding(self, text: str, dimensions: int) -> list[float]:
        """Generate a deterministic embedding vector from text.

        Uses SHA-256 to seed a deterministic sequence of floats.
        The embedding is normalized to unit length.
        """
        # Use hash to seed a deterministic sequence
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()

        # Generate enough seed values from the hash
        values: list[float] = []
        for i in range(dimensions):
            # Mix the hash with the index
            idx_bytes = str(i).encode()
            mix = hashlib.sha256(hash_bytes + idx_bytes).digest()
            # Convert first 4 bytes to a float in [-1, 1]
            val = int.from_bytes(mix[:4], "big", signed=True) / (2**31 - 1)
            values.append(val)

        # Normalize to unit length
        magnitude = sum(v * v for v in values) ** 0.5
        if magnitude > 0:
            values = [v / magnitude for v in values]

        return values
