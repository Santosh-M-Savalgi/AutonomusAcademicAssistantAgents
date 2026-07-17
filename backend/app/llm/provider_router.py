"""Provider factory — the only entry point for LLM access (Sprint 3 Phase A).

The application must never import provider classes directly. Always use
``get_provider()`` or the ``ProviderFactory`` class.

Configuration determines which provider is active via the ``LLM_PROVIDER``
environment variable (default: ``mock`` for development and testing).
"""

from __future__ import annotations

from functools import lru_cache

from app.llm.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
)
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.mock import MockProvider


class ProviderFactory:
    """Creates and caches LLM provider instances.

    Usage::

        # Production
        factory = ProviderFactory(provider_name="gemini")
        provider = factory.get_provider()

        # Testing
        factory = ProviderFactory(provider_name="mock")
        provider = factory.get_provider()
    """

    PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
        "gemini": GeminiProvider,
        "mock": MockProvider,
    }

    def __init__(
        self,
        provider_name: str | None = None,
        config: ProviderConfig | None = None,
    ):
        self._provider_name = provider_name or "mock"
        self._config = config or ProviderConfig()
        self._instance: BaseProvider | None = None

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def get_provider(self) -> BaseProvider:
        """Return (and cache) the provider instance for the configured name."""
        if self._instance is not None:
            return self._instance

        provider_cls = self.PROVIDER_REGISTRY.get(self._provider_name)
        if provider_cls is None:
            raise ProviderError(
                f"Unknown provider '{self._provider_name}'. "
                f"Available: {list(self.PROVIDER_REGISTRY)}",
            )

        self._instance = provider_cls(self._config)
        return self._instance

    def set_provider(self, provider_name: str) -> None:
        """Switch to a different provider (resets the cached instance)."""
        if provider_name not in self.PROVIDER_REGISTRY:
            raise ProviderError(
                f"Unknown provider '{provider_name}'. "
                f"Available: {list(self.PROVIDER_REGISTRY)}",
            )
        self._provider_name = provider_name
        self._instance = None

    def register_provider(self, name: str, provider_cls: type[BaseProvider]) -> None:
        """Register a custom provider class for the factory."""
        self.PROVIDER_REGISTRY[name] = provider_cls

    @classmethod
    def from_settings(cls) -> "ProviderFactory":
        """Create a factory from application settings.

        Reads ``LLM_PROVIDER`` env var. Defaults to ``mock``.
        """
        import os

        provider = os.environ.get("LLM_PROVIDER", "mock").lower()
        return cls(provider_name=provider)


@lru_cache(maxsize=1)
def get_provider() -> BaseProvider:
    """Convenience: return the default provider from settings.

    Cached to avoid re-creating the provider on every request.
    Use ``ProviderFactory`` directly for test-time overrides.
    """
    factory = ProviderFactory.from_settings()
    return factory.get_provider()
