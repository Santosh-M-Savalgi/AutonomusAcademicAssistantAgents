"""Reusable document chunking (Sprint 4 Phase B).

Provides configurable chunking strategies:
- Fixed-size with configurable overlap
- Section-aware (preserves heading hierarchy)
- Topic-boundary aware (respects topic boundaries from syllabus documents)

All chunking produces ``Chunk`` objects with consistent metadata,
making them suitable for embedding and indexing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.ingestion.document_processor import Document, Section


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    """A single chunk of text ready for embedding."""

    id: str
    document_id: str
    content: str
    chunk_index: int
    total_chunks: int
    metadata: dict = field(default_factory=dict)
    # Section hierarchy preserved in metadata
    headings: list[str] = field(default_factory=list)  # breadcrumb of headings
    section_id: str | None = None
    topic_tags: list[str] = field(default_factory=list)


# ── Chunking strategies ─────────────────────────────────────────────────────


class ChunkingStrategy(Protocol):
    """Protocol for chunking strategies."""

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """Split a Document into a list of Chunks."""
        ...


class FixedSizeChunker:
    """Fixed-size chunking with configurable overlap.

    Splits document content into chunks of approximately ``chunk_size``
    characters with ``overlap`` characters between consecutive chunks.
    Chunk boundaries seek paragraph breaks to avoid splitting mid-sentence.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 200):
        if overlap >= chunk_size:
            msg = f"Overlap ({overlap}) must be less than chunk_size ({chunk_size})"
            raise ValueError(msg)
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.stride = chunk_size - overlap

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """Split document content into fixed-size chunks."""
        text = document.content
        if not text:
            return []

        chunks: list[Chunk] = []
        start = 0
        total_len = len(text)
        chunk_index = 0

        if total_len == 0:
            return []

        while start < total_len:
            end = min(start + self.chunk_size, total_len)

            # If not at the end, try to find a good break point
            if end < total_len:
                end = self._find_break_point(text, end, direction="backward")

            content = text[start:end].strip()
            if content:
                chunk = Chunk(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    content=content,
                    chunk_index=chunk_index,
                    total_chunks=0,  # set after we know all chunks
                    metadata={
                        "start_char": start,
                        "end_char": end,
                        "chunk_size": len(content),
                        "strategy": "fixed_size",
                    },
                    headings=self._get_headings_for_position(document, start),
                    topic_tags=document.metadata.topics.copy(),
                )
                chunks.append(chunk)
                chunk_index += 1

            start += self.stride
            if start < 0:
                break

        # Update total_chunks
        for c in chunks:
            c.total_chunks = len(chunks)

        return chunks

    def _find_break_point(self, text: str, position: int, direction: str = "backward") -> int:
        """Find a good break point near position.

        Prefers: paragraph break > sentence break > word break > exact position.
        """
        search_range = min(100, position)

        if direction == "backward":
            chunk_start = max(0, position - search_range)
            segment = text[chunk_start:position]

            # Try paragraph break (double newline)
            para_break = segment.rfind("\n\n")
            if para_break != -1:
                return chunk_start + para_break + 2

            # Try newline
            newline_break = segment.rfind("\n")
            if newline_break != -1:
                return chunk_start + newline_break + 1

            # Try sentence break
            for sep in [". ", "! ", "? "]:
                idx = segment.rfind(sep)
                if idx != -1:
                    return chunk_start + idx + 1

            return position

        return position

    def _get_headings_for_position(self, document: Document, position: int) -> list[str]:
        """Get the heading breadcrumb for a given character position."""
        headings: list[str] = []
        for section in document.sections:
            # Rough estimation: check if position falls within section
            section_pos = document.content.find(section.content)
            if section_pos != -1 and section_pos <= position:
                headings.append(section.heading)
        return headings


class SectionAwareChunker:
    """Chunk by section boundaries, preserving hierarchy.

    Each section becomes a chunk (or multiple if the section is large).
    Headings are preserved as breadcrumbs in chunk metadata.
    """

    def __init__(self, max_chunk_size: int = 1500, min_chunk_size: int = 50):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self._fixed_chunker = FixedSizeChunker(
            chunk_size=max_chunk_size,
            overlap=50,
        )

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """Split document by section boundaries, preserving hierarchy."""
        if not document.sections:
            # Fall back to fixed-size chunking for documents without sections
            return self._fixed_chunker.chunk(document)

        chunks: list[Chunk] = []
        chunk_index = 0

        for section in document.sections:
            section_content = section.content.strip()
            if not section_content:
                continue

            # Build heading breadcrumb
            breadcrumb = self._build_breadcrumb(document.sections, section)

            # If section is small enough, keep as one chunk
            if len(section_content) <= self.max_chunk_size:
                if len(section_content) >= self.min_chunk_size or not chunks:
                    chunk = Chunk(
                        id=str(uuid.uuid4()),
                        document_id=document.id,
                        content=section_content,
                        chunk_index=chunk_index,
                        total_chunks=0,
                        metadata={
                            "section_id": section.id,
                            "heading": section.heading,
                            "level": section.level,
                            "strategy": "section_aware",
                        },
                        headings=breadcrumb,
                        section_id=section.id,
                        topic_tags=document.metadata.topics.copy(),
                    )
                    chunks.append(chunk)
                    chunk_index += 1
            else:
                # Split large section using fixed-size chunker
                # Create a sub-document for just this section
                section_doc = Document(
                    id=document.id,
                    metadata=document.metadata,
                    content=section_content,
                )
                sub_chunks = self._fixed_chunker.chunk(section_doc)
                for sc in sub_chunks:
                    sc.chunk_index = chunk_index
                    sc.headings = breadcrumb + sc.headings
                    sc.section_id = section.id
                    sc.metadata["strategy"] = "section_aware"
                    sc.metadata["section_id"] = section.id
                    sc.metadata["heading"] = section.heading
                    sc.metadata["level"] = section.level
                    chunks.append(sc)
                    chunk_index += 1

        # Update total_chunks
        for c in chunks:
            c.total_chunks = len(chunks)

        return chunks

    def _build_breadcrumb(self, sections: list[Section], target: Section) -> list[str]:
        """Build heading breadcrumb by following parent chain."""
        breadcrumb: list[str] = []
        seen = {target.id}
        current = target

        while current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            parent = next((s for s in sections if s.id == current.parent_id), None)
            if parent:
                breadcrumb.insert(0, parent.heading)
                current = parent
            else:
                break

        breadcrumb.append(target.heading)
        return breadcrumb


class TopicBoundaryChunker:
    """Chunk by topic boundaries extracted from syllabus documents.

    This chunker identifies topic transitions in syllabus content
    and creates chunks that don't cross topic boundaries.
    """

    def __init__(self, max_chunk_size: int = 1500, overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.overlap = min(overlap, max_chunk_size - 1) if max_chunk_size > 1 else 0
        self._fixed_chunker = FixedSizeChunker(
            chunk_size=max_chunk_size,
            overlap=self.overlap,
        )

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """Split document by topic boundaries."""
        if not document.metadata.topics:
            # Fall back to section-aware chunking
            section_chunker = SectionAwareChunker(max_chunk_size=self.max_chunk_size)
            return section_chunker.chunk(document)

        chunks: list[Chunk] = []
        chunk_index = 0

        # For topic-based documents, identify sections by topic
        content = document.content
        topic_pattern = self._build_topic_pattern(document.metadata.topics)

        if not topic_pattern:
            # Fall back to section-aware
            section_chunker = SectionAwareChunker(max_chunk_size=self.max_chunk_size)
            return section_chunker.chunk(document)

        # Split content by topic boundaries
        topic_sections = re.split(topic_pattern, content, flags=re.IGNORECASE | re.MULTILINE)

        # Pair topic names with their content
        current_topic = ""
        for i, segment in enumerate(topic_sections):
            segment = segment.strip()
            if not segment:
                continue

            # Check if segment is a topic header
            is_topic = segment.lower() in {t.lower() for t in document.metadata.topics}

            if is_topic:
                current_topic = segment
            elif current_topic:
                # This is content belonging to the previous topic
                doc = Document(
                    id=document.id,
                    metadata=document.metadata,
                    content=segment,
                )
                sub_chunks = self._fixed_chunker.chunk(doc)
                for sc in sub_chunks:
                    sc.chunk_index = chunk_index
                    sc.topic_tags = [current_topic] + sc.topic_tags
                    sc.metadata["strategy"] = "topic_boundary"
                    sc.metadata["topic"] = current_topic
                    chunks.append(sc)
                    chunk_index += 1
            else:
                # Content before any topic header
                doc = Document(
                    id=document.id,
                    metadata=document.metadata,
                    content=segment,
                )
                sub_chunks = self._fixed_chunker.chunk(doc)
                for sc in sub_chunks:
                    sc.chunk_index = chunk_index
                    sc.metadata["strategy"] = "topic_boundary"
                    chunks.append(sc)
                    chunk_index += 1

        # Update total_chunks
        for c in chunks:
            c.total_chunks = len(chunks)

        return chunks

    def _build_topic_pattern(self, topics: list[str]) -> str | None:
        """Build a regex pattern from topic names."""
        if not topics:
            return None
        escaped = [re.escape(t) for t in topics]
        # Sort by length descending to match longer names first
        escaped.sort(key=len, reverse=True)
        return "\\b(?:" + "|".join(escaped) + ")\\b"


# ── ChunkingService (public API) ────────────────────────────────────────────


class ChunkingService:
    """Configurable document chunking service.

    Usage::

        service = ChunkingService(strategy="section", max_chunk_size=1000)
        chunks = service.chunk(document)
    """

    STRATEGIES = {
        "fixed": FixedSizeChunker,
        "section": SectionAwareChunker,
        "topic": TopicBoundaryChunker,
    }

    def __init__(
        self,
        strategy: str = "section",
        chunk_size: int = 1000,
        overlap: int = 200,
    ):
        if strategy not in self.STRATEGIES:
            msg = f"Unknown chunking strategy '{strategy}'. Choose from: {list(self.STRATEGIES)}"
            raise ValueError(msg)

        self.strategy_name = strategy
        strategy_cls = self.STRATEGIES[strategy]

        if strategy == "fixed":
            actual_overlap = min(overlap, chunk_size - 1) if chunk_size > 1 else 0
            self._chunker = strategy_cls(chunk_size=chunk_size, overlap=actual_overlap)
        elif strategy == "section":
            self._chunker = strategy_cls(max_chunk_size=chunk_size)
        elif strategy == "topic":
            actual_overlap = min(overlap, chunk_size - 1) if chunk_size > 1 else 0
            self._chunker = strategy_cls(max_chunk_size=chunk_size, overlap=actual_overlap)

    def chunk(self, document: Document, **kwargs) -> list[Chunk]:
        """Chunk a document using the configured strategy.

        Args:
            document: The processed Document to chunk.

        Returns:
            A list of Chunk objects ready for embedding.
        """
        return self._chunker.chunk(document, **kwargs)
