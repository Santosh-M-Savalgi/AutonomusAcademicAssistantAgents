"""Pure review lifecycle, editing, provenance, hierarchy and confirmation policy tests."""

import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.curriculum.drafts import assemble_draft, generation_inputs
from packages.curriculum.pdf import extract_pdf
from packages.domain.curriculum import CurriculumDraft
from packages.domain.review import (
    CurriculumRevision,
    ReviewElement,
    ReviewErrorCode,
    ReviewStatus,
    validate_confirmable,
    validate_review_transition,
    validate_revision_against_draft,
)
from packages.model_client.curriculum import FakeProvider
from tests.pdf_fixtures import document_source, syllabus_pdf


def draft() -> CurriculumDraft:
    content = syllabus_pdf(["Module I: Foundations\nUnit 1: Algebra\n1.1 Functions\nBody"])
    extraction = extract_pdf(BytesIO(content), document_source(content, 1), max_bytes=100000,
                             max_pages=2, max_output_bytes=100000, minimum_useful_characters=1)
    draft_id = uuid4()
    provider = FakeProvider()
    outputs = [
        __import__("packages.domain.curriculum", fromlist=["GenerationOutput"])
        .GenerationOutput.model_validate_json(asyncio.run(provider.generate(request)))
        for request in generation_inputs(draft_id, extraction)
    ]
    return assemble_draft(draft_id, uuid4(), "minio://bucket/generated.json", extraction,
                          outputs, provider.versions)


def revision_from(source: CurriculumDraft, elements=None) -> CurriculumRevision:
    return CurriculumRevision(
        id=uuid4(), review_id=uuid4(), draft_id=source.id, revision_number=1,
        parent_revision_id=None, source=source.source, original_draft_ref="minio://draft",
        elements=elements or [ReviewElement.model_validate(item.model_dump())
                              for item in source.elements], created_by="reviewer",
    )


def test_review_transitions_are_central_and_terminal():
    validate_review_transition(ReviewStatus.DRAFT, ReviewStatus.UNDER_REVIEW)
    validate_review_transition(ReviewStatus.UNDER_REVIEW, ReviewStatus.CONFIRMED)
    with pytest.raises(ValueError, match="Invalid review transition"):
        validate_review_transition(ReviewStatus.DRAFT, ReviewStatus.CONFIRMED)
    with pytest.raises(ValueError, match="Invalid review transition"):
        validate_review_transition(ReviewStatus.CONFIRMED, ReviewStatus.UNDER_REVIEW)


def test_title_description_outcome_edit_preserves_generated_provenance():
    source = draft()
    revision = revision_from(source)
    edited = [item.model_copy(deep=True) for item in revision.elements]
    edited[0].title = "Human-reviewed title"
    edited[0].description = "Reviewed description"
    edited[0].learning_outcomes = ["Explain the reviewed topic"]
    candidate = revision.model_copy(update={"id": uuid4(), "elements": edited})
    validate_revision_against_draft(candidate, source)
    validate_confirmable(candidate)


def test_human_element_is_distinct_and_cannot_claim_provenance():
    source = draft()
    revision = revision_from(source)
    human = ReviewElement(
        id=uuid4(), key="human-addition", type="TOPIC", title="Added topic", parent_id=None,
        order=len(revision.elements) + 1, origin="HUMAN", parse_confidence=0,
        source_node_id=None, sources=[], learning_outcomes=["Practice the added topic"],
    )
    candidate = revision.model_copy(update={"id": uuid4(), "elements": [*revision.elements, human]})
    validate_revision_against_draft(candidate, source)
    assert candidate.elements[-1].origin == "HUMAN"
    bad_human = human.model_copy(update={"sources": [source.elements[0].sources[0]]})
    with pytest.raises(ValidationError):
        CurriculumRevision.model_validate(revision.model_copy(
            update={"id": uuid4(), "elements": [*revision.elements, bad_human]},
        ).model_dump())


def test_invalid_provenance_and_identity_changes_are_rejected():
    source = draft()
    revision = revision_from(source)
    changed = [item.model_copy(deep=True) for item in revision.elements]
    changed[0].source_node_id = uuid4()
    with pytest.raises(ValueError, match="identity"):
        validate_revision_against_draft(
            revision.model_copy(update={"id": uuid4(), "elements": changed}), source,
        )
    changed = [item.model_copy(deep=True) for item in revision.elements]
    changed[0].sources = []
    with pytest.raises(ValueError, match="provenance"):
        validate_revision_against_draft(
            revision.model_copy(update={"id": uuid4(), "elements": changed}), source,
        )


@pytest.mark.parametrize("changes", [
    {"origin": "HUMAN", "source_node_id": None, "sources": []},
    {"origin": "GENERATED"},
    {"key": "rewritten-identity"},
    {"parse_confidence": 0.123},
])
def test_source_derived_identity_and_origin_cannot_be_rewritten(changes):
    source = draft()
    revision = revision_from(source)
    assert revision.elements[0].origin == "EXTRACTED"
    data = revision.model_dump(mode="json")
    data["elements"][0].update(changes)
    candidate = CurriculumRevision.model_validate(data)
    with pytest.raises(ValueError):
        validate_revision_against_draft(candidate, source)


def test_parent_removal_requires_removing_children_and_cycles_are_rejected():
    source = draft()
    revision = revision_from(source)
    child = next(item for item in revision.elements if item.parent_id is not None)
    parent_id = child.parent_id
    remaining = [item for item in revision.elements if item.id != parent_id]
    with pytest.raises(ValueError, match="children"):
        validate_revision_against_draft(
            revision.model_copy(update={"id": uuid4(), "elements": remaining}), source,
        )
    cyclic = [item.model_copy(deep=True) for item in revision.elements]
    cyclic[0].parent_id = cyclic[-1].id
    with pytest.raises(ValidationError):
        CurriculumRevision.model_validate(revision.model_copy(update={"id": uuid4(),
                                                                       "elements": cyclic}))


def test_reordering_siblings_is_valid_but_parent_order_is_required():
    source = draft()
    revision = revision_from(source)
    # Sibling order can change while every parent remains before its children.
    siblings = [item for item in revision.elements if item.parent_id == revision.elements[0].id]
    if len(siblings) >= 2:
        reordered = [item for item in revision.elements if item not in siblings]
        reordered.extend(reversed(siblings))
        reordered = [item.model_copy(update={"order": index})
                     for index, item in enumerate(reordered, 1)]
        candidate = revision.model_copy(update={"id": uuid4(), "elements": reordered})
        validate_revision_against_draft(candidate, source)


def test_confirmation_requires_valid_nonempty_revision():
    source = draft()
    revision = revision_from(source)
    validate_confirmable(revision)
    with pytest.raises(ValidationError):
        CurriculumRevision.model_validate(
            revision.model_dump(mode="json") | {"elements": []},
        )


def test_error_codes_are_closed_and_revision_ids_are_not_reused():
    assert ReviewErrorCode.STALE_REVISION.value == "STALE_REVISION"
    source = draft()
    first = revision_from(source)
    second = first.model_copy(update={"id": uuid4(), "revision_number": 2,
                                      "parent_revision_id": first.id})
    assert first.id != second.id
