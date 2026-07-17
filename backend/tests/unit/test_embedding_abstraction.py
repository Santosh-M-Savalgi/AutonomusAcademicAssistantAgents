"""Tests for Sprint 4 Phase C — Embedding Abstraction.

Covers: EmbeddingProvider interface, MockEmbeddingProvider,
EmbeddingFactory, embedding dimensions, deterministic embeddings,
batch embedding.
"""

from __future__ import annotations

import pytest

from app.ingestion.embedding.base import (
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingResult,
)
from app.ingestion.embedding.mock_embedding import MockEmbeddingProvider
from app.ingestion.embedding_factory import EmbeddingFactory


# ── EmbeddingProvider interface ─────────────────────────────────────────────


class TestEmbeddingProviderInterface:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            EmbeddingProvider()  # type: ignore[abstract]

    def test_embedding_config_defaults(self) -> None:
        config = EmbeddingConfig()
        assert config.model_name == "text-embedding-004"
        assert config.embedding_dimensions == 768
        assert config.batch_size == 100


# ── MockEmbeddingProvider ───────────────────────────────────────────────────


class TestMockEmbeddingProvider:
    @pytest.mark.asyncio
    async def test_embed_text(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed_text("Hello, world!")
        assert isinstance(result, EmbeddingResult)
        assert len(result.embedding) == 768
        assert result.dimensions == 768

    @pytest.mark.asyncio
    async def test_embed_text_different_dimensions(self) -> None:
        config = EmbeddingConfig(embedding_dimensions=128)
        provider = MockEmbeddingProvider(config)
        result = await provider.embed_text("Test")
        assert len(result.embedding) == 128
        assert result.dimensions == 128

    @pytest.mark.asyncio
    async def test_deterministic_output(self) -> None:
        provider = MockEmbeddingProvider()
        result1 = await provider.embed_text("Consistent text")
        result2 = await provider.embed_text("Consistent text")
        assert result1.embedding == result2.embedding

    @pytest.mark.asyncio
    async def test_different_text_different_embedding(self) -> None:
        provider = MockEmbeddingProvider()
        result1 = await provider.embed_text("Hello")
        result2 = await provider.embed_text("World")
        assert result1.embedding != result2.embedding

    @pytest.mark.asyncio
    async def test_embedding_normalized(self) -> None:
        provider = MockEmbeddingProvider()
        result = await provider.embed_text("Normalized test")
        magnitude = sum(v * v for v in result.embedding) ** 0.5
        assert 0.99 < magnitude < 1.01  # Unit vector

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        provider = MockEmbeddingProvider()
        texts = ["Hello", "World", "Test"]
        results = await provider.embed_batch(texts)
        assert len(results) == 3
        for r in results:
            assert len(r.embedding) == 768

    @pytest.mark.asyncio
    async def test_call_count(self) -> None:
        provider = MockEmbeddingProvider()
        assert provider.call_count == 0
        await provider.embed_text("A")
        await provider.embed_text("B")
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_call_history(self) -> None:
        provider = MockEmbeddingProvider()
        await provider.embed_text("First")
        await provider.embed_text("Second")
        assert provider.call_history == ["First", "Second"]

    @pytest.mark.asyncio
    async def test_reset(self) -> None:
        provider = MockEmbeddingProvider()
        await provider.embed_text("X")
        assert provider.call_count == 1
        provider.reset()
        assert provider.call_count == 0
        assert provider.call_history == []

    @pytest.mark.asyncio
    async def test_provider_name(self) -> None:
        provider = MockEmbeddingProvider()
        assert provider.provider_name == "mock"

    @pytest.mark.asyncio
    async def test_embedding_dimensions_property(self) -> None:
        provider = MockEmbeddingProvider()
        assert provider.embedding_dimensions == 768


# ── EmbeddingFactory ────────────────────────────────────────────────────────


class TestEmbeddingFactory:
    def test_create_mock_provider(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        provider = factory.get_embedding_provider()
        assert provider.provider_name == "mock"

    def test_unknown_provider(self) -> None:
        factory = EmbeddingFactory(provider_name="unknown")
        with pytest.raises(EmbeddingError, match="Unknown embedding provider"):
            factory.get_embedding_provider()

    def test_provider_caching(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        p1 = factory.get_embedding_provider()
        p2 = factory.get_embedding_provider()
        assert p1 is p2

    def test_set_provider(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        factory.set_provider("mock")
        provider = factory.get_embedding_provider()
        assert provider.provider_name == "mock"

    def test_set_provider_unknown(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        with pytest.raises(EmbeddingError, match="Unknown embedding provider"):
            factory.set_provider("nonexistent")

    def test_register_custom_provider(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        factory.register_provider("custom", MockEmbeddingProvider)
        factory.set_provider("custom")
        provider = factory.get_embedding_provider()
        assert provider.provider_name == "mock"

    def test_from_settings_default(self) -> None:
        factory = EmbeddingFactory.from_settings()
        assert factory.provider_name == "mock"

    def test_provider_name_property(self) -> None:
        factory = EmbeddingFactory(provider_name="mock")
        assert factory.provider_name == "mock"
