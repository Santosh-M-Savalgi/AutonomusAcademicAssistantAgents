"""Tests for Sprint 3 Phase A — Provider Abstraction Layer.

Covers: BaseProvider, MockProvider, GeminiProvider (import only), ProviderFactory,
error types, and provider configuration.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.llm.provider_router import ProviderFactory, get_provider
from app.llm.providers.base import (
    BaseProvider,
    ModelCapability,
    ProviderConfig,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)
from app.llm.providers.mock import MockProvider


# ── Error types ─────────────────────────────────────────────────────────────


class TestProviderErrors:
    def test_provider_error_defaults(self) -> None:
        err = ProviderError("test error")
        assert str(err) == "test error"
        assert err.provider == "unknown"
        assert err.cause is None

    def test_provider_error_with_provider(self) -> None:
        err = ProviderError("test", provider="gemini")
        assert err.provider == "gemini"

    def test_provider_timeout_error(self) -> None:
        err = ProviderTimeoutError(provider="gemini", timeout_seconds=30.0)
        assert "timed out" in str(err)
        assert err.provider == "gemini"

    def test_provider_rate_limit_error(self) -> None:
        err = ProviderRateLimitError(provider="gemini", retry_after=60.0)
        assert "rate" in str(err).lower()
        assert err.retry_after == 60.0


# ── BaseProvider ────────────────────────────────────────────────────────────


class TestBaseProvider:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            BaseProvider()  # type: ignore[abstract]

    def test_provider_config_defaults(self) -> None:
        config = ProviderConfig()
        assert config.model_name == "gemini-2.5-flash"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.timeout_seconds == 30.0
        assert config.retry_count == 2

    def test_model_capability_enum_values(self) -> None:
        assert ModelCapability.CHAT.value == "chat"
        assert ModelCapability.STREAMING.value == "streaming"
        assert ModelCapability.EMBEDDING.value == "embedding"


# ── MockProvider ────────────────────────────────────────────────────────────


class TestMockProvider:
    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    def test_provider_name(self, provider: MockProvider) -> None:
        assert provider.provider_name == "mock"

    def test_supports_all(self, provider: MockProvider) -> None:
        assert provider.supports(ModelCapability.CHAT)
        assert provider.supports(ModelCapability.STREAMING)
        assert provider.supports(ModelCapability.EMBEDDING)

    @pytest.mark.asyncio
    async def test_default_response(self, provider: MockProvider) -> None:
        response = await provider.generate("Some prompt")
        assert "Mock provider default response" in response.content
        assert response.model_used == "mock-model"

    @pytest.mark.asyncio
    async def test_add_rule_matches(self, provider: MockProvider) -> None:
        provider.add_rule("python", "Mock Python lesson content")
        response = await provider.generate("Teach me Python")
        assert "Mock Python lesson content" in response.content

    @pytest.mark.asyncio
    async def test_add_rule_case_insensitive(self, provider: MockProvider) -> None:
        provider.add_rule("PYTHON", "Case insensitive match")
        response = await provider.generate("python is fun")
        assert "Case insensitive match" in response.content

    @pytest.mark.asyncio
    async def test_priority_order(self, provider: MockProvider) -> None:
        provider.add_rule("python", "Low priority", priority=0)
        provider.add_rule("python", "High priority", priority=10)
        response = await provider.generate("Teach python")
        assert "High priority" in response.content

    def test_clear_rules(self, provider: MockProvider) -> None:
        provider.add_rule("python", "content")
        provider.clear_rules()
        assert len(provider._rules) == 0

    @pytest.mark.asyncio
    async def test_call_history(self, provider: MockProvider) -> None:
        await provider.generate("First call")
        await provider.generate("Second call")
        assert len(provider.call_history) == 2
        assert provider.call_history[0]["prompt"] == "First call"
        assert provider.call_history[1]["prompt"] == "Second call"

    @pytest.mark.asyncio
    async def test_structured_output(self, provider: MockProvider) -> None:
        provider.add_rule("json", '{"key": "value"}')
        response = await provider.generate_structured("Give me JSON", dict)
        data = json.loads(response.content)
        assert data["key"] == "value"

    @pytest.mark.asyncio
    async def test_system_prompt_passed_in_history(self, provider: MockProvider) -> None:
        await provider.generate("Prompt", system_prompt="System instruction")
        assert provider.call_history[0]["system_prompt"] == "System instruction"

    @pytest.mark.asyncio
    async def test_temperature_and_max_tokens(self, provider: MockProvider) -> None:
        await provider.generate("Test", temperature=0.1, max_tokens=100)
        assert provider.call_history[0]["temperature"] == 0.1
        assert provider.call_history[0]["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_add_lesson_rule(self, provider: MockProvider) -> None:
        provider.add_lesson_rule("Python Lists")
        response = await provider.generate("Generate a lesson on Python Lists")
        data = json.loads(response.content)
        assert data["topic"] == "Python Lists"
        assert len(data["cards"]) == 3

    @pytest.mark.asyncio
    async def test_add_quiz_rule(self, provider: MockProvider) -> None:
        provider.add_quiz_rule("Python")
        response = await provider.generate("Create a quiz for Python")
        data = json.loads(response.content)
        assert len(data["questions"]) == 2
        assert data["questions"][0]["correct_answer"] == "Option A"


# ── ProviderFactory ─────────────────────────────────────────────────────────


class TestProviderFactory:
    def test_factory_creates_mock_default(self) -> None:
        factory = ProviderFactory()
        provider = factory.get_provider()
        assert provider.provider_name == "mock"

    def test_factory_creates_mock_explicit(self) -> None:
        factory = ProviderFactory(provider_name="mock")
        provider = factory.get_provider()
        assert isinstance(provider, MockProvider)

    def test_factory_unknown_provider(self) -> None:
        factory = ProviderFactory(provider_name="nonexistent")
        with pytest.raises(ProviderError, match="Unknown provider"):
            factory.get_provider()

    def test_factory_set_provider(self) -> None:
        factory = ProviderFactory(provider_name="mock")
        factory.get_provider()  # cache it
        factory.set_provider("mock")  # same provider, resets
        provider = factory.get_provider()
        assert provider.provider_name == "mock"

    def test_factory_set_provider_invalid(self) -> None:
        factory = ProviderFactory()
        with pytest.raises(ProviderError, match="Unknown provider"):
            factory.set_provider("invalid")

    def test_factory_register_custom(self) -> None:
        factory = ProviderFactory()

        class CustomProvider(MockProvider):
            @property
            def provider_name(self) -> str:
                return "custom"

        factory.register_provider("custom", CustomProvider)
        factory.set_provider("custom")
        provider = factory.get_provider()
        assert provider.provider_name == "custom"

    def test_factory_provider_name_property(self) -> None:
        factory = ProviderFactory(provider_name="gemini")
        assert factory.provider_name == "gemini"

    def test_factory_config_passed_to_provider(self) -> None:
        config = ProviderConfig(model_name="custom-model", temperature=0.1)
        factory = ProviderFactory(provider_name="mock", config=config)
        provider = factory.get_provider()
        assert provider.config.model_name == "custom-model"
        assert provider.config.temperature == 0.1

    def test_factory_caches_instance(self) -> None:
        factory = ProviderFactory(provider_name="mock")
        p1 = factory.get_provider()
        p2 = factory.get_provider()
        assert p1 is p2  # same instance

    def test_get_provider_function(self) -> None:
        # This uses the env default (mock), should not raise
        provider = get_provider()
        assert provider is not None


# ── GeminiProvider import ───────────────────────────────────────────────────


class TestGeminiProviderImport:
    def test_gemini_provider_importable(self) -> None:
        """Verify the Gemini module can be imported (no SDK required for import)."""
        from app.llm.providers.gemini import GeminiProvider

        assert GeminiProvider is not None

    def test_gemini_provider_instantiable(self) -> None:
        """Create instance without config — should not raise even without SDK."""
        from app.llm.providers.gemini import GeminiProvider

        provider = GeminiProvider()
        assert provider.provider_name == "gemini"
        assert provider.supports(ModelCapability.CHAT)
        assert not provider.supports(ModelCapability.EMBEDDING)  # Gemini doesn't support embedding

    def test_gemini_provider_config(self) -> None:
        from app.llm.providers.gemini import GeminiProvider

        config = ProviderConfig(model_name="gemini-2.5-flash", temperature=0.5)
        provider = GeminiProvider(config=config)
        assert provider.config.model_name == "gemini-2.5-flash"
        assert provider.config.temperature == 0.5
