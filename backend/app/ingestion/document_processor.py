"""Document ingestion pipeline (Sprint 4 Phase A).

Supports:
- Syllabus documents (structured topic lists)
- Markdown
- Plain text
- PDF (via pypdf)

Responsibilities:
- Parsing: extract structured content from each format
- Normalization: unify whitespace, line endings, encoding
- Metadata extraction: title, headings, word count, content hash
- Document version tracking: content-hash based change detection
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class DocumentMetadata:
    """Metadata extracted from a source document."""

    title: str
    source_type: str  # "syllabus" | "markdown" | "plain_text" | "pdf"
    word_count: int
    char_count: int
    content_hash: str  # SHA-256 of normalized content
    headings: list[str] = field(default_factory=list)
    file_name: str = ""
    topics: list[str] = field(default_factory=list)
    extracted_at: str = ""


@dataclass
class Document:
    """A fully processed document ready for chunking."""

    id: str
    metadata: DocumentMetadata
    content: str
    sections: list[Section] = field(default_factory=list)


@dataclass
class Section:
    """A hierarchical section within a document."""

    id: str
    heading: str
    level: int  # 1 = h1, 2 = h2, etc.
    content: str
    parent_id: str | None = None  # UUID of parent section, if any


# ── Content hash helpers ────────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Normalize whitespace, line endings, and encoding."""
    # Replace all line endings with \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse multiple blank lines to one
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines)


def _compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of normalized content."""
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ── Document parsers ────────────────────────────────────────────────────────


class DocumentParser(Protocol):
    """Protocol for document parsers."""

    def parse(self, content: str, file_name: str) -> Document:
        """Parse raw content into a Document with sections."""
        ...


class PlainTextParser:
    """Parse plain text content."""

    def parse(self, content: str, file_name: str = "") -> Document:
        normalized = _normalize_text(content)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        word_count = len(normalized.split())
        char_count = len(normalized)

        # Extract headings (lines starting with # or ===/--- underlined)
        headings = _extract_headings(normalized)

        # Build sections
        sections = _build_sections_from_headings(normalized)

        doc_id = str(uuid.uuid4())
        metadata = DocumentMetadata(
            title=file_name.replace(".txt", "").replace("_", " ").title() if file_name else "Untitled",
            source_type="plain_text",
            word_count=word_count,
            char_count=char_count,
            content_hash=content_hash,
            headings=headings,
            file_name=file_name,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )
        return Document(
            id=doc_id,
            metadata=metadata,
            content=normalized,
            sections=sections,
        )


class MarkdownParser:
    """Parse Markdown content with section hierarchy."""

    def parse(self, content: str, file_name: str = "") -> Document:
        normalized = _normalize_text(content)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        word_count = len(normalized.split())
        char_count = len(normalized)

        headings = _extract_markdown_headings(normalized)
        sections = _build_markdown_sections(normalized)

        # Determine title from first h1 or file name
        title = ""
        for heading, level in headings:
            if level == 1:
                title = heading
                break
        if not title:
            title = file_name.replace(".md", "").replace("_", " ").title() if file_name else "Untitled"

        doc_id = str(uuid.uuid4())
        metadata = DocumentMetadata(
            title=title,
            source_type="markdown",
            word_count=word_count,
            char_count=char_count,
            content_hash=content_hash,
            headings=[h for h, _ in headings],
            file_name=file_name,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )
        return Document(
            id=doc_id,
            metadata=metadata,
            content=normalized,
            sections=sections,
        )


class SyllabusParser:
    """Parse syllabus-format documents (topic lists with descriptions)."""

    def parse(self, content: str, file_name: str = "") -> Document:
        normalized = _normalize_text(content)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        word_count = len(normalized.split())
        char_count = len(normalized)

        # Extract topics (lines starting with - or * or numbered)
        topics = _extract_syllabus_topics(normalized)

        doc_id = str(uuid.uuid4())
        metadata = DocumentMetadata(
            title=file_name.replace(".txt", "").replace(".md", "").replace("_", " ").title()
            if file_name else "Syllabus",
            source_type="syllabus",
            word_count=word_count,
            char_count=char_count,
            content_hash=content_hash,
            headings=[],
            file_name=file_name,
            topics=topics,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )
        return Document(
            id=doc_id,
            metadata=metadata,
            content=normalized,
        )


class PDFParser:
    """Parse PDF content using pypdf."""

    def parse(self, file_path: str, file_name: str = "") -> Document:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        content_parts: list[str] = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                content_parts.append(text)

        raw_content = "\n\n".join(content_parts)
        normalized = _normalize_text(raw_content)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        word_count = len(normalized.split())
        char_count = len(normalized)

        # Try to extract title from metadata or first page
        title = ""
        if reader.metadata and reader.metadata.title:
            title = reader.metadata.title
        if not title:
            title = file_name.replace(".pdf", "").replace("_", " ").title() if file_name else "Untitled"

        headings = _extract_headings(normalized)
        sections = _build_sections_from_headings(normalized)

        doc_id = str(uuid.uuid4())
        metadata = DocumentMetadata(
            title=title,
            source_type="pdf",
            word_count=word_count,
            char_count=char_count,
            content_hash=content_hash,
            headings=headings,
            file_name=file_name,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )
        return Document(
            id=doc_id,
            metadata=metadata,
            content=normalized,
            sections=sections,
        )


# ── Extraction helpers ──────────────────────────────────────────────────────


def _extract_headings(text: str) -> list[str]:
    """Extract heading-like lines from plain text (lines ending with === or ---)."""
    headings: list[str] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Check next line for underline heading markers
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and all(c in "=-~" for c in next_line) and len(next_line) >= 3:
                    headings.append(stripped)
    return headings


def _extract_markdown_headings(text: str) -> list[tuple[str, int]]:
    """Extract Markdown headings with their levels."""
    headings: list[tuple[str, int]] = []
    for line in text.split("\n"):
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            headings.append((heading_text, level))
    return headings


def _build_markdown_sections(text: str) -> list[Section]:
    """Build hierarchical sections from Markdown content."""
    sections: list[Section] = []
    lines = text.split("\n")

    current_section: Section | None = None
    section_stack: list[Section] = []

    content_buffer: list[str] = []

    def flush_buffer() -> str:
        result = "\n".join(content_buffer).strip()
        content_buffer.clear()
        return result

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            # Flush previous section content
            prev_content = flush_buffer()

            if current_section and prev_content:
                current_section.content = prev_content

            level = len(match.group(1))
            heading_text = match.group(2).strip()

            section = Section(
                id=str(uuid.uuid4()),
                heading=heading_text,
                level=level,
                content="",
                parent_id=None,
            )

            # Find parent: last section with lower level
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()

            if section_stack:
                section.parent_id = section_stack[-1].id

            sections.append(section)
            current_section = section
            section_stack.append(section)
        else:
            content_buffer.append(line)

    # Flush final section content
    final_content = flush_buffer()
    if current_section and final_content:
        current_section.content = final_content

    return sections


def _build_sections_from_headings(text: str) -> list[Section]:
    """Build sections from plain-text headings (underlined ===/---)."""
    sections: list[Section] = []
    lines = text.split("\n")
    current_section: Section | None = None
    content_buffer: list[str] = []

    def flush_buffer() -> str:
        result = "\n".join(content_buffer).strip()
        content_buffer.clear()
        return result

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if next_stripped and all(c in "=-~" for c in next_stripped) and len(next_stripped) >= 3:
                # This is a heading
                if current_section:
                    current_section.content = flush_buffer()
                heading_text = stripped
                level = 1 if next_stripped and next_stripped[0] == "=" else 2
                current_section = Section(
                    id=str(uuid.uuid4()),
                    heading=heading_text,
                    level=level,
                    content="",
                )
                sections.append(current_section)
                i += 2
                continue

        if current_section:
            content_buffer.append(lines[i])
        i += 1

    if current_section:
        current_section.content = flush_buffer()

    return sections


def _extract_syllabus_topics(text: str) -> list[str]:
    """Extract topic names from syllabus text."""
    topics: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Match list items (-, *, or numbered)
        match = re.match(r"^[\-\*\d+\.\s]+(.+)$", stripped)
        if match:
            topic = match.group(1).strip()
            if topic:
                topics.append(topic)
    return topics


# ── Document version tracking ────────────────────────────────────────────────


class DocumentVersionTracker:
    """Track document versions using content hashes.

    Documents are considered the same version if their normalized content
    hash matches. This avoids re-processing unchanged documents.
    """

    def __init__(self) -> None:
        self._known_hashes: dict[str, str] = {}  # doc_id -> content_hash

    def has_changed(self, doc_id: str, content: str) -> bool:
        """Check if a document's content has changed since last seen."""
        current_hash = _compute_content_hash(content)
        known_hash = self._known_hashes.get(doc_id)
        return known_hash != current_hash

    def register_version(self, doc_id: str, content: str) -> str:
        """Register a new version and return the content hash."""
        content_hash = _compute_content_hash(content)
        self._known_hashes[doc_id] = content_hash
        return content_hash

    def get_known_hash(self, doc_id: str) -> str | None:
        """Get the last known hash for a document ID."""
        return self._known_hashes.get(doc_id)


# ── DocumentProcessor (public API) ────────────────────────────────────────────


class DocumentProcessor:
    """High-level document ingestion pipeline.

    Usage::

        processor = DocumentProcessor()
        doc = processor.process("path/to/file.pdf")
        # or
        doc = processor.process_text("# My Heading\\n\\nContent here", source_type="markdown")
    """

    def __init__(self, version_tracker: DocumentVersionTracker | None = None):
        self.version_tracker = version_tracker or DocumentVersionTracker()
        self._parsers: dict[str, DocumentParser] = {
            "plain_text": PlainTextParser(),
            "markdown": MarkdownParser(),
            "syllabus": SyllabusParser(),
            "pdf": PDFParser(),
        }

    def register_parser(self, source_type: str, parser: DocumentParser) -> None:
        """Register a custom parser for a source type."""
        self._parsers[source_type] = parser

    def process(
        self,
        file_path: str,
        source_type: str | None = None,
        file_name: str | None = None,
    ) -> Document:
        """Process a file and return a Document.

        Args:
            file_path: Path to the file on disk.
            source_type: Override source type detection (e.g., "pdf").
                If None, inferred from extension.
            file_name: Optional file name for metadata.

        Returns:
            A processed Document ready for chunking.
        """
        import os

        if file_name is None:
            file_name = os.path.basename(file_path)

        # Infer source type from extension
        ext = os.path.splitext(file_path)[1].lower()
        inferred_type = source_type or {
            ".pdf": "pdf",
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "plain_text",
        }.get(ext, "plain_text")

        parser = self._parsers.get(inferred_type)
        if parser is None:
            msg = f"No parser registered for source type: {inferred_type}"
            raise ValueError(msg)

        # Read file
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # For text-based formats, decode
        if inferred_type != "pdf":
            text = raw_bytes.decode("utf-8", errors="replace")

        # Parse
        if inferred_type == "pdf":
            doc = parser.parse(file_path, file_name=file_name)  # type: ignore[arg-type]
        else:
            doc = parser.parse(text, file_name=file_name)  # type: ignore[arg-type]

        # Version tracking
        if self.version_tracker:
            self.version_tracker.register_version(doc.id, doc.content)

        return doc

    def process_text(
        self,
        text: str,
        source_type: str = "plain_text",
        file_name: str = "",
    ) -> Document:
        """Process raw text content directly.

        Args:
            text: The text content to process.
            source_type: One of "plain_text", "markdown", or "syllabus".
            file_name: Optional file name for metadata.

        Returns:
            A processed Document ready for chunking.
        """
        parser = self._parsers.get(source_type)
        if parser is None:
            msg = f"No parser registered for source type: {source_type}"
            raise ValueError(msg)

        # PDF parsing requires a file path, not raw text
        if source_type == "pdf":
            msg = "Use process() with a file path for PDF documents"
            raise ValueError(msg)

        doc = parser.parse(text, file_name=file_name)

        # Version tracking
        if self.version_tracker:
            self.version_tracker.register_version(doc.id, doc.content)

        return doc
