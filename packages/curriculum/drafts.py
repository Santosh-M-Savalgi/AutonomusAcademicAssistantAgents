"""Pure source partitioning, provider-output validation, and draft assembly."""

from uuid import UUID

from packages.domain.curriculum import (
    CurriculumDraft,
    CurriculumElement,
    GeneratedElement,
    GenerationInput,
    GenerationOutput,
    SourcePassage,
    element_id,
)
from packages.domain.extraction import ExtractionResult, NodeType
from packages.domain.models import VersionStamp


def generation_inputs(draft_id: UUID, extraction: ExtractionResult) -> list[GenerationInput]:
    """One bounded request per extracted root, independent of syllabus naming conventions."""

    root_of: dict[UUID, UUID] = {}
    groups: dict[UUID, GenerationInput] = {}
    for node in extraction.nodes:
        root = root_of[node.parent_id] if node.parent_id else node.id
        root_of[node.id] = root
        groups.setdefault(root, GenerationInput(draft_id=draft_id, sections=[], passages=[]))
        groups[root].sections.append(node)
        lines = extraction.pages[node.source.page - 1].text.split("\n")
        groups[root].passages.append(SourcePassage(
            source=node.source,
            text="\n".join(lines[node.source.line_start - 1:node.source.line_end]),
        ))
    return list(groups.values())


def validate_provider_output(request: GenerationInput, content: bytes) -> GenerationOutput:
    output = GenerationOutput.model_validate_json(content)
    sections = {node.id: node for node in request.sections}
    anchors = {element_id(request.draft_id, node.id): node for node in request.sections}
    seen: dict[UUID, GeneratedElement] = {}
    for node in output.elements:
        if node.source_node_id is None:
            raise ValueError("Generated element requires a source node")
        source = sections.get(node.source_node_id)
        if source is None or node.id != element_id(request.draft_id, source.id, node.key):
            raise ValueError("Invalid generated identity/source")
        if node.id in seen or node.id in anchors or not node.title.strip():
            raise ValueError("Duplicate or empty provider element")
        # This sprint admits only the exact source-section range, never invented citations.
        if node.sources != [source.source]:
            raise ValueError("Invalid generated provenance")
        anchor = anchors.get(node.parent_id)
        parent = seen.get(node.parent_id)
        if anchor is not None:
            if anchor.id != source.id or (
                node.type == "TOPIC" and anchor.type in {NodeType.TOPIC, NodeType.SUBTOPIC}
            ) or (
                node.type == "SUBTOPIC"
                and anchor.type not in {NodeType.TOPIC, NodeType.SUBTOPIC}
            ):
                raise ValueError("Generated hierarchy contradicts extracted hierarchy")
        elif parent is None or parent.source_node_id != source.id or node.type != "SUBTOPIC":
            raise ValueError("Invalid generated parent")
        seen[node.id] = node
    return output


def assemble_draft(
    draft_id: UUID, extraction_job_id: UUID, extraction_ref: str, extraction: ExtractionResult,
    outputs: list[GenerationOutput], versions: VersionStamp,
) -> CurriculumDraft:
    requests = generation_inputs(draft_id, extraction)
    if len(outputs) != len(requests):
        raise ValueError("Missing provider section output")
    generated: dict[UUID, list[GeneratedElement]] = {}
    for request, output in zip(requests, outputs, strict=True):
        validated = validate_provider_output(request, output.model_dump_json().encode())
        for node in validated.elements:
            generated.setdefault(node.source_node_id, []).append(node)
    elements: list[CurriculumElement] = []
    for section in extraction.nodes:
        elements.append(CurriculumElement(
            id=element_id(draft_id, section.id), key="extracted",
            type=section.type, title=section.title,
            parent_id=element_id(draft_id, section.parent_id) if section.parent_id else None,
            order=len(elements) + 1, source_node_id=section.id, sources=[section.source],
            origin="EXTRACTED", parse_confidence=section.parse_confidence,
        ))
        for node in generated.get(section.id, []):
            elements.append(CurriculumElement(
                id=node.id, key=node.key, type=NodeType(node.type), title=node.title,
                parent_id=node.parent_id,
                order=len(elements) + 1, source_node_id=section.id, sources=node.sources,
                origin="GENERATED", parse_confidence=section.parse_confidence,
            ))
    warnings = []
    if extraction.summary.status != "TEXT":
        warnings.append("LOW_TEXT")
    if extraction.summary.empty_page_count:
        warnings.append("EMPTY_PAGES")
    if extraction.unclassified:
        warnings.append("UNCLASSIFIED_CONTENT")
    if not extraction.nodes:
        warnings.append("NO_STRUCTURE")
    parents = {node.parent_id for node in elements}
    if any(node.id not in parents and node.type not in {NodeType.TOPIC, NodeType.SUBTOPIC}
           for node in elements) or not elements:
        warnings.append("MISSING_TOPICS")
    return CurriculumDraft.model_validate({
        "id": draft_id, "source": extraction.source, "extraction_job_id": extraction_job_id,
        "extraction_ref": extraction_ref, "versions": versions, "elements": elements,
        "unclassified": extraction.unclassified, "warnings": warnings,
        "completeness": "INCOMPLETE" if warnings else "COMPLETE",
    })


def validate_draft_source(draft: CurriculumDraft, extraction: ExtractionResult) -> None:
    """Recheck artifacts independently of providers, including API reads."""

    sections = {node.id: node for node in extraction.nodes}
    anchors = [node for node in draft.elements if node.origin == "EXTRACTED"]
    if draft.source != extraction.source or draft.unclassified != extraction.unclassified:
        raise ValueError("Draft source mismatch")
    anchor_ids: list[UUID] = []
    for node in anchors:
        if node.source_node_id is None:
            raise ValueError("Extracted element requires a source node")
        anchor_ids.append(node.source_node_id)
    if anchor_ids != [node.id for node in extraction.nodes]:
        raise ValueError("Missing or reordered extracted hierarchy")
    for node in draft.elements:
        if node.origin == "HUMAN":
            continue
        if node.source_node_id is None:
            raise ValueError("Source-derived element requires a source node")
        source = sections.get(node.source_node_id)
        if source is None or node.sources != [source.source]:
            raise ValueError("Invalid draft provenance")
        if node.origin == "EXTRACTED" and (
            node.id != element_id(draft.id, source.id) or node.title != source.title
            or node.type != source.type or node.parent_id != (
                element_id(draft.id, source.parent_id) if source.parent_id else None
            )
        ):
            raise ValueError("Extracted hierarchy modified")
    outputs = []
    for request in generation_inputs(draft.id, extraction):
        ids = {section.id for section in request.sections}
        outputs.append(GenerationOutput(schema_version="curriculum-unit-v1", elements=[
            GeneratedElement.model_validate({key: value for key, value in node.model_dump().items()
                                             if key in GeneratedElement.model_fields})
            for node in draft.elements if node.origin == "GENERATED" and node.source_node_id in ids
        ]))
    expected = assemble_draft(draft.id, draft.extraction_job_id, draft.extraction_ref,
                              extraction, outputs, draft.versions)
    if expected != draft:
        raise ValueError("Inconsistent draft content/metadata")
