"""Provider, draft contracts, provenance and deterministic assembly tests."""

import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.curriculum.config import DraftSettings
from packages.curriculum.drafts import (
    assemble_draft,
    generation_inputs,
    validate_draft_source,
    validate_provider_output,
)
from packages.curriculum.pdf import extract_pdf
from packages.domain.curriculum import (
    CurriculumDraft,
    GenerationOutput,
)
from packages.model_client.curriculum import FakeProvider, ProviderError
from tests.pdf_fixtures import document_source, syllabus_pdf


def extraction(text: str = "Module I: Basics\nUnit 1: Algebra\n1.1 Functions\nBody"):
    content = syllabus_pdf([text, "", "Module II: Applications\n2.1 Methods"])
    return extract_pdf(BytesIO(content), document_source(content, 3), max_bytes=100000,
                       max_pages=5, max_output_bytes=100000, minimum_useful_characters=1)


async def provider_outputs(draft_id, result):
    provider = FakeProvider()
    outputs = [GenerationOutput.model_validate_json(await provider.generate(request))
               for request in generation_inputs(draft_id, result)]
    return provider, outputs


def test_fake_provider_is_deterministic_and_does_not_invent_source_ranges():
    result = extraction()
    draft_id = uuid4()
    requests = generation_inputs(draft_id, result)
    first = asyncio.run(FakeProvider().generate(requests[0]))
    second = asyncio.run(FakeProvider().generate(requests[0]))
    assert first == second
    output = GenerationOutput.model_validate_json(first)
    assert output.schema_version == "curriculum-unit-v1"
    assert all(element.sources[0] in [section.source for section in requests[0].sections]
               for element in output.elements)


def test_generation_input_partitions_roots_and_preserves_unclassified_content():
    result = extraction()
    groups = generation_inputs(uuid4(), result)
    assert len(groups) == 2
    assert sum(len(group.sections) for group in groups) == len(result.nodes)
    assert sum(len(group.passages) for group in groups) == len(result.nodes)
    assert result.unclassified


def test_valid_draft_is_explicitly_unconfirmed_and_source_traceable():
    result = extraction()
    draft_id = uuid4()
    provider, outputs = asyncio.run(provider_outputs(draft_id, result))
    draft = assemble_draft(draft_id, uuid4(), "minio://aaa/extraction.json", result, outputs,
                           provider.versions)
    assert draft.status == "DRAFT"
    assert draft.schema_version == "curriculum-draft-v1"
    assert draft.elements
    assert all(node.sources for node in draft.elements)
    assert all(node.origin in {"EXTRACTED", "GENERATED"} for node in draft.elements)
    validate_draft_source(draft, result)
    assert CurriculumDraft.model_validate_json(draft.canonical_bytes()) == draft
    assert draft.canonical_bytes() == draft.model_copy().canonical_bytes()


@pytest.mark.parametrize("mutation", ["duplicate", "bad_parent", "bad_source", "bad_page",
                                      "bad_id", "empty_title"])
def test_provider_output_validation_rejects_untrusted_structure(mutation):
    result = extraction()
    draft_id = uuid4()
    request = generation_inputs(draft_id, result)[0]
    provider = FakeProvider()
    output = GenerationOutput.model_validate_json(asyncio.run(provider.generate(request)))
    assert output.elements
    data = output.model_dump()
    if mutation == "duplicate":
        data["elements"].append(data["elements"][0])
    elif mutation == "bad_parent":
        data["elements"][0]["parent_id"] = uuid4()
    elif mutation == "bad_source":
        data["elements"][0]["source_node_id"] = uuid4()
    elif mutation == "bad_page":
        data["elements"][0]["sources"][0]["page"] = 99
    elif mutation == "bad_id":
        data["elements"][0]["id"] = uuid4()
    else:
        data["elements"][0]["title"] = ""
    with pytest.raises((ValidationError, ValueError)):
        validate_provider_output(
            request, GenerationOutput.model_validate(data).model_dump_json().encode(),
        )


def test_missing_provider_section_is_invalid_and_empty_input_is_incomplete():
    result = extraction()
    draft_id = uuid4()
    provider, outputs = asyncio.run(provider_outputs(draft_id, result))
    with pytest.raises(ValueError, match="Missing provider"):
        assemble_draft(draft_id, uuid4(), "ref", result, outputs[:-1], provider.versions)
    content = syllabus_pdf(["No heading here\njust prose"])
    empty = extract_pdf(BytesIO(content), document_source(content, 1), max_bytes=100000,
                        max_pages=5, max_output_bytes=100000, minimum_useful_characters=1)
    assert not empty.nodes


def test_draft_source_validation_rejects_modified_extracted_element():
    result = extraction()
    draft_id = uuid4()
    provider, outputs = asyncio.run(provider_outputs(draft_id, result))
    draft = assemble_draft(draft_id, uuid4(), "ref", result, outputs, provider.versions)
    data = draft.model_dump()
    data["elements"][0]["title"] = "Invented title"
    with pytest.raises(ValueError):
        validate_draft_source(CurriculumDraft.model_validate(data), result)


def test_draft_settings_are_bounded():
    with pytest.raises(ValidationError):
        DraftSettings(_env_file=None, timeout_seconds=0)
    assert DraftSettings(_env_file=None).artifact_max_bytes == 4 * 1024 * 1024


async def test_provider_exception_contract_is_typed():
    provider = FakeProvider()
    assert provider.versions.model_id == "fake-curriculum-v1"
    error = ProviderError(retryable=False)
    assert error.retryable is False
