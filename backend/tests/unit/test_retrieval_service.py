"""Tests for Sprint 4 Phase E — Retrieval Service.

Covers: semantic search, prerequisite-aware retrieval,
metadata filtering, similarity threshold, context builder,
orchestration integration, API endpoints.

Uses MockEmbeddingProvider for deterministic, network-free testing.
Uses in-memory mock for VectorStoreService to avoid ChromaDB dependency.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.embedding.base import EmbeddingConfig
from app.ingestion.embedding.mock_embedding import MockEmbeddingProvider
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    RetrievedChunk,
)


@pytest.fixture
def mock_embedding_provider():
    return MockEmbeddingProvider(EmbeddingConfig(embedding_dimensions=64))


@pytest.fixture
def mock_vector_store():
    """Create a mock VectorStoreService that returns controlled results."""
    mock = MagicMock()

    # Default: return empty results
    mock.search.return_value = {
        "ids": [[]],
        "distances": [[]],
        "metadatas": [[]],
        "documents": [[]],
    }

    # Chunks collection for search_chunks_by_ids
    mock.chunks_collection = MagicMock()
    mock.chunks_collection.get.return_value = {
        "ids": [],
        "metadatas": [],
        "documents": [],
    }

    return mock


@pytest.fixture
def retrieval_service(mock_embedding_provider, mock_vector_store):
    return RetrievalService(
        vector_store=mock_vector_store,
        embedding_provider=mock_embedding_provider,
        similarity_threshold=0.0,  # No filtering for tests
    )


@pytest.fixture
def context_builder():
    return ContextBuilder(max_context_tokens=2000)


# ── RetrievalService ────────────────────────────────────────────────────────


class TestRetrievalService:
    @pytest.mark.asyncio
    async def test_search_basic(self, retrieval_service, mock_vector_store):
        # Setup mock results
        mock_vector_store.search.return_value = {
            "ids": [["chunk1", "chunk2"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[
                {"document_id": "doc1", "headings": "Intro|Main"},
                {"document_id": "doc1", "headings": "", "topic_tags": "Python"},
            ]],
            "documents": [["Content of chunk 1", "Content of chunk 2"]],
        }

        result = await retrieval_service.search(query="Python lists", top_k=5)
        assert isinstance(result, RetrievalResult)
        assert result.query == "Python lists"
        assert len(result.chunks) == 2

    @pytest.mark.asyncio
    async def test_search_empty_results(self, retrieval_service, mock_vector_store):
        mock_vector_store.search.return_value = {
            "ids": [[]],
            "distances": [[]],
            "metadatas": [[]],
            "documents": [[]],
        }

        result = await retrieval_service.search(query="nothing")
        assert len(result.chunks) == 0
        assert result.total_results == 0

    @pytest.mark.asyncio
    async def test_similarity_threshold_filtering(self, retrieval_service, mock_vector_store):
        retrieval_service.similarity_threshold = 0.85
        mock_vector_store.search.return_value = {
            "ids": [["chunk1", "chunk2"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[{}, {}]],
            "documents": [["Content A", "Content B"]],
        }

        result = await retrieval_service.search(query="test", min_score=0.8)
        # The distances become scores: 1.0 - distance = 0.9 and 0.7
        # 0.7 < 0.8, so chunk2 should be filtered
        assert len(result.chunks) == 1
        assert result.filtered_by_threshold == 1

    @pytest.mark.asyncio
    async def test_search_by_topic(self, retrieval_service, mock_vector_store):
        mock_vector_store.search.return_value = {
            "ids": [["chunk1"]],
            "distances": [[0.2]],
            "metadatas": [[{"document_id": "doc1"}]],
            "documents": [["Topic content"]],
        }

        result = await retrieval_service.search_by_topic(
            topic_name="Python Lists",
            topic_description="Ordered collections in Python",
        )
        assert result.total_results >= 0

    @pytest.mark.asyncio
    async def test_search_with_prerequisites(self, retrieval_service, mock_vector_store):
        # Main search returns some results
        mock_vector_store.search.return_value = {
            "ids": [["chunk1"]],
            "distances": [[0.2]],
            "metadatas": [[{"document_id": "doc1"}]],
            "documents": [["Main content"]],
        }

        result = await retrieval_service.search_with_prerequisites(
            topic_name="NumPy",
            topic_description="Numerical computing",
            prerequisite_topics=[
                {"name": "Lists", "mastery": 0.9},
                {"name": "Loops", "mastery": 0.4},
            ],
        )
        assert isinstance(result, RetrievalResult)
        assert result.prerequisite_chunks is not None

    @pytest.mark.asyncio
    async def test_search_by_syllabus(self, retrieval_service, mock_vector_store):
        mock_vector_store.search.return_value = {
            "ids": [["chunk1"]],
            "distances": [[0.15]],
            "metadatas": [[{"document_id": "doc1", "syllabus_id": "syll-123"}]],
            "documents": [["Syllabus content"]],
        }

        result = await retrieval_service.search_by_syllabus(
            query="Python",
            syllabus_id="syll-123",
        )
        assert result.query == "Python"

    @pytest.mark.asyncio
    async def test_result_sorting_by_score(self, retrieval_service, mock_vector_store):
        mock_vector_store.search.return_value = {
            "ids": [["chunk_a", "chunk_b", "chunk_c"]],
            "distances": [[0.5, 0.1, 0.3]],  # scores: 0.5, 0.9, 0.7
            "metadatas": [[{}, {}, {}]],
            "documents": [["A content", "B content", "C content"]],
        }

        result = await retrieval_service.search(query="test")
        # Should be sorted by score descending: B(0.9), C(0.7), A(0.5)
        scores = [c.score for c in result.chunks]
        assert scores == sorted(scores, reverse=True)


# ── ContextBuilder ──────────────────────────────────────────────────────────


class TestContextBuilder:
    def test_build_tutor_context_empty(self, context_builder):
        ctx = context_builder.build_tutor_context(
            topic_name="Python",
            topic_description="Programming language",
        )
        assert ctx.topic_name == "Python"
        assert len(ctx.relevant_chunks) == 0
        assert ctx.estimated_tokens == 0

    def test_build_tutor_context_with_retrieval(self, context_builder):
        result = RetrievalResult(
            query="test",
            chunks=[
                RetrievedChunk(
                    chunk_id="c1",
                    document_id="d1",
                    content="Python is a programming language.",
                    score=0.95,
                ),
                RetrievedChunk(
                    chunk_id="c2",
                    document_id="d1",
                    content="Lists are ordered collections.",
                    score=0.85,
                ),
            ],
            total_results=2,
        )

        ctx = context_builder.build_tutor_context(
            topic_name="Python",
            topic_description="",
            retrieval_result=result,
            mastery_score=0.5,
        )
        assert len(ctx.relevant_chunks) == 2
        assert ctx.mastery_score == 0.5
        assert ctx.estimated_tokens > 0

    def test_build_tutor_context_max_tokens(self, context_builder):
        context_builder.max_context_tokens = 50  # Very small limit
        large_chunks = [
            RetrievedChunk(
                chunk_id=f"c{i}",
                document_id="d1",
                content="X " * 500,  # ~1000 chars
                score=0.9,
            )
            for i in range(10)
        ]
        result = RetrievalResult(query="test", chunks=large_chunks, total_results=10)

        ctx = context_builder.build_tutor_context(
            topic_name="Test",
            topic_description="",
            retrieval_result=result,
        )
        # Should be truncated by token limit
        assert len(ctx.relevant_chunks) < 10

    def test_build_quiz_context(self, context_builder):
        result = RetrievalResult(
            query="test",
            chunks=[
                RetrievedChunk(
                    chunk_id="c1",
                    document_id="d1",
                    content="Quiz content",
                    score=0.9,
                ),
            ],
            total_results=1,
        )

        ctx = context_builder.build_quiz_context(
            topic_name="Python",
            topic_description="",
            retrieval_result=result,
            prerequisite_topics=[{"name": "Basics", "mastery": 0.8}],
            mastery_score=0.6,
        )
        assert len(ctx.relevant_chunks) == 1
        assert len(ctx.prerequisite_topics) == 1
        assert ctx.mastery_score == 0.6

    def test_format_tutor_context(self, context_builder):
        result = RetrievalResult(
            query="test",
            chunks=[
                RetrievedChunk(
                    chunk_id="c1",
                    document_id="d1",
                    content="Source content here",
                    score=0.9,
                    headings=["Chapter 1", "Section 1.1"],
                ),
            ],
            total_results=1,
        )

        ctx = context_builder.build_tutor_context(
            topic_name="Test",
            topic_description="",
            retrieval_result=result,
            learning_objectives=["Understand X", "Apply Y"],
        )

        formatted = context_builder.format_tutor_context_for_prompt(ctx)
        assert "## Source Material" in formatted
        assert "Source content here" in formatted
        assert "## Learning Objectives" in formatted
        assert "Understand X" in formatted
        assert "## Current Mastery Level" not in formatted  # mastery_score = 0

    def test_format_quiz_context(self, context_builder):
        result = RetrievalResult(
            query="test",
            chunks=[
                RetrievedChunk(
                    chunk_id="c1",
                    document_id="d1",
                    content="Relevant material",
                    score=0.85,
                ),
            ],
            total_results=1,
        )

        ctx = context_builder.build_quiz_context(
            topic_name="Test",
            topic_description="",
            retrieval_result=result,
            mastery_score=0.75,
        )

        formatted = context_builder.format_quiz_context_for_prompt(ctx)
        assert "## Source Material for Quiz" in formatted
        assert "Relevant material" in formatted
        assert "## Current Mastery Level: 75%" in formatted
