"""Deterministic, I/O-free algorithms for graph validation and traversal."""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from uuid import NAMESPACE_URL, UUID, uuid5

from packages.domain.extraction import NodeType
from packages.domain.graph import (
    Concept,
    EdgeStatus,
    EdgeType,
    GraphDefinition,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphSnapshot,
    GraphSource,
    MappingKind,
    TopicConceptMapping,
)
from packages.domain.review import CurriculumRevision, ReviewRecord, ReviewStatus

INFERRED_CONCEPT_NAMESPACE = uuid5(NAMESPACE_URL, "aaa-v3:inferred-leaf-concepts:v1")


class GraphValidationError(ValueError):
    """Base error for invalid executable graph structure."""


class GraphCycleError(GraphValidationError):
    """Raised when active prerequisite relationships are cyclic."""

    def __init__(self, node_ids: Iterable[UUID]) -> None:
        self.node_ids = tuple(sorted(node_ids, key=str))
        rendered = ", ".join(str(node_id) for node_id in self.node_ids)
        super().__init__(f"Prerequisite cycle leaves unresolved nodes: {rendered}")


class GraphSelfLoopError(GraphValidationError):
    """Raised when an edge bypasses contract construction and is self-referential."""

    def __init__(self, edge_id: UUID) -> None:
        self.edge_id = edge_id
        super().__init__(f"Graph edge {edge_id} is a self-loop")


def _prerequisite_edges(
    graph: GraphDefinition, *, confirmed_only: bool,
) -> tuple[GraphEdge, ...]:
    """Select executable or candidate prerequisite edges deterministically."""

    _validate_self_loops(graph)
    edges = [
        edge
        for edge in graph.edges
        if edge.edge_type == EdgeType.PREREQUISITE_OF
        and edge.status != EdgeStatus.REJECTED
        and (not confirmed_only or edge.status == EdgeStatus.CONFIRMED)
    ]
    return tuple(sorted(
        edges,
        key=lambda edge: (str(edge.source_node_id), str(edge.target_node_id), str(edge.edge_id)),
    ))


def confirmed_prerequisite_edges(graph: GraphDefinition) -> tuple[GraphEdge, ...]:
    """Return only confirmed prerequisite edges that may enforce a gate."""

    return _prerequisite_edges(graph, confirmed_only=True)


def proposed_prerequisite_edges(graph: GraphDefinition) -> tuple[GraphEdge, ...]:
    """Return proposed prerequisite edges for informational display only."""

    return tuple(
        edge for edge in _prerequisite_edges(graph, confirmed_only=False)
        if edge.status == EdgeStatus.PROPOSED
    )


def rejected_prerequisite_edges(graph: GraphDefinition) -> tuple[GraphEdge, ...]:
    """Return rejected prerequisite edges for audit display only."""

    return tuple(sorted(
        (
            edge for edge in graph.edges
            if edge.edge_type == EdgeType.PREREQUISITE_OF and edge.status == EdgeStatus.REJECTED
        ),
        key=lambda edge: (str(edge.source_node_id), str(edge.target_node_id), str(edge.edge_id)),
    ))


def _validate_self_loops(graph: GraphDefinition) -> None:
    for edge in graph.edges:
        if edge.source_node_id == edge.target_node_id:
            raise GraphSelfLoopError(edge.edge_id)


def _topological_order(
    graph: GraphDefinition, edges: tuple[GraphEdge, ...],
) -> tuple[UUID, ...]:
    node_ids = tuple(sorted((node.id for node in graph.nodes), key=str))
    adjacency: dict[UUID, list[UUID]] = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)
        indegree[edge.target_node_id] += 1
    for children in adjacency.values():
        children.sort(key=str)

    ready = [(str(node_id), node_id) for node_id in node_ids if indegree[node_id] == 0]
    heapq.heapify(ready)
    ordered: list[UUID] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for child_id in adjacency[node_id]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                heapq.heappush(ready, (str(child_id), child_id))

    if len(ordered) != len(node_ids):
        raise GraphCycleError(node_id for node_id, degree in indegree.items() if degree > 0)
    return tuple(ordered)


def validate_dag(graph: GraphDefinition, *, include_proposed: bool = True) -> None:
    """Validate the prerequisite DAG.

    Proposed edges are included by default so a generated candidate graph
    cannot hide a cycle. Rejected edges are always excluded: they remain
    auditable data but are not part of either the candidate or executable graph.
    """

    _validate_self_loops(graph)
    edges = _prerequisite_edges(graph, confirmed_only=not include_proposed)
    _topological_order(graph, edges)


def topological_order(
    graph: GraphDefinition, *, confirmed_only: bool = True,
) -> tuple[UUID, ...]:
    """Return a stable Kahn topological ordering of all graph nodes."""

    _validate_self_loops(graph)
    edges = _prerequisite_edges(graph, confirmed_only=confirmed_only)
    return _topological_order(graph, edges)


def topological_depth(
    graph: GraphDefinition, *, confirmed_only: bool = True,
) -> dict[UUID, int]:
    """Return the longest confirmed-prerequisite distance from any root."""

    edges = _prerequisite_edges(graph, confirmed_only=confirmed_only)
    order = _topological_order(graph, edges)
    depth = {node.id: 0 for node in graph.nodes}
    adjacency: dict[UUID, list[UUID]] = {node.id: [] for node in graph.nodes}
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)
    for node_id in order:
        for child_id in adjacency[node_id]:
            depth[child_id] = max(depth[child_id], depth[node_id] + 1)
    return {node_id: depth[node_id] for node_id in sorted(depth, key=str)}


def unique_descendant_counts(
    graph: GraphDefinition, *, confirmed_only: bool = True,
) -> dict[UUID, int]:
    """Count each reachable descendant once for every graph node."""

    edges = _prerequisite_edges(graph, confirmed_only=confirmed_only)
    order = _topological_order(graph, edges)
    adjacency: dict[UUID, list[UUID]] = {node.id: [] for node in graph.nodes}
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)

    descendants_by_node: dict[UUID, set[UUID]] = {node.id: set() for node in graph.nodes}
    for node_id in reversed(order):
        for child_id in adjacency[node_id]:
            descendants_by_node[node_id].add(child_id)
            descendants_by_node[node_id].update(descendants_by_node[child_id])
    return {
        node_id: len(descendants_by_node[node_id])
        for node_id in sorted(descendants_by_node, key=str)
    }


def descendants(
    graph: GraphDefinition, node_id: UUID, *, confirmed_only: bool = True,
) -> tuple[UUID, ...]:
    """Return unique descendants in stable topological order."""

    if node_id not in {node.id for node in graph.nodes}:
        raise ValueError(f"Unknown graph node: {node_id}")
    edges = _prerequisite_edges(graph, confirmed_only=confirmed_only)
    order = _topological_order(graph, edges)
    adjacency: dict[UUID, list[UUID]] = {node.id: [] for node in graph.nodes}
    for edge in edges:
        adjacency[edge.source_node_id].append(edge.target_node_id)
    found: set[UUID] = set()
    pending = list(adjacency[node_id])
    while pending:
        child_id = pending.pop()
        if child_id in found:
            continue
        found.add(child_id)
        pending.extend(adjacency[child_id])
    return tuple(candidate for candidate in order if candidate in found)


def infer_leaf_topic_concept(
    graph: GraphDefinition, topic_id: UUID,
) -> tuple[GraphNode, Concept, TopicConceptMapping]:
    """Create a stable, visibly inferred leaf-topic fallback.

    The returned concept node and mapping are not confirmed. Callers must
    merge them into a new graph definition if they choose to use this fallback.
    Existing mappings and non-leaf topics are rejected so this helper cannot
    silently replace a more precise mapping.
    """

    graph = type(graph).model_validate(graph.model_dump())
    nodes = {node.id: node for node in graph.nodes}
    topic = nodes.get(topic_id)
    if topic is None or topic.node_type != GraphNodeType.TOPIC:
        raise ValueError("Leaf fallback requires an existing TOPIC node")
    if any(node.parent_id == topic_id for node in graph.nodes):
        raise ValueError("Leaf fallback is only valid for a topic without child topics")
    if any(mapping.topic_id == topic_id for mapping in graph.mappings):
        raise ValueError("Leaf fallback cannot replace an existing topic-to-concept mapping")

    concept_id = uuid5(INFERRED_CONCEPT_NAMESPACE, str(topic_id))
    if concept_id in nodes:
        raise ValueError("Fallback concept identity already exists")
    concept_node = GraphNode(
        id=concept_id,
        node_type=GraphNodeType.CONCEPT,
        label=topic.label,
        source=GraphSource.INFERRED_FALLBACK,
        confidence=0.0,
    )
    concept = Concept(
        id=concept_id,
        key=f"inferred-{concept_id.hex[:16]}",
        title=topic.label,
        description="Fallback concept inferred from a leaf topic; not manually verified.",
        source=GraphSource.INFERRED_FALLBACK,
        confidence=0.0,
        verified=False,
        derived_from_topic_id=topic_id,
    )
    mapping = TopicConceptMapping(
        mapping_id=uuid5(concept_id, "mapping:v1"),
        topic_id=topic_id,
        concept_id=concept_id,
        mapping_kind=MappingKind.INFERRED_FALLBACK,
        source=GraphSource.INFERRED_FALLBACK,
        confidence=0.0,
        verified=False,
    )
    return concept_node, concept, mapping


def graph_from_confirmed_revision(
    review: ReviewRecord,
    revision: CurriculumRevision,
    *,
    concepts: tuple[Concept, ...] = (),
    mappings: tuple[TopicConceptMapping, ...] = (),
    edges: tuple[GraphEdge, ...] = (),
    infer_unmapped_leaves: bool = False,
    graph_version: int = 1,
) -> GraphSnapshot:
    """Adapt a confirmed Phase 2 revision without changing IDs or inventing edges.

    Explicit definitions and mappings take precedence. Fallback is opt-in, only
    for actual TOPIC/SUBTOPIC leaves, and always carries inferred provenance.
    This validates supplied domain values; persistence must establish their authenticity.
    """

    review = ReviewRecord.model_validate(review.model_dump())
    revision = CurriculumRevision.model_validate(revision.model_dump())
    if review.status != ReviewStatus.CONFIRMED or not review.confirmed_by:
        raise ValueError("Graph construction requires a confirmed curriculum")
    if (review.confirmed_revision_id != revision.id
            or review.current_revision_id != revision.id or review.id != revision.review_id
            or review.draft_id != revision.draft_id
            or review.revision_number != revision.revision_number
            or review.course_id != revision.source.course_id
            or review.document_id != revision.source.document_id
            or review.document_version_id != revision.source.version_id
            or review.original_draft_ref != revision.original_draft_ref):
        raise ValueError("Confirmed curriculum revision association mismatch")
    nodes = [
        GraphNode(
            id=element.id,
            node_type=(GraphNodeType.TOPIC if element.type in {NodeType.TOPIC, NodeType.SUBTOPIC}
                       else GraphNodeType.CONTAINER),
            label=element.title,
            parent_id=element.parent_id,
            curriculum_element_id=element.id,
            curriculum_element=element.model_copy(deep=True),
            source={
                "HUMAN": GraphSource.USER_DEFINED,
                "EXTRACTED": GraphSource.SYLLABUS_EXPLICIT,
                "GENERATED": GraphSource.LLM_PROPOSED,
            }[element.origin],
            confidence=element.parse_confidence,
        )
        for element in revision.elements
    ]
    nodes.extend(
        GraphNode(id=concept.id, node_type=GraphNodeType.CONCEPT, label=concept.title,
                  source=concept.source, confidence=concept.confidence)
        for concept in concepts
    )
    snapshot = GraphSnapshot(
        course_id=review.course_id, curriculum_revision_id=revision.id,
        curriculum_source=revision.source.model_copy(deep=True), graph_version=graph_version,
        nodes=tuple(nodes), concepts=concepts, mappings=mappings, edges=edges,
    )
    if infer_unmapped_leaves:
        parents = {node.parent_id for node in nodes}
        mapped = {mapping.topic_id for mapping in mappings}
        additions = [
            infer_leaf_topic_concept(snapshot, node.id)
            for node in nodes
            if node.node_type == GraphNodeType.TOPIC and node.id not in parents | mapped
        ]
        snapshot = GraphSnapshot.model_validate(snapshot.model_dump() | {
            "nodes": (*snapshot.nodes, *(item[0] for item in additions)),
            "concepts": (*snapshot.concepts, *(item[1] for item in additions)),
            "mappings": (*snapshot.mappings, *(item[2] for item in additions)),
        })
    validate_dag(snapshot)
    return snapshot
