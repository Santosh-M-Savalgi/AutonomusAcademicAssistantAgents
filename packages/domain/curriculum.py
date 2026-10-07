"""Versioned draft and untrusted provider contracts; no provider or persistence imports."""

import hashlib
import json
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from packages.domain.extraction import DocumentSource, NodeType, SourceReference, StructureNode
from packages.domain.models import DomainModel, VersionStamp

DRAFT_POLICY = "curriculum-draft-v1"


def draft_identity(extraction_id: UUID, reference: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"aaa:draft:{DRAFT_POLICY}:{extraction_id}:{reference}")


def element_id(draft_id: UUID, source_id: UUID, key: str = "extracted") -> UUID:
    return uuid5(draft_id, f"{source_id}:{key}")


class SourcePassage(DomainModel):
    source: SourceReference
    text: str


class GenerationInput(DomainModel):
    draft_id: UUID
    sections: list[StructureNode]
    passages: list[SourcePassage]


class GeneratedElement(DomainModel):
    id: UUID
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    type: Literal["TOPIC", "SUBTOPIC"]
    title: str = Field(min_length=1, max_length=160)
    parent_id: UUID
    source_node_id: UUID
    sources: list[SourceReference] = Field(min_length=1, max_length=32)


class GenerationOutput(DomainModel):
    schema_version: Literal["curriculum-unit-v1"]
    elements: list[GeneratedElement] = Field(max_length=64)


class CurriculumElement(DomainModel):
    id: UUID
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    type: NodeType
    title: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None
    order: int = Field(ge=1)
    source_node_id: UUID | None = None
    sources: list[SourceReference] = Field(default_factory=list)
    origin: Literal["EXTRACTED", "GENERATED", "HUMAN"]
    parse_confidence: float = Field(default=0, ge=0, le=1)
    description: str | None = Field(default=None, max_length=4000)
    learning_outcomes: list[str] = Field(default_factory=list, max_length=32)


class CurriculumDraft(DomainModel):
    schema_version: Literal["curriculum-draft-v1"] = "curriculum-draft-v1"
    id: UUID
    status: Literal["DRAFT"] = "DRAFT"
    source: DocumentSource
    extraction_job_id: UUID
    extraction_ref: str = Field(max_length=512)
    versions: VersionStamp
    elements: list[CurriculumElement]
    unclassified: list[SourceReference]
    warnings: list[Literal["LOW_TEXT", "EMPTY_PAGES", "UNCLASSIFIED_CONTENT",
                           "NO_STRUCTURE", "MISSING_TOPICS"]]
    completeness: Literal["COMPLETE", "INCOMPLETE"]

    @model_validator(mode="after")
    def validate_hierarchy(self) -> Self:
        seen: dict[UUID, CurriculumElement] = {}
        rank = {kind: i for i, kind in enumerate(NodeType)}
        for order, node in enumerate(self.elements, 1):
            if node.id in seen or node.order != order or not node.title.strip():
                raise ValueError("Duplicate, empty or unordered curriculum element")
            if node.source_node_id is None and node.origin != "HUMAN":
                raise ValueError("Source-derived element requires a source node")
            if node.source_node_id is not None and (
                node.id != element_id(self.id, node.source_node_id, node.key)
            ):
                raise ValueError("Unstable curriculum identifier")
            if node.parent_id is not None:
                parent = seen.get(node.parent_id)
                if parent is None or rank[parent.type] > rank[node.type] or (
                    parent.type == node.type and node.type != NodeType.SUBTOPIC
                ):
                    raise ValueError("Invalid curriculum hierarchy")
            if any(ref.page > self.source.page_count for ref in node.sources):
                raise ValueError("Invalid curriculum source page")
            seen[node.id] = node
        if len(set(self.warnings)) != len(self.warnings) or self.completeness != (
            "INCOMPLETE" if self.warnings else "COMPLETE"
        ):
            raise ValueError("Inconsistent draft completeness")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode()

    def artifact_key(self) -> str:
        digest = hashlib.sha256(self.canonical_bytes()).hexdigest()
        return (f"courses/{self.source.course_id}/documents/{self.source.document_id}/"
                f"drafts/{self.source.version_id}/{self.schema_version}/{self.id}/{digest}.json")


class DraftJobPayload(DomainModel):
    course_id: UUID
    document_id: UUID
    document_version_id: UUID
    extraction_job_id: UUID
    policy: Literal["curriculum-draft-v1"] = "curriculum-draft-v1"
