"""Graph contract, provenance and seed-template tests."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from packages.curriculum.graph import (
    graph_from_confirmed_revision,
    infer_leaf_topic_concept,
    validate_dag,
)
from packages.curriculum.templates import (
    algebra_foundations_template,
    programming_foundations_template,
    seed_template,
)
from packages.domain.extraction import DocumentSource, NodeType, SourceReference
from packages.domain.graph import (
    Concept,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphDefinition,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphSource,
    MappingKind,
    TopicConceptMapping,
)
from packages.domain.review import CurriculumRevision, ReviewElement, ReviewRecord, ReviewStatus


def topic(label: str = "Leaf topic") -> GraphNode:
    return GraphNode(
        id=uuid4(),
        node_type=GraphNodeType.TOPIC,
        label=label,
        source=GraphSource.SYLLABUS_EXPLICIT,
        confidence=1.0,
    )


def test_self_loops_are_rejected_by_the_edge_contract() -> None:
    node_id = uuid4()
    with pytest.raises(ValidationError, match="self-loops"):
        GraphEdge(
            edge_id=uuid4(),
            edge_type=EdgeType.PREREQUISITE_OF,
            source_node_id=node_id,
            target_node_id=node_id,
            source=EdgeSource.LLM_PROPOSED,
            confidence=0.8,
            status=EdgeStatus.PROPOSED,
        )


def test_inferred_fallback_is_stable_and_never_verified() -> None:
    leaf = topic()
    graph = GraphDefinition(nodes=[leaf], concepts=[], mappings=[], edges=[])

    first = infer_leaf_topic_concept(graph, leaf.id)
    second = infer_leaf_topic_concept(graph, leaf.id)

    assert first == second
    concept_node, concept, mapping = first
    assert concept_node.id == concept.id == mapping.concept_id
    assert concept.source == GraphSource.INFERRED_FALLBACK
    assert concept.verified is False
    assert mapping.mapping_kind == MappingKind.INFERRED_FALLBACK
    assert mapping.source == GraphSource.INFERRED_FALLBACK
    assert mapping.verified is False


def test_inferred_fallback_cannot_replace_an_existing_mapping() -> None:
    leaf = topic()
    concept_id = uuid4()
    graph = GraphDefinition(
        nodes=[
            leaf,
            GraphNode(
                id=concept_id,
                node_type=GraphNodeType.CONCEPT,
                label="Explicit concept",
                source=GraphSource.USER_DEFINED,
                confidence=1.0,
            ),
        ],
        concepts=[
            Concept(
                id=concept_id,
                key="explicit-concept",
                title="Explicit concept",
                source=GraphSource.USER_DEFINED,
                confidence=1.0,
            ),
        ],
        mappings=[
            TopicConceptMapping(
                mapping_id=uuid4(),
                topic_id=leaf.id,
                concept_id=concept_id,
                mapping_kind=MappingKind.EXPLICIT,
                source=GraphSource.USER_DEFINED,
                confidence=1.0,
                verified=True,
            ),
        ],
        edges=[],
    )
    with pytest.raises(ValueError, match="existing topic-to-concept"):
        infer_leaf_topic_concept(graph, leaf.id)


@pytest.mark.parametrize(
    "template_factory,template_id",
    [
        (algebra_foundations_template, "algebra-foundations"),
        (programming_foundations_template, "programming-foundations"),
    ],
)
def test_seed_templates_are_versioned_stable_and_unconfirmed(template_factory, template_id) -> None:
    first = template_factory()
    second = seed_template(template_id)

    assert first.template_id == template_id
    assert first.template_version == "v1"
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.provenance == "SEED_TEMPLATE"
    assert first.nodes and first.concepts and first.mappings and first.edges
    assert all(edge.source == EdgeSource.SEED_TEMPLATE for edge in first.edges)
    assert all(edge.status == EdgeStatus.PROPOSED for edge in first.edges)
    assert all(mapping.verified is False for mapping in first.mappings)
    assert all(concept.verified is False for concept in first.concepts)
    validate_dag(first)
    snapshot = first.to_snapshot(uuid4(), uuid4())
    assert snapshot.edges == first.edges


def test_graph_references_preserve_curriculum_element_identity() -> None:
    element_id = UUID("00000000-0000-0000-0000-000000000123")
    node = GraphNode(
        id=element_id,
        node_type=GraphNodeType.TOPIC,
        label="Confirmed topic",
        curriculum_element_id=element_id,
        source=GraphSource.SYLLABUS_EXPLICIT,
        confidence=1.0,
    )
    graph = GraphDefinition(nodes=[node], concepts=[], mappings=[], edges=[])
    assert graph.nodes[0].id == graph.nodes[0].curriculum_element_id


def test_confirmed_revision_adapter_preserves_source_and_opt_in_fallback() -> None:
    course_id = UUID("00000000-0000-0000-0000-000000000201")
    document_id = UUID("00000000-0000-0000-0000-000000000202")
    revision_id = UUID("00000000-0000-0000-0000-000000000203")
    review_id = UUID("00000000-0000-0000-0000-000000000204")
    draft_id = UUID("00000000-0000-0000-0000-000000000205")
    element_id = UUID("00000000-0000-0000-0000-000000000206")
    source_node_id = UUID("00000000-0000-0000-0000-000000000207")
    source = DocumentSource(
        course_id=course_id,
        document_id=document_id,
        version_id=UUID("00000000-0000-0000-0000-000000000208"),
        version_number=1,
        sha256="0" * 64,
        size_bytes=1,
        page_count=1,
    )
    element = ReviewElement(
        id=element_id,
        key="functions",
        type=NodeType.TOPIC,
        title="Functions",
        parent_id=None,
        order=1,
        source_node_id=source_node_id,
        sources=[SourceReference(page=1, line_start=1, line_end=1)],
        origin="EXTRACTED",
        parse_confidence=0.8,
    )
    revision = CurriculumRevision(
        id=revision_id,
        review_id=review_id,
        draft_id=draft_id,
        revision_number=1,
        parent_revision_id=None,
        source=source,
        original_draft_ref="minio://bucket/revision.json",
        elements=[element],
        created_by="fixture-student",
    )
    review = ReviewRecord(
        id=review_id,
        course_id=course_id,
        document_id=document_id,
        document_version_id=source.version_id,
        draft_id=draft_id,
        original_draft_ref=revision.original_draft_ref,
        status=ReviewStatus.CONFIRMED,
        current_revision_id=revision_id,
        revision_number=1,
        confirmed_revision_id=revision_id,
        created_by="fixture-student",
        updated_by="fixture-student",
        confirmed_by="fixture-student",
    )

    graph = graph_from_confirmed_revision(review, revision, infer_unmapped_leaves=True)

    topic_node = next(node for node in graph.nodes if node.id == element_id)
    fallback_concept = next(concept for concept in graph.concepts
                            if concept.derived_from_topic_id == element_id)
    assert topic_node.curriculum_element_id == element.id
    assert topic_node.curriculum_element is not None
    assert topic_node.source == GraphSource.SYLLABUS_EXPLICIT
    assert fallback_concept.verified is False
    assert any(mapping.concept_id == fallback_concept.id
               and mapping.mapping_kind == MappingKind.INFERRED_FALLBACK
               for mapping in graph.mappings)
