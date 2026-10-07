"""Deterministic graph algorithms and Hypothesis properties."""

from uuid import UUID, uuid5

import pytest
from hypothesis import given
from hypothesis import strategies as st

from packages.curriculum.graph import (
    GraphCycleError,
    GraphSelfLoopError,
    confirmed_prerequisite_edges,
    descendants,
    topological_depth,
    topological_order,
    unique_descendant_counts,
    validate_dag,
)
from packages.domain.graph import (
    Concept,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphSnapshot,
    GraphSource,
    MappingKind,
    TopicConceptMapping,
)

GRAPH_NAMESPACE = UUID("00000000-0000-0000-0000-00000000a301")
COURSE_ID = uuid5(GRAPH_NAMESPACE, "course")


def node_id(index: int) -> UUID:
    return uuid5(GRAPH_NAMESPACE, f"node:{index}")


def edge_id(source: UUID, target: UUID, index: int) -> UUID:
    return uuid5(GRAPH_NAMESPACE, f"edge:{source}:{target}:{index}")


@st.composite
def generated_dags(draw: st.DrawFn) -> GraphSnapshot:
    count = draw(st.integers(min_value=1, max_value=10))
    ids = [node_id(index) for index in range(count)]
    topic_identifier = uuid5(GRAPH_NAMESPACE, "generated-topic")
    nodes = [
        GraphNode(
            id=topic_identifier,
            node_type=GraphNodeType.TOPIC,
            label="Generated topic",
            source=GraphSource.SEED_TEMPLATE,
            confidence=1.0,
        ),
        *[
            GraphNode(
                id=identifier,
                node_type=GraphNodeType.CONCEPT,
                label=f"Concept {index}",
                source=GraphSource.SEED_TEMPLATE,
                confidence=1.0,
            )
            for index, identifier in enumerate(ids)
        ],
    ]
    concepts = [
        Concept(
            id=identifier,
            key=f"concept-{index}",
            title=f"Concept {index}",
            source=GraphSource.SEED_TEMPLATE,
            confidence=1.0,
        )
        for index, identifier in enumerate(ids)
    ]
    pairs = [(source, target) for source in range(count) for target in range(source + 1, count)]
    selected = draw(st.lists(st.booleans(), min_size=len(pairs), max_size=len(pairs)))
    statuses = draw(st.lists(
        st.sampled_from([EdgeStatus.CONFIRMED, EdgeStatus.PROPOSED, EdgeStatus.REJECTED]),
        min_size=len(pairs),
        max_size=len(pairs),
    ))
    edges = [
        GraphEdge(
            edge_id=edge_id(ids[source], ids[target], index),
            edge_type=EdgeType.PREREQUISITE_OF,
            source_node_id=ids[source],
            target_node_id=ids[target],
            source=EdgeSource.SEED_TEMPLATE,
            confidence=0.9,
            status=statuses[index],
        )
        for index, ((source, target), include) in enumerate(zip(pairs, selected, strict=True))
        if include
    ]
    mappings = [
        TopicConceptMapping(
            mapping_id=uuid5(GRAPH_NAMESPACE, f"mapping:{index}"),
            topic_id=topic_identifier,
            concept_id=identifier,
            mapping_kind=MappingKind.EXPLICIT,
            source=GraphSource.SEED_TEMPLATE,
            confidence=1.0,
        )
        for index, identifier in enumerate(ids)
    ]
    return GraphSnapshot(
        graph_version=1,
        course_id=COURSE_ID,
        curriculum_revision_id=uuid5(GRAPH_NAMESPACE, "revision"),
        nodes=nodes,
        concepts=concepts,
        mappings=mappings,
        edges=edges,
    )


def linear_graph(count: int) -> GraphSnapshot:
    ids = [node_id(index) for index in range(count)]
    nodes = [
        GraphNode(
            id=identifier,
            node_type=GraphNodeType.CONCEPT,
            label=f"Concept {index}",
            source=GraphSource.USER_DEFINED,
            confidence=1.0,
        )
        for index, identifier in enumerate(ids)
    ]
    concepts = [
        Concept(
            id=identifier,
            key=f"concept-{index}",
            title=f"Concept {index}",
            source=GraphSource.USER_DEFINED,
            confidence=1.0,
        )
        for index, identifier in enumerate(ids)
    ]
    edges = [
        GraphEdge(
            edge_id=edge_id(ids[index], ids[index + 1], index),
            edge_type=EdgeType.PREREQUISITE_OF,
            source_node_id=ids[index],
            target_node_id=ids[index + 1],
            source=EdgeSource.USER_CONFIRMED,
            confidence=1.0,
            status=EdgeStatus.CONFIRMED,
        )
        for index in range(count - 1)
    ]
    return GraphSnapshot(
        graph_version=1,
        course_id=COURSE_ID,
        curriculum_revision_id=uuid5(GRAPH_NAMESPACE, "chain-revision"),
        nodes=nodes,
        concepts=concepts,
        mappings=[],
        edges=edges,
    )


def chain_graph() -> GraphSnapshot:
    return linear_graph(3)


def with_edges(graph: GraphSnapshot, edges: list[GraphEdge]) -> GraphSnapshot:
    data = graph.model_dump(mode="json")
    data["edges"] = [edge.model_dump(mode="json") for edge in edges]
    return GraphSnapshot.model_validate(data)


@given(generated_dags())
def test_generated_dags_validate_and_order_confirmed_edges(graph: GraphSnapshot) -> None:
    validate_dag(graph)
    order = topological_order(graph, confirmed_only=False)
    positions = {node_id: index for index, node_id in enumerate(order)}
    for edge in graph.edges:
        if edge.status != EdgeStatus.REJECTED:
            assert positions[edge.source_node_id] < positions[edge.target_node_id]


@given(st.integers(min_value=2, max_value=12))
def test_adding_a_cycle_edge_to_a_generated_chain_fails(count: int) -> None:
    graph = linear_graph(count)
    ids = [node.id for node in graph.nodes]
    closing_edge = GraphEdge(
        edge_id=edge_id(ids[-1], ids[0], 200),
        edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=ids[-1],
        target_node_id=ids[0],
        source=EdgeSource.USER_CONFIRMED,
        confidence=1.0,
        status=EdgeStatus.CONFIRMED,
    )
    with pytest.raises(GraphCycleError):
        validate_dag(with_edges(graph, [*graph.edges, closing_edge]))


@given(generated_dags())
def test_confirmed_filter_never_returns_proposed_or_rejected(
    graph: GraphSnapshot,
) -> None:
    assert all(edge.status == EdgeStatus.CONFIRMED
               for edge in confirmed_prerequisite_edges(graph))


@given(generated_dags())
def test_unique_descendant_counts_equal_unique_reachable_nodes(
    graph: GraphSnapshot,
) -> None:
    counts = unique_descendant_counts(graph, confirmed_only=False)
    assert all(
        counts[node.id] == len(set(descendants(graph, node.id, confirmed_only=False)))
        for node in graph.nodes
    )


@given(generated_dags())
def test_canonical_bytes_are_stable_under_permutation(graph: GraphSnapshot) -> None:
    data = graph.model_dump(mode="json")
    data.update({
        "nodes": list(reversed(data["nodes"])),
        "concepts": list(reversed(data["concepts"])),
        "mappings": list(reversed(data["mappings"])),
        "edges": list(reversed(data["edges"])),
    })
    assert graph.canonical_bytes() == GraphSnapshot.model_validate(data).canonical_bytes()


@given(st.integers(min_value=0, max_value=100))
def test_self_loop_property_is_rejected(index: int) -> None:
    identifier = node_id(index)
    with pytest.raises(ValueError, match="self-loops"):
        GraphEdge(
            edge_id=edge_id(identifier, identifier, index),
            edge_type=EdgeType.PREREQUISITE_OF,
            source_node_id=identifier,
            target_node_id=identifier,
            source=EdgeSource.USER_CONFIRMED,
            confidence=1.0,
            status=EdgeStatus.CONFIRMED,
        )


def test_cycle_producing_edge_fails_validation() -> None:
    graph = chain_graph()
    ids = [node.id for node in graph.nodes]
    cycle = GraphEdge(
        edge_id=edge_id(ids[2], ids[0], 99),
        edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=ids[2],
        target_node_id=ids[0],
        source=EdgeSource.USER_CONFIRMED,
        confidence=1.0,
        status=EdgeStatus.CONFIRMED,
    )
    cyclic = with_edges(graph, [*graph.edges, cycle])
    with pytest.raises(GraphCycleError) as error:
        validate_dag(cyclic)
    assert set(error.value.node_ids) == set(ids)


def test_algorithm_detects_a_bypassed_self_loop() -> None:
    graph = chain_graph()
    identifier = graph.nodes[0].id
    invalid_edge = GraphEdge.model_construct(
        edge_id=edge_id(identifier, identifier, 100),
        edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=identifier,
        target_node_id=identifier,
        source=EdgeSource.USER_CONFIRMED,
        confidence=1.0,
        status=EdgeStatus.CONFIRMED,
    )
    invalid = graph.model_copy(update={"edges": (invalid_edge,)})
    with pytest.raises(GraphSelfLoopError):
        validate_dag(invalid)


def test_only_confirmed_edges_are_enforceable() -> None:
    graph = chain_graph()
    proposed = graph.edges[0].model_copy(update={"status": EdgeStatus.PROPOSED})
    rejected = graph.edges[1].model_copy(update={"status": EdgeStatus.REJECTED})
    mixed = with_edges(graph, [proposed, rejected])

    assert confirmed_prerequisite_edges(mixed) == ()
    assert topological_order(mixed) == tuple(sorted((node.id for node in mixed.nodes), key=str))
    validate_dag(mixed)


def test_topological_depth_and_unique_descendants_use_confirmed_direction() -> None:
    graph = chain_graph()
    ids = [node.id for node in graph.nodes]
    assert topological_depth(graph) == {ids[0]: 0, ids[1]: 1, ids[2]: 2}
    assert unique_descendant_counts(graph) == {ids[0]: 2, ids[1]: 1, ids[2]: 0}
    assert descendants(graph, ids[0]) == (ids[1], ids[2])


def test_descendants_count_shared_nodes_once() -> None:
    graph = chain_graph()
    ids = [node.id for node in graph.nodes]
    diamond_edge = GraphEdge(
        edge_id=edge_id(ids[0], ids[2], 101),
        edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=ids[0],
        target_node_id=ids[2],
        source=EdgeSource.USER_CONFIRMED,
        confidence=1.0,
        status=EdgeStatus.CONFIRMED,
    )
    diamond = with_edges(graph, [graph.edges[0], diamond_edge])
    assert unique_descendant_counts(diamond)[ids[0]] == 2


def test_canonical_serialization_is_independent_of_input_permutation() -> None:
    graph = chain_graph()
    data = graph.model_dump(mode="json")
    data.update({
        "nodes": list(reversed(data["nodes"])),
        "concepts": list(reversed(data["concepts"])),
        "mappings": list(reversed(data["mappings"])),
        "edges": list(reversed(data["edges"])),
    })
    permuted = GraphSnapshot.model_validate(data)
    assert graph.canonical_bytes() == permuted.canonical_bytes()
