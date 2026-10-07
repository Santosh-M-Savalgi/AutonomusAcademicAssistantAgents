"""Explicit curriculum successor-version and element-lineage contracts."""

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from packages.domain.models import DomainModel


class LineageKind(StrEnum):
    UNCHANGED = "UNCHANGED"
    REPLACED = "REPLACED"
    MERGED = "MERGED"
    SPLIT = "SPLIT"


class SuccessorLineage(DomainModel):
    kind: LineageKind
    parent_element_ids: list[UUID] = Field(min_length=1, max_length=32)
    successor_element_ids: list[UUID] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_shape(self) -> "SuccessorLineage":
        if (
            len(set(self.parent_element_ids)) != len(self.parent_element_ids)
            or len(set(self.successor_element_ids)) != len(self.successor_element_ids)
        ):
            raise ValueError("Lineage element identities must be unique")
        if self.kind == LineageKind.UNCHANGED and (
            len(self.parent_element_ids) != 1
            or len(self.successor_element_ids) != 1
            or self.parent_element_ids[0] != self.successor_element_ids[0]
        ):
            raise ValueError("UNCHANGED lineage requires one identical element identity")
        if self.kind == LineageKind.REPLACED and (
            len(self.parent_element_ids) != 1
            or len(self.successor_element_ids) != 1
            or self.parent_element_ids[0] == self.successor_element_ids[0]
        ):
            raise ValueError("REPLACED lineage requires one different successor element")
        if self.kind == LineageKind.MERGED and (
            len(self.parent_element_ids) < 2 or len(self.successor_element_ids) != 1
        ):
            raise ValueError("MERGED lineage requires multiple parents and one successor")
        if self.kind == LineageKind.SPLIT and (
            len(self.parent_element_ids) != 1 or len(self.successor_element_ids) < 2
        ):
            raise ValueError("SPLIT lineage requires one parent and multiple successors")
        return self


class CurriculumSuccessorRequest(DomainModel):
    successor_draft_id: UUID
    lineage: list[SuccessorLineage] = Field(min_length=1, max_length=512)


class CurriculumSuccessorRecord(DomainModel):
    id: UUID
    course_id: UUID
    parent_review_id: UUID
    parent_revision_id: UUID
    successor_review_id: UUID
    successor_revision_id: UUID | None
    status: str
    created_by_identity_id: UUID
    lineage: list[SuccessorLineage]
