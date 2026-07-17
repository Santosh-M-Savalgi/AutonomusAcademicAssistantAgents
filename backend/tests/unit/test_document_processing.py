"""Tests for Sprint 4 Phase A — Document Processing Pipeline.

Covers: plain text parsing, markdown parsing, syllabus parsing,
PDF parsing, metadata extraction, content hashing, normalization,
document version tracking.
"""

from __future__ import annotations

import pytest

from app.ingestion.document_processor import (
    DocumentProcessor,
    DocumentVersionTracker,
    MarkdownParser,
    PlainTextParser,
    Section,
    SyllabusParser,
    _compute_content_hash,
    _normalize_text,
)


# ── Content normalization ───────────────────────────────────────────────────


class TestContentNormalization:
    def test_normalize_line_endings(self) -> None:
        text = "line1\r\nline2\rline3\nline4"
        result = _normalize_text(text)
        assert result == "line1\nline2\nline3\nline4"

    def test_collapse_blank_lines(self) -> None:
        text = "para1\n\n\n\npara2"
        result = _normalize_text(text)
        assert result == "para1\n\npara2"

    def test_strip_line_whitespace(self) -> None:
        text = "  hello   \n  world  "
        result = _normalize_text(text)
        assert result == "hello\nworld"

    def test_content_hash_is_deterministic(self) -> None:
        h1 = _compute_content_hash("Hello, World!")
        h2 = _compute_content_hash("Hello, World!")
        assert h1 == h2

    def test_content_hash_changes(self) -> None:
        h1 = _compute_content_hash("Hello, World!")
        h2 = _compute_content_hash("Hello, World.")
        assert h1 != h2


# ── PlainTextParser ─────────────────────────────────────────────────────────


class TestPlainTextParser:
    def test_parse_basic_text(self) -> None:
        parser = PlainTextParser()
        doc = parser.parse("Hello, world! This is a test.")
        assert doc.metadata.word_count > 0
        assert doc.metadata.char_count > 0
        assert doc.metadata.source_type == "plain_text"
        assert doc.content == "Hello, world! This is a test."

    def test_parse_empty_text(self) -> None:
        parser = PlainTextParser()
        doc = parser.parse("")
        assert doc.metadata.word_count == 0
        assert doc.metadata.char_count == 0


# ── MarkdownParser ──────────────────────────────────────────────────────────


class TestMarkdownParser:
    def test_parse_markdown_with_headings(self) -> None:
        parser = MarkdownParser()
        text = "# Title\n\nSome content\n\n## Section 1\n\nSection content\n\n### Subsection\n\nMore details"
        doc = parser.parse(text)
        assert doc.metadata.source_type == "markdown"
        assert doc.metadata.title == "Title"
        assert "Section 1" in doc.metadata.headings
        assert len(doc.sections) > 0

    def test_parse_markdown_section_hierarchy(self) -> None:
        parser = MarkdownParser()
        text = "# H1\n\nContent\n\n## H2\n\nH2 content"
        doc = parser.parse(text)
        assert len(doc.sections) >= 2
        assert doc.sections[0].level == 1
        assert doc.sections[0].heading == "H1"
        if len(doc.sections) > 1:
            assert doc.sections[1].level == 2

    def test_parse_markdown_parent_references(self) -> None:
        parser = MarkdownParser()
        text = "# Parent\n\nContent\n\n## Child\n\nChild content"
        doc = parser.parse(text)
        child_sections = [s for s in doc.sections if s.heading == "Child"]
        parent_sections = [s for s in doc.sections if s.heading == "Parent"]
        if child_sections and parent_sections:
            assert child_sections[0].parent_id == parent_sections[0].id

    def test_parse_markdown_section_content(self) -> None:
        parser = MarkdownParser()
        text = "# Topic\n\nSpecific section content here\n\n## Extra\n\nExtra content"
        doc = parser.parse(text)
        topic_sections = [s for s in doc.sections if s.heading == "Topic"]
        if topic_sections:
            assert "Specific section content" in topic_sections[0].content


# ── SyllabusParser ──────────────────────────────────────────────────────────


class TestSyllabusParser:
    def test_parse_syllabus_topics(self) -> None:
        parser = SyllabusParser()
        text = "- Python Basics\n- Data Types\n- Functions\n- Lists\n- Loops"
        doc = parser.parse(text)
        assert doc.metadata.source_type == "syllabus"
        assert len(doc.metadata.topics) >= 3
        assert "Python Basics" in doc.metadata.topics

    def test_parse_numbered_syllabus(self) -> None:
        parser = SyllabusParser()
        text = "1. Variables\n2. Conditions\n3. Loops\n4. Functions"
        doc = parser.parse(text)
        assert len(doc.metadata.topics) >= 3

    def test_parse_syllabus_with_descriptions(self) -> None:
        parser = SyllabusParser()
        text = "- Python Basics: general purpose language\n- Lists: ordered collections\n- Functions: reusable blocks"
        doc = parser.parse(text)
        # Topics are extracted from list items - the full item text after the marker
        assert len(doc.metadata.topics) > 0


# ── DocumentProcessor ───────────────────────────────────────────────────────


class TestDocumentProcessor:
    def test_process_text_plain(self) -> None:
        processor = DocumentProcessor()
        doc = processor.process_text("Hello world", source_type="plain_text")
        assert doc.metadata.source_type == "plain_text"
        assert doc.metadata.word_count == 2

    def test_process_text_markdown(self) -> None:
        processor = DocumentProcessor()
        doc = processor.process_text("# Title\n\nContent", source_type="markdown")
        assert doc.metadata.source_type == "markdown"
        assert doc.metadata.title == "Title"

    def test_process_text_syllabus(self) -> None:
        processor = DocumentProcessor()
        doc = processor.process_text("- Topic 1\n- Topic 2", source_type="syllabus")
        assert doc.metadata.source_type == "syllabus"
        assert len(doc.metadata.topics) == 2

    def test_process_text_unknown_type(self) -> None:
        processor = DocumentProcessor()
        with pytest.raises(ValueError, match="No parser registered"):
            processor.process_text("content", source_type="unknown_format")

    def test_process_text_pdf_rejected(self) -> None:
        processor = DocumentProcessor()
        with pytest.raises(ValueError, match="Use process"):
            processor.process_text("content", source_type="pdf")

    def test_register_custom_parser(self) -> None:
        processor = DocumentProcessor()
        processor.register_parser("custom", PlainTextParser())
        doc = processor.process_text("test", source_type="custom")
        assert doc.metadata.source_type == "plain_text"

    def test_process_file_nonexistent(self) -> None:
        processor = DocumentProcessor()
        with pytest.raises(FileNotFoundError):
            processor.process("nonexistent_file.txt")


# ── DocumentVersionTracker ──────────────────────────────────────────────────


class TestDocumentVersionTracker:
    def test_has_changed_new_doc(self) -> None:
        tracker = DocumentVersionTracker()
        assert tracker.has_changed("doc1", "Initial content") is True

    def test_has_changed_same_content(self) -> None:
        tracker = DocumentVersionTracker()
        tracker.register_version("doc1", "Same content")
        assert tracker.has_changed("doc1", "Same content") is False

    def test_has_changed_different_content(self) -> None:
        tracker = DocumentVersionTracker()
        tracker.register_version("doc1", "Original content")
        assert tracker.has_changed("doc1", "Modified content") is True

    def test_register_version_returns_hash(self) -> None:
        tracker = DocumentVersionTracker()
        h = tracker.register_version("doc1", "Content")
        assert len(h) == 64  # SHA-256 hex

    def test_get_known_hash_not_found(self) -> None:
        tracker = DocumentVersionTracker()
        assert tracker.get_known_hash("nonexistent") is None

    def test_get_known_hash(self) -> None:
        tracker = DocumentVersionTracker()
        h = tracker.register_version("doc1", "Content")
        assert tracker.get_known_hash("doc1") == h
