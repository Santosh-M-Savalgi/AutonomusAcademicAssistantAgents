"""Provider factory — the only entry point for LLM access.

Registers: deepseek, gemini, mock.
Startup validation enforces: if LLM_PROVIDER=deepseek, DEEPSEEK_API_KEY
must be set — refuses to start otherwise.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.llm.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderError,
)
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.mock import MockProvider


class ProviderFactory:
    """Creates and caches LLM provider instances."""

    PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
        "deepseek": DeepSeekProvider,
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

        # ── Hard block: deepseek requires an API key ────────────────────
        if self._provider_name == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            if not key:
                raise ProviderError(
                    "DEEPSEEK_API_KEY is not set. "
                    "LLM_PROVIDER=deepseek requires a valid API key. "
                    "Set DEEPSEEK_API_KEY in .env.",
                    provider="deepseek",
                )

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
        """Register a custom provider class."""
        self.PROVIDER_REGISTRY[name] = provider_cls

    @classmethod
    def from_settings(cls) -> "ProviderFactory":
        """Create a factory from application settings.

        Reads ``LLM_PROVIDER`` env var. Defaults to ``mock``
        (dev/test only — production must set explicitly).
        """
        provider = os.environ.get("LLM_PROVIDER", "mock").lower()
        return cls(provider_name=provider)

    @classmethod
    def from_env(cls) -> "ProviderFactory":
        """Alias for ``from_settings()``."""
        return cls.from_settings()


@lru_cache(maxsize=1)
def get_provider() -> BaseProvider:
    """Convenience: return the default provider from settings.

    Cached. Use ``ProviderFactory`` directly for test-time overrides.
    """
    factory = ProviderFactory.from_settings()
    return factory.get_provider()


def validate_provider_startup() -> list[str]:
    """Startup validation: ensure provider is usable.

    Returns a list of error messages (empty = OK).
    Called at app startup before accepting traffic.
    """
    errors: list[str] = []
    provider = os.environ.get("LLM_PROVIDER", "mock").lower()

    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            errors.append(
                "LLM_PROVIDER=deepseek but DEEPSEEK_API_KEY is empty. "
                "Set DEEPSEEK_API_KEY in .env or switch to a different provider."
            )
        else:
            # Key exists but might be invalid — quick format check
            if len(key) < 10:
                errors.append(
                    "DEEPSEEK_API_KEY appears too short (< 10 chars). "
                    "Verify your key is correct."
                )

    return errors
