"""Versioned seed graph templates with stable, non-confirming provenance."""

from __future__ import annotations

from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from packages.domain.graph import (
    Concept,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphSource,
    GraphTemplate,
    MappingKind,
    TopicConceptMapping,
)

SEED_TEMPLATE_NAMESPACE = uuid5(NAMESPACE_URL, "aaa-v3:seed-graph-templates:v1")


def _stable_id(template_id: str, kind: str, key: str) -> UUID:
    # Namespace v1 is the identity scheme, not the template content revision.
    return uuid5(SEED_TEMPLATE_NAMESPACE, f"{template_id}:{kind}:{key}")


def _node(
    template_id: str,
    node_type: GraphNodeType,
    key: str,
    label: str,
    *,
    parent_id: UUID | None = None,
) -> GraphNode:
    return GraphNode(
        id=_stable_id(template_id, node_type.value.lower(), key),
        node_type=node_type,
        label=label,
        parent_id=parent_id,
        source=GraphSource.SEED_TEMPLATE,
        confidence=1.0,
    )


def _concept(template_id: str, key: str, title: str) -> tuple[GraphNode, Concept]:
    concept_id = _stable_id(template_id, "concept", key)
    return (
        GraphNode(
            id=concept_id,
            node_type=GraphNodeType.CONCEPT,
            label=title,
            source=GraphSource.SEED_TEMPLATE,
            confidence=1.0,
        ),
        Concept(
            id=concept_id,
            key=key,
            title=title,
            source=GraphSource.SEED_TEMPLATE,
            confidence=1.0,
            verified=False,
        ),
    )


def _mapping(
    template_id: str, topic_id: UUID, concept_id: UUID, key: str,
) -> TopicConceptMapping:
    return TopicConceptMapping(
        mapping_id=_stable_id(template_id, "mapping", key),
        topic_id=topic_id,
        concept_id=concept_id,
        mapping_kind=MappingKind.EXPLICIT,
        source=GraphSource.SEED_TEMPLATE,
        confidence=0.9,
        verified=False,
    )


def _prerequisite(
    template_id: str,
    prerequisite_id: UUID,
    dependent_id: UUID,
    key: str,
    confidence: float = 0.9,
) -> GraphEdge:
    return GraphEdge(
        edge_id=_stable_id(template_id, "edge", key),
        edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=prerequisite_id,
        target_node_id=dependent_id,
        source=EdgeSource.SEED_TEMPLATE,
        confidence=confidence,
        status=EdgeStatus.PROPOSED,
    )


def _template(
    template_id: str,
    subject: str,
    topics: list[GraphNode],
    concept_pairs: list[tuple[GraphNode, Concept]],
    mappings: list[TopicConceptMapping],
    edges: list[GraphEdge],
) -> GraphTemplate:
    return GraphTemplate(
        template_id=template_id,
        template_version="v1",
        subject=subject,
        nodes=(*topics, *(node for node, _ in concept_pairs)),
        concepts=tuple(concept for _, concept in concept_pairs),
        mappings=tuple(mappings),
        edges=tuple(edges),
    )


def algebra_foundations_template() -> GraphTemplate:
    """Return the stable v1 algebra foundations seed template."""

    template_id = "algebra-foundations"
    root = _node(template_id, GraphNodeType.TOPIC, "foundations", "Algebra foundations")
    topic_specs = [
        ("number-systems", "Number systems"),
        ("linear-equations", "Linear equations"),
        ("coordinate-geometry", "Coordinate geometry"),
        ("functions", "Functions"),
        ("polynomial-algebra", "Polynomial algebra"),
        ("quadratics", "Quadratics"),
    ]
    topics = [root]
    topics.extend(
        _node(template_id, GraphNodeType.TOPIC, key, label, parent_id=root.id)
        for key, label in topic_specs
    )
    concept_specs = [
        ("arithmetic", "Arithmetic and number sense"),
        ("fractions", "Fractions and ratios"),
        ("variables", "Variables and expressions"),
        ("equation-solving", "Equation solving"),
        ("coordinate-plane", "Coordinate plane"),
        ("function-notation", "Function notation"),
        ("polynomial-operations", "Polynomial operations"),
        ("factoring", "Factoring"),
        ("quadratic-equations", "Quadratic equations"),
    ]
    concepts = [_concept(template_id, key, title) for key, title in concept_specs]
    by_key = {concept.key: concept.id for _, concept in concepts}
    topic_by_key = {topic.label: topic.id for topic in topics}
    mappings = [
        _mapping(
            template_id, topic_by_key["Number systems"], by_key["arithmetic"],
            "number-arithmetic",
        ),
        _mapping(
            template_id, topic_by_key["Number systems"], by_key["fractions"],
            "number-fractions",
        ),
        _mapping(
            template_id, topic_by_key["Linear equations"], by_key["variables"],
            "linear-variables",
        ),
        _mapping(
            template_id, topic_by_key["Linear equations"], by_key["equation-solving"],
            "linear-solving",
        ),
        _mapping(
            template_id, topic_by_key["Coordinate geometry"], by_key["coordinate-plane"],
            "geometry-plane",
        ),
        _mapping(
            template_id, topic_by_key["Functions"], by_key["function-notation"],
            "functions-notation",
        ),
        _mapping(
            template_id, topic_by_key["Polynomial algebra"],
            by_key["polynomial-operations"], "polynomial-operations",
        ),
        _mapping(
            template_id, topic_by_key["Polynomial algebra"], by_key["factoring"],
            "polynomial-factoring",
        ),
        _mapping(
            template_id, topic_by_key["Quadratics"], by_key["quadratic-equations"],
            "quadratics-equations",
        ),
    ]
    edges = [
        _prerequisite(
            template_id, by_key["arithmetic"], by_key["fractions"], "arithmetic-fractions",
        ),
        _prerequisite(
            template_id, by_key["fractions"], by_key["variables"], "fractions-variables",
        ),
        _prerequisite(
            template_id, by_key["variables"], by_key["equation-solving"], "variables-solving",
        ),
        _prerequisite(
            template_id, by_key["coordinate-plane"], by_key["function-notation"],
            "plane-functions",
        ),
        _prerequisite(
            template_id, by_key["equation-solving"], by_key["function-notation"],
            "solving-functions",
        ),
        _prerequisite(
            template_id, by_key["polynomial-operations"], by_key["factoring"],
            "operations-factoring",
        ),
        _prerequisite(
            template_id, by_key["factoring"], by_key["quadratic-equations"],
            "factoring-quadratics",
        ),
        _prerequisite(
            template_id, by_key["equation-solving"], by_key["quadratic-equations"],
            "solving-quadratics",
        ),
    ]
    return _template(template_id, "algebra", topics, concepts, mappings, edges)


def programming_foundations_template() -> GraphTemplate:
    """Return the stable v1 programming foundations seed template."""

    template_id = "programming-foundations"
    root = _node(template_id, GraphNodeType.TOPIC, "foundations", "Programming foundations")
    topic_specs = [
        ("computational-thinking", "Computational thinking"),
        ("variables-and-types", "Variables and types"),
        ("control-flow", "Control flow"),
        ("functions", "Functions"),
        ("data-structures", "Data structures"),
        ("testing-and-debugging", "Testing and debugging"),
    ]
    topics = [root]
    topics.extend(
        _node(template_id, GraphNodeType.TOPIC, key, label, parent_id=root.id)
        for key, label in topic_specs
    )
    concept_specs = [
        ("problem-decomposition", "Problem decomposition"),
        ("variables-and-types", "Variables and types"),
        ("control-flow", "Control flow"),
        ("function-abstraction", "Function abstraction"),
        ("data-structures", "Data structures"),
        ("testing-debugging", "Testing and debugging"),
    ]
    concepts = [_concept(template_id, key, title) for key, title in concept_specs]
    by_key = {concept.key: concept.id for _, concept in concepts}
    topic_by_key = {topic.label: topic.id for topic in topics}
    mappings = [
        _mapping(
            template_id, topic_by_key["Computational thinking"],
            by_key["problem-decomposition"], "thinking-decomposition",
        ),
        _mapping(
            template_id, topic_by_key["Variables and types"],
            by_key["variables-and-types"], "variables-types",
        ),
        _mapping(
            template_id, topic_by_key["Control flow"], by_key["control-flow"],
            "control-flow",
        ),
        _mapping(
            template_id, topic_by_key["Functions"], by_key["function-abstraction"],
            "functions-abstraction",
        ),
        _mapping(
            template_id, topic_by_key["Data structures"], by_key["data-structures"],
            "structures",
        ),
        _mapping(
            template_id, topic_by_key["Testing and debugging"],
            by_key["testing-debugging"], "testing-debugging",
        ),
    ]
    edges = [
        _prerequisite(
            template_id, by_key["problem-decomposition"], by_key["variables-and-types"],
            "decomposition-variables",
        ),
        _prerequisite(
            template_id, by_key["variables-and-types"], by_key["control-flow"],
            "variables-control",
        ),
        _prerequisite(
            template_id, by_key["control-flow"], by_key["function-abstraction"],
            "control-functions",
        ),
        _prerequisite(
            template_id, by_key["function-abstraction"], by_key["data-structures"],
            "functions-structures",
        ),
        _prerequisite(
            template_id, by_key["variables-and-types"], by_key["data-structures"],
            "variables-structures",
        ),
        _prerequisite(
            template_id, by_key["control-flow"], by_key["testing-debugging"],
            "control-testing",
        ),
        _prerequisite(
            template_id, by_key["function-abstraction"], by_key["testing-debugging"],
            "functions-testing",
        ),
    ]
    return _template(template_id, "programming", topics, concepts, mappings, edges)


SEED_TEMPLATE_BUILDERS: dict[str, Callable[[], GraphTemplate]] = {
    "algebra-foundations": algebra_foundations_template,
    "programming-foundations": programming_foundations_template,
}


def seed_template(template_id: str) -> GraphTemplate:
    """Build a known template by stable identifier."""

    try:
        builder = SEED_TEMPLATE_BUILDERS[template_id]
    except KeyError:
        raise ValueError(f"Unknown seed graph template: {template_id}") from None
    return builder()
