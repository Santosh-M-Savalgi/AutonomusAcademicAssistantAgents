"""Pure, versioned contracts for the curriculum and prerequisite graph.

The graph deliberately models topic containment separately from prerequisite
relationships. A topic's parent is curriculum hierarchy metadata; it never
creates a prerequisite edge. For a ``PREREQUISITE_OF`` edge, the source node
is always the prerequisite and the target node is always the dependent.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from packages.domain.extraction import DocumentSource, NodeType
from packages.domain.models import DomainModel
from packages.domain.review import ReviewElement

GRAPH_SCHEMA_VERSION: Literal["graph-v1"] = "graph-v1"
GRAPH_TEMPLATE_SCHEMA_VERSION: Literal["graph-template-v1"] = "graph-template-v1"
GRAPH_BUILD_JOB_SCHEMA_VERSION: Literal["graph-build-v1"] = "graph-build-v1"


class GraphNodeType(StrEnum):
    """Kinds of nodes that may participate in the learning graph."""

    CONTAINER = "CONTAINER"
    TOPIC = "TOPIC"
    CONCEPT = "CONCEPT"


class GraphSource(StrEnum):
    """Provenance for graph nodes, concepts and mappings."""

    SYLLABUS_EXPLICIT = "SYLLABUS_EXPLICIT"
    USER_DEFINED = "USER_DEFINED"
    LLM_PROPOSED = "LLM_PROPOSED"
    USER_CONFIRMED = "USER_CONFIRMED"
    SEED_TEMPLATE = "SEED_TEMPLATE"
    INFERRED_FALLBACK = "INFERRED_FALLBACK"


class EdgeType(StrEnum):
    """Relationships represented in a graph snapshot."""

    PREREQUISITE_OF = "PREREQUISITE_OF"
    PART_OF = "PART_OF"
    RELATED_TO = "RELATED_TO"
    BUILDS_ON = "BUILDS_ON"
    ASSESSES = "ASSESSES"
    EXAMPLE_OF = "EXAMPLE_OF"


class EdgeSource(StrEnum):
    """Allowed provenance values for graph relationships."""

    SYLLABUS_EXPLICIT = "SYLLABUS_EXPLICIT"
    LLM_PROPOSED = "LLM_PROPOSED"
    USER_CONFIRMED = "USER_CONFIRMED"
    SEED_TEMPLATE = "SEED_TEMPLATE"


class EdgeStatus(StrEnum):
    """Lifecycle state of a graph relationship."""

    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class GraphPublicationStatus(StrEnum):
    """Durable lifecycle of a relational graph snapshot."""

    PUBLISHED = "PUBLISHED"


class MappingKind(StrEnum):
    """Whether a topic-to-concept mapping was explicit or inferred."""

    EXPLICIT = "EXPLICIT"
    INFERRED_FALLBACK = "INFERRED_FALLBACK"


class GraphModel(DomainModel):
    """Immutable graph values; nested graph instances are revalidated on ingestion."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always", allow_inf_nan=False)


class GraphNode(GraphModel):
    """A topic or concept node with stable identity and provenance."""

    id: UUID
    node_type: GraphNodeType
    label: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None
    curriculum_element_id: UUID | None = None
    curriculum_element: ReviewElement | None = None
    source: GraphSource
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if not self.label.strip():
            raise ValueError("Graph node label cannot be blank")
        if self.parent_id == self.id:
            raise ValueError("A graph node cannot be its own parent")
        if self.curriculum_element is not None:
            element = ReviewElement.model_validate(self.curriculum_element.model_dump())
            expected_type = (
                GraphNodeType.TOPIC
                if element.type in {NodeType.TOPIC, NodeType.SUBTOPIC}
                else GraphNodeType.CONTAINER
            )
            if (self.id != element.id or self.curriculum_element_id != element.id
                    or self.parent_id != element.parent_id or self.label != element.title
                    or self.node_type != expected_type
                    or self.confidence != element.parse_confidence):
                raise ValueError("Graph node must preserve its curriculum element")
            expected_source = {
                "HUMAN": GraphSource.USER_DEFINED,
                "EXTRACTED": GraphSource.SYLLABUS_EXPLICIT,
                "GENERATED": GraphSource.LLM_PROPOSED,
            }[element.origin]
            if self.source != expected_source:
                raise ValueError("Graph node must preserve curriculum origin")
        return self


class Concept(GraphModel):
    """A stable concept definition, independent of a particular topic title."""

    id: UUID
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    source: GraphSource
    confidence: float = Field(ge=0, le=1)
    verified: bool = False
    derived_from_topic_id: UUID | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if not self.title.strip():
            raise ValueError("Concept title cannot be blank")
        if (self.source == GraphSource.INFERRED_FALLBACK
                and (self.verified or self.derived_from_topic_id is None)):
            raise ValueError("Inferred concepts require a source topic and remain unverified")
        return self


class TopicConceptMapping(GraphModel):
    """A typed mapping that keeps inferred fallback provenance explicit."""

    mapping_id: UUID
    topic_id: UUID
    concept_id: UUID
    mapping_kind: MappingKind
    source: GraphSource
    confidence: float = Field(ge=0, le=1)
    verified: bool = False

    @model_validator(mode="after")
    def validate_inferred_mapping(self) -> Self:
        if self.mapping_kind == MappingKind.INFERRED_FALLBACK:
            if self.source != GraphSource.INFERRED_FALLBACK or self.verified:
                raise ValueError(
                    "An inferred fallback mapping must retain inferred provenance "
                    "and remain unverified"
                )
        elif self.source == GraphSource.INFERRED_FALLBACK:
            raise ValueError("An explicit mapping cannot use inferred fallback provenance")
        return self


class GraphEdge(GraphModel):
    """A directed graph relationship.

    For ``PREREQUISITE_OF``, ``source_node_id`` is the prerequisite and
    ``target_node_id`` is the dependent. Confirmation is intentionally
    independent from confidence and provenance.
    """

    edge_id: UUID
    edge_type: EdgeType
    source_node_id: UUID
    target_node_id: UUID
    source: EdgeSource
    confidence: float = Field(ge=0, le=1)
    status: EdgeStatus

    @model_validator(mode="after")
    def reject_self_loop(self) -> Self:
        if self.source_node_id == self.target_node_id:
            raise ValueError("Graph edges cannot be self-loops")
        return self


class PrerequisiteEdge(GraphEdge):
    """A prerequisite -> dependent relationship between two concepts."""

    edge_type: Literal[EdgeType.PREREQUISITE_OF] = EdgeType.PREREQUISITE_OF


class GraphDefinition(GraphModel):
    """Common validated contents shared by snapshots and seed templates."""

    nodes: tuple[GraphNode, ...]
    concepts: tuple[Concept, ...]
    mappings: tuple[TopicConceptMapping, ...]
    edges: tuple[GraphEdge, ...]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Graph node identifiers must be unique")

        concepts = {concept.id: concept for concept in self.concepts}
        if len(concepts) != len(self.concepts):
            raise ValueError("Concept identifiers must be unique")
        concept_node_ids = {
            node.id for node in self.nodes if node.node_type == GraphNodeType.CONCEPT
        }
        if concept_node_ids != set(concepts):
            raise ValueError("Every concept must have exactly one CONCEPT graph node")
        for concept in self.concepts:
            node = nodes[concept.id]
            if (node.label, node.source, node.confidence) != (
                concept.title, concept.source, concept.confidence,
            ):
                raise ValueError("Concept definition and graph node must agree")
            if concept.derived_from_topic_id is not None:
                origin = nodes.get(concept.derived_from_topic_id)
                if origin is None or origin.node_type != GraphNodeType.TOPIC:
                    raise ValueError("Derived concept references an unknown topic")

        for node in self.nodes:
            if node.parent_id is None:
                continue
            parent = nodes.get(node.parent_id)
            if parent is None:
                raise ValueError(f"Graph node {node.id} references an unknown parent")
            if GraphNodeType.CONCEPT in {node.node_type, parent.node_type}:
                raise ValueError("Concepts cannot participate in curriculum containment")

        # Validate the containment forest separately; it never generates prerequisites.
        visited: set[UUID] = set()
        for node in self.nodes:
            path: set[UUID] = set()
            cursor: UUID | None = node.id
            while cursor is not None and cursor not in visited:
                if cursor in path:
                    raise ValueError("Curriculum containment contains a cycle")
                path.add(cursor)
                cursor = nodes[cursor].parent_id
            visited.update(path)

        mapping_ids: set[UUID] = set()
        mapping_pairs: set[tuple[UUID, UUID]] = set()
        for mapping in self.mappings:
            if mapping.mapping_id in mapping_ids:
                raise ValueError("Topic-to-concept mapping identifiers must be unique")
            if (mapping.topic_id, mapping.concept_id) in mapping_pairs:
                raise ValueError("A topic-to-concept pair may appear only once")
            topic = nodes.get(mapping.topic_id)
            concept_node = nodes.get(mapping.concept_id)
            if topic is None or topic.node_type != GraphNodeType.TOPIC:
                raise ValueError("Topic-to-concept mappings require a TOPIC source")
            if concept_node is None or concept_node.node_type != GraphNodeType.CONCEPT:
                raise ValueError("Topic-to-concept mappings require a CONCEPT target")
            definition = concepts[mapping.concept_id]
            if mapping.mapping_kind == MappingKind.INFERRED_FALLBACK and (
                definition.source != GraphSource.INFERRED_FALLBACK
                or definition.derived_from_topic_id != mapping.topic_id
            ):
                raise ValueError("Inferred mapping must reference its topic-derived concept")
            if (mapping.mapping_kind == MappingKind.EXPLICIT
                    and definition.source == GraphSource.INFERRED_FALLBACK):
                raise ValueError("An inferred concept requires an inferred fallback mapping")
            mapping_ids.add(mapping.mapping_id)
            mapping_pairs.add((mapping.topic_id, mapping.concept_id))

        edge_ids: set[UUID] = set()
        edge_pairs: set[tuple[EdgeType, UUID, UUID]] = set()
        for edge in self.edges:
            if edge.edge_id in edge_ids:
                raise ValueError("Graph edge identifiers must be unique")
            if (edge.edge_type, edge.source_node_id, edge.target_node_id) in edge_pairs:
                raise ValueError("A graph relationship may appear only once per snapshot")
            source = nodes.get(edge.source_node_id)
            target = nodes.get(edge.target_node_id)
            if source is None or target is None:
                raise ValueError("Graph edges must reference known nodes")
            if edge.edge_type == EdgeType.PREREQUISITE_OF and (
                source.node_type != GraphNodeType.CONCEPT
                or target.node_type != GraphNodeType.CONCEPT
            ):
                raise ValueError("Prerequisite edges must connect concepts")
            edge_ids.add(edge.edge_id)
            edge_pairs.add((edge.edge_type, edge.source_node_id, edge.target_node_id))
        return self

    def canonical_dict(self) -> dict[str, object]:
        """Return an order-independent JSON-compatible representation."""

        data = type(self).model_validate(self.model_dump()).model_dump(mode="json")
        for field, identifier in (
            ("nodes", "id"),
            ("concepts", "id"),
            ("mappings", "mapping_id"),
            ("edges", "edge_id"),
        ):
            values = data[field]
            assert isinstance(values, list)
            values.sort(key=lambda item: str(item[identifier]))
        return data

    def canonical_bytes(self) -> bytes:
        """Serialize the graph deterministically for hashing and comparison."""

        return json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


class GraphSnapshot(GraphDefinition):
    """A graph associated with one confirmed curriculum revision."""

    schema_version: Literal["graph-v1"] = GRAPH_SCHEMA_VERSION
    graph_version: int = Field(ge=1)
    course_id: UUID
    curriculum_revision_id: UUID
    curriculum_source: DocumentSource | None = None

    @model_validator(mode="after")
    def validate_curriculum_source(self) -> Self:
        if self.curriculum_source is not None:
            if self.curriculum_source.course_id != self.course_id:
                raise ValueError("Graph course differs from curriculum source")
            for node in self.nodes:
                if node.curriculum_element is not None and any(
                    ref.page > self.curriculum_source.page_count
                    for ref in node.curriculum_element.sources
                ):
                    raise ValueError("Graph provenance is outside the source document")
        return self


class GraphBuildJobPayload(GraphModel):
    """Exact immutable revision identity carried by a graph-build job."""

    schema_version: Literal["graph-build-v1"] = GRAPH_BUILD_JOB_SCHEMA_VERSION
    course_id: UUID
    review_id: UUID
    curriculum_revision_id: UUID
    revision_artifact_ref: str = Field(min_length=1, max_length=512)
    revision_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_identity_id: UUID
    actor_subject: str = Field(min_length=1, max_length=255)
    graph_version: int = Field(default=1, ge=1)


class GraphTemplate(GraphDefinition):
    """A versioned, auditable seed graph that is not confirmation by itself."""

    schema_version: Literal["graph-template-v1"] = GRAPH_TEMPLATE_SCHEMA_VERSION
    template_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    template_version: str = Field(pattern=r"^v[0-9]+$")
    subject: str = Field(min_length=1, max_length=100)
    provenance: Literal["SEED_TEMPLATE"] = "SEED_TEMPLATE"

    def to_snapshot(
        self,
        course_id: UUID,
        curriculum_revision_id: UUID,
        *,
        graph_version: int = 1,
    ) -> GraphSnapshot:
        """Attach a seed definition to a confirmed curriculum revision.

        Edges retain their original ``PROPOSED`` status and therefore remain
        informational until an explicit confirmation operation occurs later.
        """

        return GraphSnapshot(
            course_id=course_id,
            graph_version=graph_version,
            curriculum_revision_id=curriculum_revision_id,
            nodes=self.nodes,
            concepts=self.concepts,
            mappings=self.mappings,
            edges=self.edges,
        )

    @model_validator(mode="after")
    def unconfirmed_template(self) -> Self:
        if any(
            edge.status != EdgeStatus.PROPOSED or edge.source != EdgeSource.SEED_TEMPLATE
            for edge in self.edges
        ):
            raise ValueError("Seed template edges must be proposed with template provenance")
        if any(node.source != GraphSource.SEED_TEMPLATE for node in self.nodes):
            raise ValueError("Seed template nodes must retain template provenance")
        if any(
            concept.source != GraphSource.SEED_TEMPLATE or concept.verified
            for concept in self.concepts
        ) or any(
            mapping.source != GraphSource.SEED_TEMPLATE or mapping.verified
            for mapping in self.mappings
        ):
            raise ValueError("Seed concepts and mappings must remain unverified")
        return self
