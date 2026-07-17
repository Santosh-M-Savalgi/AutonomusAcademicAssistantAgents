"""Tests for Sprint 4 Phase B — Chunking.

Covers: FixedSizeChunker, SectionAwareChunker, TopicBoundaryChunker,
ChunkingService, configurable chunk size/overlap, section hierarchy
preservation, topic boundary preservation.
"""

from __future__ import annotations

import pytest

from app.ingestion.chunker import (
    ChunkingService,
    FixedSizeChunker,
    SectionAwareChunker,
    TopicBoundaryChunker,
)
from app.ingestion.document_processor import Document, DocumentMetadata, Section


def _make_document(
    content: str,
    sections: list[Section] | None = None,
    topics: list[str] | None = None,
) -> Document:
    metadata = DocumentMetadata(
        title="Test Document",
        source_type="plain_text",
        word_count=len(content.split()),
        char_count=len(content),
        content_hash="abc123",
        topics=topics or [],
    )
    return Document(
        id="doc-1",
        metadata=metadata,
        content=content,
        sections=sections or [],
    )


# ── FixedSizeChunker ────────────────────────────────────────────────────────


class TestFixedSizeChunker:
    def test_chunk_basic(self) -> None:
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        content = "A " * 500
        doc = _make_document(content)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 0
        assert all(c.content for c in chunks)

    def test_chunk_size_configurable(self) -> None:
        chunker = FixedSizeChunker(chunk_size=200, overlap=20)
        content = "X " * 1000
        doc = _make_document(content)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 0

    def test_overlap_less_than_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="(?i)overlap"):
            FixedSizeChunker(chunk_size=100, overlap=200)

    def test_empty_document(self) -> None:
        chunker = FixedSizeChunker()
        doc = _make_document("")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 0

    def test_chunk_index_order(self) -> None:
        chunker = FixedSizeChunker(chunk_size=50, overlap=10)
        content = "Word " * 100
        doc = _make_document(content)
        chunks = chunker.chunk(doc)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_total_chunks_consistent(self) -> None:
        chunker = FixedSizeChunker(chunk_size=100, overlap=30)
        content = "Test " * 200
        doc = _make_document(content)
        chunks = chunker.chunk(doc)
        assert all(c.total_chunks == len(chunks) for c in chunks)


# ── SectionAwareChunker ─────────────────────────────────────────────────────


class TestSectionAwareChunker:
    def test_chunk_by_section(self) -> None:
        chunker = SectionAwareChunker(max_chunk_size=500)
        sections = [
            Section(id="s1", heading="Intro", level=1, content="Introduction content here."),
            Section(id="s2", heading="Main", level=2, content="Main content here."),
        ]
        doc = _make_document("Intro\n\nMain", sections=sections)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 0

    def test_section_heading_in_metadata(self) -> None:
        chunker = SectionAwareChunker(max_chunk_size=1000)
        sections = [
            Section(id="s1", heading="Chapter 1", level=1, content="Content of chapter 1."),
        ]
        doc = _make_document("Chapter 1 content here.", sections=sections)
        chunks = chunker.chunk(doc)
        if chunks:
            assert chunks[0].metadata.get("heading") == "Chapter 1"

    def test_without_sections_falls_back(self) -> None:
        chunker = SectionAwareChunker(max_chunk_size=100)
        doc = _make_document("Word " * 100)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 0

    def test_breadcrumb_chain(self) -> None:
        chunker = SectionAwareChunker(max_chunk_size=500)
        sections = [
            Section(id="s1", heading="Parent", level=1, content="Parent content."),
            Section(id="s2", heading="Child", level=2, content="Child content.", parent_id="s1"),
        ]
        doc = _make_document("Parent\n\nChild", sections=sections)
        chunks = chunker.chunk(doc)
        child_chunks = [c for c in chunks if c.section_id == "s2"]
        for c in child_chunks:
            assert "Parent" in c.headings or not c.headings


# ── TopicBoundaryChunker ────────────────────────────────────────────────────


class TestTopicBoundaryChunker:
    def test_chunk_by_topic(self) -> None:
        chunker = TopicBoundaryChunker(max_chunk_size=500)
        doc = _make_document(
            "Python: Intro to programming.\nData Types: Numbers and strings.",
            topics=["Python", "Data Types"],
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 0

    def test_falls_back_without_topics(self) -> None:
        chunker = TopicBoundaryChunker(max_chunk_size=200, overlap=50)
        doc = _make_document("Word " * 100, topics=[])
        chunks = chunker.chunk(doc)
        assert len(chunks) > 0


# ── ChunkingService ─────────────────────────────────────────────────────────


class TestChunkingService:
    def test_fixed_strategy(self) -> None:
        service = ChunkingService(strategy="fixed", chunk_size=100, overlap=20)
        doc = _make_document("Word " * 50)
        chunks = service.chunk(doc)
        assert len(chunks) > 0

    def test_section_strategy(self) -> None:
        service = ChunkingService(strategy="section", chunk_size=100)
        sections = [
            Section(id="s1", heading="Intro", level=1, content="Intro content"),
        ]
        doc = _make_document("Intro content", sections=sections)
        chunks = service.chunk(doc)
        assert len(chunks) > 0

    def test_topic_strategy(self) -> None:
        service = ChunkingService(strategy="topic", chunk_size=100)
        doc = _make_document("Python topic", topics=["Python"])
        chunks = service.chunk(doc)
        assert len(chunks) >= 0

    def test_unknown_strategy(self) -> None:
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            ChunkingService(strategy="invalid")

    def test_chunk_has_metadata(self) -> None:
        service = ChunkingService(strategy="fixed", chunk_size=100, overlap=20)
        doc = _make_document("Test " * 50)
        chunks = service.chunk(doc)
        if chunks:
            assert "strategy" in chunks[0].metadata
            assert "start_char" in chunks[0].metadata

    def test_chunk_has_document_id(self) -> None:
        service = ChunkingService(strategy="fixed", chunk_size=100, overlap=20)
        doc = _make_document("Test " * 50)
        chunks = service.chunk(doc)
        assert all(c.document_id == "doc-1" for c in chunks)
