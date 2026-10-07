"""Explicit successor-lineage contract tests."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain.successor import LineageKind, SuccessorLineage
from packages.persistence.successors import successor_identity


def test_unchanged_lineage_requires_the_same_single_identity() -> None:
    element_id = uuid4()
    lineage = SuccessorLineage(
        kind=LineageKind.UNCHANGED,
        parent_element_ids=[element_id],
        successor_element_ids=[element_id],
    )
    assert lineage.kind == LineageKind.UNCHANGED


@pytest.mark.parametrize(
    "kind,parent_count,successor_count",
    [
        (LineageKind.REPLACED, 1, 1),
        (LineageKind.MERGED, 2, 1),
        (LineageKind.SPLIT, 1, 2),
    ],
)
def test_nontrivial_lineage_shapes_are_explicit(
    kind: LineageKind, parent_count: int, successor_count: int,
) -> None:
    parents = [uuid4() for _ in range(parent_count)]
    successors = [uuid4() for _ in range(successor_count)]
    lineage = SuccessorLineage(
        kind=kind,
        parent_element_ids=parents,
        successor_element_ids=successors,
    )
    assert lineage.parent_element_ids == parents
    assert lineage.successor_element_ids == successors


@pytest.mark.parametrize(
    "kind,parent_count,successor_count",
    [
        (LineageKind.REPLACED, 2, 1),
        (LineageKind.MERGED, 1, 1),
        (LineageKind.MERGED, 1, 2),
        (LineageKind.SPLIT, 2, 1),
        (LineageKind.SPLIT, 1, 1),
    ],
)
def test_invalid_lineage_shapes_are_rejected(
    kind: LineageKind, parent_count: int, successor_count: int,
) -> None:
    with pytest.raises(ValidationError):
        SuccessorLineage(
            kind=kind,
            parent_element_ids=[uuid4() for _ in range(parent_count)],
            successor_element_ids=[uuid4() for _ in range(successor_count)],
        )


def test_lineage_cannot_repeat_an_element_identity() -> None:
    element_id = uuid4()
    with pytest.raises(ValidationError, match="must be unique"):
        SuccessorLineage(
            kind=LineageKind.MERGED,
            parent_element_ids=[element_id, element_id],
            successor_element_ids=[uuid4()],
        )


def test_successor_identity_changes_when_successor_revision_changes() -> None:
    parent = uuid4()
    review = uuid4()
    first_revision = uuid4()
    second_revision = uuid4()
    assert successor_identity(parent, review, first_revision) != successor_identity(
        parent, review, second_revision,
    )
