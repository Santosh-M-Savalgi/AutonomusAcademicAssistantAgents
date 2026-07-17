"""Tests for Knowledge Graph Service (Phase A).

Covers: graph construction, cycle detection, topological sort, BFS, DFS,
transitive prerequisites, ancestors.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    TopicEdgeData,
    TopicNode,
    build_graph_from_models,
)


# ── fixtures ───────────────────────────────────────────────────────────────


def _make_node(name: str, difficulty: str = "beginner") -> TopicNode:
    return TopicNode(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        difficulty=difficulty,
        learning_depth=15,
    )


def _make_edge(
    parent_id: uuid.UUID,
    child_id: uuid.UUID,
    weight: float = 1.0,
) -> TopicEdgeData:
    return TopicEdgeData(
        id=uuid.uuid4(),
        parent_id=parent_id,
        child_id=child_id,
        relationship_type="direct_prerequisite",
        weight=weight,
    )


@pytest.fixture
def linear_graph() -> KnowledgeGraph:
    """A -> B -> C -> D  (A depends on B, B on C, C on D)."""
    d = _make_node("D")
    c = _make_node("C")
    b = _make_node("B")
    a = _make_node("A")
    return KnowledgeGraph.build(
        [a, b, c, d],
        [
            _make_edge(a.id, b.id),
            _make_edge(b.id, c.id),
            _make_edge(c.id, d.id),
        ],
    )


@pytest.fixture
def diamond_graph() -> KnowledgeGraph:
    """A -> B, A -> C, B -> D, C -> D  (diamond shape)."""
    d = _make_node("D")
    c = _make_node("C")
    b = _make_node("B")
    a = _make_node("A")
    return KnowledgeGraph.build(
        [a, b, c, d],
        [
            _make_edge(a.id, b.id),
            _make_edge(a.id, c.id),
            _make_edge(b.id, d.id),
            _make_edge(c.id, d.id),
        ],
    )


@pytest.fixture
def cycle_graph() -> KnowledgeGraph:
    """A -> B -> C -> A  (cycle)."""
    c = _make_node("C")
    b = _make_node("B")
    a = _make_node("A")
    return KnowledgeGraph.build(
        [a, b, c],
        [
            _make_edge(a.id, b.id),
            _make_edge(b.id, c.id),
            _make_edge(c.id, a.id),
        ],
    )


@pytest.fixture
def empty_graph() -> KnowledgeGraph:
    return KnowledgeGraph()


# ── graph construction ─────────────────────────────────────────────────────


class TestGraphConstruction:
    def test_empty_graph(self, empty_graph: KnowledgeGraph) -> None:
        assert empty_graph.node_count == 0
        assert empty_graph.edge_count == 0

    def test_linear_graph_counts(self, linear_graph: KnowledgeGraph) -> None:
        assert linear_graph.node_count == 4
        assert linear_graph.edge_count == 3

    def test_prerequisites_linear(self, linear_graph: KnowledgeGraph) -> None:
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")
        b = next(n for n in linear_graph.nodes.values() if n.name == "B")
        c = next(n for n in linear_graph.nodes.values() if n.name == "C")
        d = next(n for n in linear_graph.nodes.values() if n.name == "D")

        # A depends on B
        assert linear_graph.get_prerequisites(a.id) == {b.id}
        # B depends on C
        assert linear_graph.get_prerequisites(b.id) == {c.id}
        # D has no prerequisites
        assert linear_graph.get_prerequisites(d.id) == set()

    def test_dependents_linear(self, linear_graph: KnowledgeGraph) -> None:
        b = next(n for n in linear_graph.nodes.values() if n.name == "B")
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")

        # B's dependents: A depends on B
        assert linear_graph.get_dependents(b.id) == {a.id}

    def test_diamond_dependents(self, diamond_graph: KnowledgeGraph) -> None:
        d = next(n for n in diamond_graph.nodes.values() if n.name == "D")
        b = next(n for n in diamond_graph.nodes.values() if n.name == "B")
        c = next(n for n in diamond_graph.nodes.values() if n.name == "C")

        # Both B and C depend on D
        dependents = diamond_graph.get_dependents(d.id)
        assert dependents == {b.id, c.id}


# ── cycle detection ────────────────────────────────────────────────────────


class TestCycleDetection:
    def test_linear_no_cycle(self, linear_graph: KnowledgeGraph) -> None:
        assert not linear_graph.has_cycle()
        assert linear_graph.find_cycle_path() is None

    def test_diamond_no_cycle(self, diamond_graph: KnowledgeGraph) -> None:
        assert not diamond_graph.has_cycle()
        assert diamond_graph.find_cycle_path() is None

    def test_cycle_detected(self, cycle_graph: KnowledgeGraph) -> None:
        assert cycle_graph.has_cycle()

    def test_cycle_path_found(self, cycle_graph: KnowledgeGraph) -> None:
        path = cycle_graph.find_cycle_path()
        assert path is not None
        # Should be a cycle: first == last
        assert path[0] == path[-1]
        assert len(path) >= 3

    def test_empty_no_cycle(self, empty_graph: KnowledgeGraph) -> None:
        assert not empty_graph.has_cycle()
        assert empty_graph.find_cycle_path() is None

    def test_single_node_no_cycle(self) -> None:
        n = _make_node("solo")
        kg = KnowledgeGraph.build([n], [])
        assert not kg.has_cycle()

    def test_self_loop_is_cycle(self) -> None:
        n = _make_node("self")
        kg = KnowledgeGraph.build([n], [_make_edge(n.id, n.id)])
        assert kg.has_cycle()
        path = kg.find_cycle_path()
        assert path is not None
        assert path[0] == path[-1] == n.id


# ── topological sort ───────────────────────────────────────────────────────


class TestTopologicalSort:
    def test_linear_topo(self, linear_graph: KnowledgeGraph) -> None:
        order = linear_graph.topological_sort()
        names = [linear_graph.nodes[nid].name for nid in order]
        # D must come first (no deps), then C, then B, then A
        assert names.index("D") < names.index("C")
        assert names.index("C") < names.index("B")
        assert names.index("B") < names.index("A")

    def test_diamond_topo(self, diamond_graph: KnowledgeGraph) -> None:
        order = diamond_graph.topological_sort()
        names = [diamond_graph.nodes[nid].name for nid in order]
        # D must come first
        assert names.index("D") < names.index("B")
        assert names.index("D") < names.index("C")
        assert names.index("B") < names.index("A")
        assert names.index("C") < names.index("A")

    def test_cycle_returns_empty(self, cycle_graph: KnowledgeGraph) -> None:
        assert cycle_graph.topological_sort() == []

    def test_empty_topo(self, empty_graph: KnowledgeGraph) -> None:
        assert empty_graph.topological_sort() == []


# ── BFS ────────────────────────────────────────────────────────────────────


class TestBFS:
    def test_bfs_linear(self, linear_graph: KnowledgeGraph) -> None:
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")
        order = linear_graph.bfs(a.id)
        names = [linear_graph.nodes[nid].name for nid in order]
        # BFS from A: A first, then B, then C, then D
        assert names[0] == "A"
        assert names.index("B") < names.index("C") < names.index("D")

    def test_bfs_diamond(self, diamond_graph: KnowledgeGraph) -> None:
        a = next(n for n in diamond_graph.nodes.values() if n.name == "A")
        order = diamond_graph.bfs(a.id)
        names = [diamond_graph.nodes[nid].name for nid in order]
        # BFS from A: A first, then {B, C} level 1, then D level 2
        assert names[0] == "A"
        assert names.index("B") < names.index("D")
        assert names.index("C") < names.index("D")

    def test_bfs_nonexistent(self, empty_graph: KnowledgeGraph) -> None:
        assert empty_graph.bfs(uuid.uuid4()) == []

    def test_bfs_single_node(self) -> None:
        n = _make_node("solo")
        kg = KnowledgeGraph.build([n], [])
        assert kg.bfs(n.id) == [n.id]


# ── DFS ────────────────────────────────────────────────────────────────────


class TestDFS:
    def test_dfs_linear(self, linear_graph: KnowledgeGraph) -> None:
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")
        order = linear_graph.dfs(a.id)
        names = [linear_graph.nodes[nid].name for nid in order]
        # DFS from A goes deep first
        assert names[0] == "A"

    def test_dfs_nonexistent(self, empty_graph: KnowledgeGraph) -> None:
        assert empty_graph.dfs(uuid.uuid4()) == []

    def test_dfs_single_node(self) -> None:
        n = _make_node("solo")
        kg = KnowledgeGraph.build([n], [])
        assert kg.dfs(n.id) == [n.id]


# ── transitive prerequisites ────────────────────────────────────────────────


class TestTransitivePrerequisites:
    def test_linear_transitive(self, linear_graph: KnowledgeGraph) -> None:
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")
        b = next(n for n in linear_graph.nodes.values() if n.name == "B")
        c = next(n for n in linear_graph.nodes.values() if n.name == "C")
        d = next(n for n in linear_graph.nodes.values() if n.name == "D")

        prereqs = linear_graph.get_transitive_prerequisites(a.id)
        assert prereqs == {b.id: 1, c.id: 2, d.id: 3}

    def test_d_has_no_prereqs(self, linear_graph: KnowledgeGraph) -> None:
        d = next(n for n in linear_graph.nodes.values() if n.name == "D")
        assert linear_graph.get_transitive_prerequisites(d.id) == {}

    def test_nonexistent(self, empty_graph: KnowledgeGraph) -> None:
        assert empty_graph.get_transitive_prerequisites(uuid.uuid4()) == {}


# ── ancestors ──────────────────────────────────────────────────────────────


class TestAncestors:
    def test_d_ancestors_linear(self, linear_graph: KnowledgeGraph) -> None:
        d = next(n for n in linear_graph.nodes.values() if n.name == "D")
        c = next(n for n in linear_graph.nodes.values() if n.name == "C")
        b = next(n for n in linear_graph.nodes.values() if n.name == "B")
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")

        ancestors = linear_graph.get_all_ancestors(d.id)
        assert ancestors == {c.id, b.id, a.id}

    def test_a_has_no_ancestors(self, linear_graph: KnowledgeGraph) -> None:
        a = next(n for n in linear_graph.nodes.values() if n.name == "A")
        assert linear_graph.get_all_ancestors(a.id) == set()


# ── build_graph_from_models ────────────────────────────────────────────────


class TestBuildGraphFromModels:
    def test_builds_from_sqlalchemy_models(self) -> None:
        """Integration-style test using simplified model-like objects."""

        class FakeTopic:
            def __init__(self, id, name, slug, difficulty, learning_depth, mastery_threshold):
                self.id = id
                self.name = name
                self.slug = slug
                self.difficulty = difficulty
                self.learning_depth = learning_depth
                self.mastery_threshold = mastery_threshold

        class FakeEdge:
            def __init__(self, id, parent_topic_id, child_topic_id, relationship_type, weight):
                self.id = id
                self.parent_topic_id = parent_topic_id
                self.child_topic_id = child_topic_id
                self.relationship_type = relationship_type
                self.weight = weight

        # Simulate enum-like .value access
        class FakeEnum:
            def __init__(self, value):
                self.value = value

        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        edge_id = uuid.uuid4()

        topics = [
            FakeTopic(t1_id, "Python", "python", FakeEnum("beginner"), 30, 0.80),
            FakeTopic(t2_id, "Loops", "loops", FakeEnum("beginner"), 15, 0.75),
        ]
        edges = [
            FakeEdge(edge_id, t1_id, t2_id, FakeEnum("direct_prerequisite"), 0.9),
        ]

        kg = build_graph_from_models(topics, edges)
        assert kg.node_count == 2
        assert kg.edge_count == 1
        assert kg.get_prerequisites(t1_id) == {t2_id}
