"""Pure curriculum review lifecycle, revision validation and confirmation policy."""

from enum import StrEnum
from typing import Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from packages.domain.curriculum import CurriculumDraft, CurriculumElement
from packages.domain.extraction import DocumentSource, NodeType
from packages.domain.models import DomainModel


class ReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"


class ReviewErrorCode(StrEnum):
    REVIEW_NOT_FOUND = "REVIEW_NOT_FOUND"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    STALE_REVISION = "STALE_REVISION"
    CONFIRMED_IMMUTABLE = "CONFIRMED_IMMUTABLE"
    INVALID_REVISION = "INVALID_REVISION"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
    UNAUTHORIZED = "UNAUTHORIZED"


def review_identity(draft_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"aaa:curriculum-review:{draft_id}")


def validate_review_transition(source: ReviewStatus, target: ReviewStatus) -> None:
    allowed = {
        ReviewStatus.DRAFT: {ReviewStatus.UNDER_REVIEW},
        ReviewStatus.UNDER_REVIEW: {ReviewStatus.CONFIRMED},
        ReviewStatus.CONFIRMED: set(),
    }
    if target not in allowed[source]:
        raise ValueError(f"Invalid review transition: {source} -> {target}")


class ReviewElement(CurriculumElement):
    """A review element; HUMAN elements have no fabricated source provenance."""


class CurriculumRevision(DomainModel):
    schema_version: str = "curriculum-review-v1"
    id: UUID
    review_id: UUID
    draft_id: UUID
    revision_number: int = Field(ge=1)
    parent_revision_id: UUID | None
    source: DocumentSource
    original_draft_ref: str = Field(max_length=512)
    elements: list[ReviewElement] = Field(min_length=1, max_length=512)
    created_by: str = Field(min_length=1, max_length=255)

    def canonical_bytes(self) -> bytes:
        import json

        return json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode()

    @model_validator(mode="after")
    def ordered_hierarchy(self) -> Self:
        seen: set[UUID] = set()
        ranks = {kind: rank for rank, kind in enumerate(NodeType)}
        for order, element in enumerate(self.elements, 1):
            if element.order != order or element.id in seen:
                raise ValueError("Revision elements must have unique stable ordering")
            if element.parent_id is not None:
                if element.parent_id not in seen:
                    raise ValueError("Revision parent must precede its child")
                parent = next(item for item in self.elements if item.id == element.parent_id)
                if ranks[parent.type] > ranks[element.type] or (
                    parent.type == element.type and element.type != NodeType.SUBTOPIC
                ):
                    raise ValueError("Invalid revision hierarchy")
            for source in element.sources:
                if source.page > self.source.page_count:
                    raise ValueError("Revision source page is outside the source document")
            if element.origin == "HUMAN" and (
                element.source_node_id is not None or element.sources
            ):
                raise ValueError("Human elements cannot claim source provenance")
            if element.origin != "HUMAN" and element.source_node_id is None:
                raise ValueError("Generated/extracted elements require a source node")
            seen.add(element.id)
        return self


class ReviewRecord(DomainModel):
    id: UUID
    course_id: UUID
    document_id: UUID
    document_version_id: UUID
    draft_id: UUID
    original_draft_ref: str = Field(max_length=512)
    status: ReviewStatus
    current_revision_id: UUID
    revision_number: int = Field(ge=1)
    confirmed_revision_id: UUID | None
    created_by: str
    updated_by: str
    confirmed_by: str | None


def validate_revision_against_draft(
    revision: CurriculumRevision, draft: CurriculumDraft,
) -> None:
    if revision.source != draft.source or revision.draft_id != draft.id:
        raise ValueError("Revision source/draft association mismatch")
    original = {element.id: element for element in draft.elements}
    for element in revision.elements:
        if element.origin == "HUMAN":
            if element.id in original:
                raise ValueError("Generated/extracted identity changed")
            continue
        source = original.get(element.id)
        if source is None or element.source_node_id != source.source_node_id:
            raise ValueError("Generated/extracted element identity changed")
        if (element.key != source.key or element.origin != source.origin
                or element.parse_confidence != source.parse_confidence):
            raise ValueError("Generated/extracted identity changed")
        if element.type != source.type or element.sources != source.sources:
            raise ValueError("Generated/extracted provenance changed")
    for source in draft.elements:
        if source.id in {element.id for element in revision.elements}:
            continue
        if any(element.parent_id == source.id for element in revision.elements):
            raise ValueError("Removed element still has children")


def validate_confirmable(revision: CurriculumRevision) -> None:
    if not revision.elements:
        raise ValueError("A curriculum must contain at least one element")
    for element in revision.elements:
        if not element.title.strip():
            raise ValueError("Every curriculum element requires a title")
        if element.origin != "HUMAN" and not element.sources:
            raise ValueError("Every source-derived element requires provenance")
