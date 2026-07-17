"""Base provider interface for LLM abstraction (Sprint 3 Phase A).

All LLM providers must implement BaseProvider. The application must never
call any provider SDK directly — all AI interactions go through this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ModelCapability(str, Enum):
    """Capabilities a provider may support."""

    CHAT = "chat"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    EMBEDDING = "embedding"


@dataclass
class ProviderConfig:
    """Configuration for a provider instance."""

    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout_seconds: float = 30.0
    retry_count: int = 2
    extra: dict = field(default_factory=dict)


@dataclass
class ProviderResponse:
    """Normalized response from any LLM provider."""

    content: str
    model_used: str
    finish_reason: str = "stop"
    usage: dict | None = None
    raw: dict | None = None


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, message: str, provider: str = "unknown", cause: Exception | None = None):
        self.provider = provider
        self.cause = cause
        super().__init__(message)


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""

    def __init__(self, provider: str = "unknown", timeout_seconds: float = 0.0):
        super().__init__(
            f"Provider {provider} timed out after {timeout_seconds}s",
            provider=provider,
        )


class ProviderRateLimitError(ProviderError):
    """Raised when a provider returns a rate-limit response."""

    def __init__(self, provider: str = "unknown", retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(
            f"Provider {provider} rate-limited (retry after {retry_after}s)",
            provider=provider,
        )


class BaseProvider(ABC):
    """Abstract base for all LLM providers.

    Every provider must implement ``generate()`` and ``supports()``.
    Providers should NEVER be imported directly by application code —
    always go through ``ProviderFactory``.
    """

    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig()

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Send a prompt to the LLM and return the normalized response.

        Args:
            prompt: The user/assistant prompt content.
            system_prompt: Optional system-level instruction.
            temperature: Override for generation temperature.
            max_tokens: Override for max output tokens.

        Returns:
            A ``ProviderResponse`` with the generated content.

        Raises:
            ProviderTimeoutError: When the request times out.
            ProviderRateLimitError: When rate-limited.
            ProviderError: For other provider failures.
        """
        ...

    @abstractmethod
    def supports(self, capability: ModelCapability) -> bool:
        """Check whether this provider supports a given capability."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier (e.g. ``gemini``, ``mock``)."""
        ...

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """Generate structured output (JSON schema constrained).

        Default implementation falls back to text generation with schema
        instructions. Providers with native structured output should override.
        """
        schema_hint = self._build_schema_hint(response_schema)
        combined_prompt = f"{prompt}\n\nRespond with valid JSON matching this schema:\n{schema_hint}"
        return await self.generate(
            combined_prompt,
            system_prompt=system_prompt,
            temperature=temperature or 0.1,
        )

    def _build_schema_hint(self, schema: type) -> str:
        """Build a JSON schema hint string for structured output."""
        try:
            # Try Pydantic v2 model
            return str(schema.model_json_schema())
        except Exception:
            return str(schema)
