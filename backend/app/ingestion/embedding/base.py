"""Embedding provider abstraction (Sprint 4 Phase C).

Follows the same architecture as Sprint 3's LLM provider pattern:
- BaseEmbeddingProvider (abstract interface)
- GeminiEmbeddingProvider (wraps Google's embedding API)
- MockEmbeddingProvider (deterministic, for testing)

Embedding providers are independent from LLM providers. They implement
a different interface (embed_text, embed_batch) and are configured
separately.

No hardcoded provider logic. Use EmbeddingFactory to create providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class EmbeddingConfig:
    """Configuration for an embedding provider."""

    model_name: str = "text-embedding-004"
    embedding_dimensions: int = 768
    batch_size: int = 100
    timeout_seconds: float = 30.0
    extra: dict = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    """Result from embedding a single text."""

    text: str
    embedding: list[float]
    model_used: str
    dimensions: int


class EmbeddingError(Exception):
    """Base exception for embedding provider errors."""

    def __init__(self, message: str, provider: str = "unknown", cause: Exception | None = None):
        self.provider = provider
        self.cause = cause
        super().__init__(message)


class EmbeddingProvider(ABC):
    """Abstract base for all embedding providers.

    Every embedding provider must implement ``embed_text()``, ``embed_batch()``,
    and ``embedding_dimensions``.

    Providers should NEVER be imported directly by application code —
    always go through ``EmbeddingFactory``.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig()

    @abstractmethod
    async def embed_text(self, text: str) -> EmbeddingResult:
        """Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            An ``EmbeddingResult`` with the embedding vector.

        Raises:
            EmbeddingError: On provider failure.
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts efficiently.

        Args:
            texts: The texts to embed.

        Returns:
            A list of ``EmbeddingResult`` objects, one per input text.
        """
        ...

    @property
    @abstractmethod
    def embedding_dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier (e.g. ``gemini``, ``mock``)."""
        ...
