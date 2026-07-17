"""Embedding factory — single entry point for embedding access (Sprint 4 Phase C).

Follows the Sprint 3 ProviderFactory pattern: registry-based, cached
instances, environment-driven configuration.

Usage::

    factory = EmbeddingFactory(provider_name="mock")
    provider = factory.get_embedding_provider()
    result = await provider.embed_text("Hello, world!")
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.ingestion.embedding.base import (
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingProvider,
)
from app.ingestion.embedding.gemini_embedding import GeminiEmbeddingProvider
from app.ingestion.embedding.mock_embedding import MockEmbeddingProvider


class EmbeddingFactory:
    """Creates and caches embedding provider instances.

    Usage::

        # Production
        factory = EmbeddingFactory(provider_name="gemini")
        provider = factory.get_embedding_provider()

        # Testing
        factory = EmbeddingFactory(provider_name="mock")
        provider = factory.get_embedding_provider()
    """

    PROVIDER_REGISTRY: dict[str, type[EmbeddingProvider]] = {
        "gemini": GeminiEmbeddingProvider,
        "mock": MockEmbeddingProvider,
    }

    def __init__(
        self,
        provider_name: str | None = None,
        config: EmbeddingConfig | None = None,
    ):
        self._provider_name = provider_name or "mock"
        self._config = config or EmbeddingConfig()
        self._instance: EmbeddingProvider | None = None

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_embedding_provider(self) -> EmbeddingProvider:
        """Return (and cache) the embedding provider instance."""
        if self._instance is not None:
            return self._instance

        provider_cls = self.PROVIDER_REGISTRY.get(self._provider_name)
        if provider_cls is None:
            raise EmbeddingError(
                f"Unknown embedding provider '{self._provider_name}'. "
                f"Available: {list(self.PROVIDER_REGISTRY)}",
                provider=self._provider_name,
            )

        self._instance = provider_cls(self._config)
        return self._instance

    def set_provider(self, provider_name: str) -> None:
        """Switch to a different provider (resets the cached instance)."""
        if provider_name not in self.PROVIDER_REGISTRY:
            raise EmbeddingError(
                f"Unknown embedding provider '{provider_name}'. "
                f"Available: {list(self.PROVIDER_REGISTRY)}",
                provider=provider_name,
            )
        self._provider_name = provider_name
        self._instance = None

    def register_provider(self, name: str, provider_cls: type[EmbeddingProvider]) -> None:
        """Register a custom embedding provider class."""
        self.PROVIDER_REGISTRY[name] = provider_cls

    @classmethod
    def from_settings(cls) -> "EmbeddingFactory":
        """Create a factory from application settings.

        Reads ``EMBEDDING_PROVIDER`` env var. Defaults to ``mock``.
        """
        provider = os.environ.get("EMBEDDING_PROVIDER", "mock").lower()
        model = os.environ.get("EMBEDDING_MODEL", "text-embedding-004")
        config = EmbeddingConfig(model_name=model)
        return cls(provider_name=provider, config=config)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Convenience: return the default embedding provider from settings.

    Cached to avoid re-creating the provider on every request.
    Use ``EmbeddingFactory`` directly for test-time overrides.
    """
    factory = EmbeddingFactory.from_settings()
    return factory.get_embedding_provider()
