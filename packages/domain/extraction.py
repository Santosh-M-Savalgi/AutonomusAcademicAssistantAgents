"""Versioned, page-traceable deterministic extraction contracts (no I/O)."""

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from packages.domain.models import DomainModel

SCHEMA_VERSION = "extraction-v1"
POLICY_VERSION = "syllabus-structure-v1"
DetectionMethod = Literal["keyword_number", "decimal_number", "syllabus_heading", "repeated_caps"]


class NodeType(StrEnum):
    MODULE = "MODULE"
    UNIT = "UNIT"
    CHAPTER = "CHAPTER"
    SECTION = "SECTION"
    TOPIC = "TOPIC"
    SUBTOPIC = "SUBTOPIC"


class WarningCode(StrEnum):
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    LOW_TEXT = "LOW_TEXT"
    AMBIGUOUS_HEADING = "AMBIGUOUS_HEADING"


class DocumentSource(DomainModel):
    course_id: UUID
    document_id: UUID
    version_id: UUID
    version_number: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    page_count: int = Field(ge=0)


class SourceReference(DomainModel):
    """One-based inclusive lines in the normalized page text, never PDF byte offsets."""

    page: int = Field(ge=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("Reversed source range")
        return self


class ExtractedPage(DomainModel):
    number: int = Field(ge=1)
    text: str
    status: Literal["TEXT", "OCR_CANDIDATE"]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if "\r" in self.text or (bool(self.text.strip()) != (self.status == "TEXT")):
            raise ValueError("Invalid normalized page status/text")
        return self


class ExtractionWarning(DomainModel):
    code: WarningCode
    page: int | None = Field(default=None, ge=1)
    source: SourceReference | None = None


class StructureNode(DomainModel):
    id: UUID
    type: NodeType
    title: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None
    order: int = Field(ge=1)
    source: SourceReference
    detection_method: DetectionMethod
    parse_confidence: float = Field(ge=0, le=1)


class ExtractionSummary(DomainModel):
    page_count: int = Field(ge=0)
    empty_page_count: int = Field(ge=0)
    total_characters: int = Field(ge=0)
    node_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    status: Literal["TEXT", "LOW_TEXT", "NO_TEXT"]


def node_id(source: DocumentSource, kind: NodeType, ref: SourceReference, title: str) -> UUID:
    return uuid5(source.version_id, f"{POLICY_VERSION}:{source.sha256}:{kind}:"
                 f"{ref.page}:{ref.line_start}:{ref.line_end}:{title}")


class ExtractionResult(DomainModel):
    schema_version: Literal["extraction-v1"] = "extraction-v1"
    policy_version: Literal["syllabus-structure-v1"] = "syllabus-structure-v1"
    source: DocumentSource
    minimum_useful_characters: int = Field(ge=0)
    pages: list[ExtractedPage]
    nodes: list[StructureNode]
    unclassified: list[SourceReference]
    warnings: list[ExtractionWarning]
    summary: ExtractionSummary

    @model_validator(mode="after")
    def validate_traceability(self) -> Self:
        if [p.number for p in self.pages] != list(range(1, len(self.pages) + 1)):
            raise ValueError("Pages must be complete and ordered")
        if self.source.page_count != len(self.pages):
            raise ValueError("Source page count mismatch")
        lines = {p.number: p.text.split("\n") for p in self.pages}
        covered: set[tuple[int, int]] = set()

        def check_ref(ref: SourceReference, *, cover: bool = False) -> None:
            if ref.page not in lines or ref.line_end > len(lines[ref.page]):
                raise ValueError("Source reference outside document")
            if cover:
                for line in range(ref.line_start, ref.line_end + 1):
                    key = (ref.page, line)
                    if key in covered:
                        raise ValueError("Overlapping content references")
                    covered.add(key)

        seen: dict[UUID, StructureNode] = {}
        ranks = {kind: rank for rank, kind in enumerate(NodeType)}
        previous = (0, 0)
        for order, node in enumerate(self.nodes, 1):
            check_ref(node.source, cover=True)
            location = (node.source.page, node.source.line_start)
            if node.id in seen or node.order != order or location <= previous:
                raise ValueError("Duplicate or unordered structure node")
            if node.id != node_id(self.source, node.type, node.source, node.title):
                raise ValueError("Non-deterministic node identifier")
            if node.title != " ".join(
                line.strip() for line in lines[node.source.page][
                    node.source.line_start - 1:node.source.line_end
                ]
            ):
                raise ValueError("Heading must match its source")
            if node.parent_id is not None:
                parent = seen.get(node.parent_id)
                if parent is None or ranks[parent.type] > ranks[node.type] or (
                    parent.type == node.type and node.type != NodeType.SUBTOPIC
                ):
                    raise ValueError("Invalid hierarchy parent")
            previous = location
            seen[node.id] = node
        previous = (0, 0)
        for ref in self.unclassified:
            check_ref(ref, cover=True)
            if (ref.page, ref.line_start) <= previous:
                raise ValueError("Unclassified references must be ordered")
            previous = (ref.page, ref.line_end)
        expected = {(p, n) for p, text in lines.items()
                    for n, line in enumerate(text, 1) if line.strip()}
        if not expected <= covered:
            raise ValueError("Unreferenced document text")
        for warning in self.warnings:
            if warning.page is not None and warning.page not in lines:
                raise ValueError("Invalid warning page")
            if warning.source:
                check_ref(warning.source)
                if warning.page != warning.source.page:
                    raise ValueError("Warning/source mismatch")
        characters = sum(len(p.text) for p in self.pages)
        useful = sum(sum(not c.isspace() for c in p.text) for p in self.pages)
        status: Literal["TEXT", "LOW_TEXT", "NO_TEXT"] = "NO_TEXT" if not useful else (
            "LOW_TEXT" if useful < self.minimum_useful_characters else "TEXT"
        )
        expected_summary = ExtractionSummary(
            page_count=len(self.pages), empty_page_count=sum(p.status == "OCR_CANDIDATE"
                                                           for p in self.pages),
            total_characters=characters, node_count=len(self.nodes),
            warning_count=len(self.warnings), status=status,
        )
        if self.summary != expected_summary:
            raise ValueError("Inconsistent extraction summary")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")

    def artifact_key(self) -> str:
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return (f"courses/{self.source.course_id}/documents/{self.source.document_id}/"
                f"extractions/{self.source.version_id}/{self.schema_version}/{digest}.json")
