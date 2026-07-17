"""Knowledge Graph Service — pure deterministic graph operations (Phase A).

Operates on in-memory adjacency-list representations built from Sprint 1
repository data. No LLM calls, no DB writes. All algorithms are deterministic
and independently testable.

Architecture reference: Sections 7.1–7.9.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field


# ── domain types ───────────────────────────────────────────────────────────


@dataclass
class TopicNode:
    """Lightweight in-memory topic for graph algorithms."""

    id: uuid.UUID
    name: str
    slug: str
    difficulty: str  # beginner | intermediate | advanced
    learning_depth: int
    mastery_threshold: float = 0.75


@dataclass
class TopicEdgeData:
    """Lightweight in-memory edge for graph algorithms."""

    id: uuid.UUID
    parent_id: uuid.UUID   # topic that *depends on* child
    child_id: uuid.UUID    # the prerequisite topic
    relationship_type: str  # direct_prerequisite | related_concept | part_of
    weight: float = 1.0


@dataclass
class KnowledgeGraph:
    """In-memory directed graph built from Topic + TopicEdge data.

    Nodes are indexed by ``id``. Edges are stored as an adjacency list
    (both outgoing and incoming) for efficient traversal in both directions.
    """

    nodes: dict[uuid.UUID, TopicNode] = field(default_factory=dict)
    # parent_id -> set of child_ids  (what this topic depends on)
    outgoing: dict[uuid.UUID, set[uuid.UUID]] = field(default_factory=dict)
    # child_id -> set of parent_ids  (what depends on this topic)
    incoming: dict[uuid.UUID, set[uuid.UUID]] = field(default_factory=dict)

    edges: dict[uuid.UUID, TopicEdgeData] = field(default_factory=dict)

    # ── construction ────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        topics: list[TopicNode],
        edges: list[TopicEdgeData],
    ) -> KnowledgeGraph:
        """Construct a KnowledgeGraph from topic and edge lists."""
        kg = cls()
        for t in topics:
            kg.add_node(t)
        for e in edges:
            kg.add_edge(e)
        return kg

    def add_node(self, node: TopicNode) -> None:
        self.nodes[node.id] = node
        self.outgoing.setdefault(node.id, set())
        self.incoming.setdefault(node.id, set())

    def add_edge(self, edge: TopicEdgeData) -> None:
        self.edges[edge.id] = edge
        self.outgoing.setdefault(edge.parent_id, set()).add(edge.child_id)
        self.incoming.setdefault(edge.child_id, set()).add(edge.parent_id)
        # Ensure both endpoints exist in sets
        self.outgoing.setdefault(edge.child_id, set())
        self.incoming.setdefault(edge.parent_id, set())

    # ── queries ─────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def get_prerequisites(self, topic_id: uuid.UUID) -> set[uuid.UUID]:
        """Direct prerequisites (child nodes) of a topic."""
        return self.outgoing.get(topic_id, set())

    def get_dependents(self, topic_id: uuid.UUID) -> set[uuid.UUID]:
        """Topics that directly depend on this one (parent nodes)."""
        return self.incoming.get(topic_id, set())

    # ── cycle detection ─────────────────────────────────────────────────

    def has_cycle(self) -> bool:
        """Return True if the graph contains any directed cycle.

        Uses Kahn's algorithm (topological sort attempt): if not all nodes
        are processed, a cycle exists.
        """
        return not self._topological_sort_success()

    def _topological_sort_success(self) -> bool:
        """Return True iff a full topological ordering exists (no cycles)."""
        dep_count: dict[uuid.UUID, int] = {
            nid: len(self.outgoing.get(nid, set())) for nid in self.nodes
        }
        queue: deque[uuid.UUID] = deque(
            nid for nid, deg in dep_count.items() if deg == 0
        )
        processed = 0
        while queue:
            node = queue.popleft()
            processed += 1
            for parent in self.incoming.get(node, set()):
                dep_count[parent] -= 1
                if dep_count[parent] == 0:
                    queue.append(parent)
        return processed == len(self.nodes)

    def find_cycle_path(self) -> list[uuid.UUID] | None:
        """Return one cycle path as a list of node ids, or None.

        Uses DFS with recursion-stack tracking (white/gray/black coloring).
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[uuid.UUID, int] = {nid: WHITE for nid in self.nodes}
        parent: dict[uuid.UUID, uuid.UUID | None] = {
            nid: None for nid in self.nodes
        }

        def _dfs(node: uuid.UUID) -> list[uuid.UUID] | None:
            color[node] = GRAY
            for child in self.outgoing.get(node, set()):
                if color[child] == GRAY:
                    # cycle found — reconstruct path
                    path = [child, node]
                    cur = node
                    while parent.get(cur) is not None and parent[cur] != child:
                        cur = parent[cur]  # type: ignore[assignment]
                        path.append(cur)
                    path.append(child)
                    path.reverse()
                    return path
                if color[child] == WHITE:
                    parent[child] = node
                    result = _dfs(child)
                    if result is not None:
                        return result
            color[node] = BLACK
            return None

        for nid in self.nodes:
            if color[nid] == WHITE:
                cycle = _dfs(nid)
                if cycle is not None:
                    return cycle
        return None

    # ── traversal ───────────────────────────────────────────────────────

    def bfs(self, start_id: uuid.UUID) -> list[uuid.UUID]:
        """Breadth-first traversal order from *start_id*.

        Follows outgoing edges (dependencies). Returns node ids in BFS order.
        """
        if start_id not in self.nodes:
            return []
        visited: set[uuid.UUID] = {start_id}
        queue: deque[uuid.UUID] = deque([start_id])
        order: list[uuid.UUID] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for child in sorted(self.outgoing.get(node, set()), key=str):
                if child not in visited:
                    visited.add(child)
                    queue.append(child)
        return order

    def dfs(self, start_id: uuid.UUID) -> list[uuid.UUID]:
        """Depth-first traversal order from *start_id*.

        Follows outgoing edges (dependencies). Returns node ids in DFS order.
        """
        if start_id not in self.nodes:
            return []
        visited: set[uuid.UUID] = set()
        order: list[uuid.UUID] = []

        def _dfs(node: uuid.UUID) -> None:
            visited.add(node)
            order.append(node)
            for child in sorted(self.outgoing.get(node, set()), key=str):
                if child not in visited:
                    _dfs(child)

        _dfs(start_id)
        return order

    def topological_sort(self) -> list[uuid.UUID]:
        """Return a topological ordering of all nodes (Kahn's algorithm).

        Ordering respects prerequisite direction: nodes with *no* prerequisites
        (no outgoing edges) come first, so a student can learn in order.

        Returns the empty list if the graph contains a cycle.
        """
        # "Out-degree" = number of prerequisites a node has (following outgoing
        # edges from parent to child — the dependency direction).
        dep_count: dict[uuid.UUID, int] = {
            nid: len(self.outgoing.get(nid, set())) for nid in self.nodes
        }
        # Nodes with zero prerequisites go first.
        queue: deque[uuid.UUID] = deque(
            nid for nid, deg in dep_count.items() if deg == 0
        )
        order: list[uuid.UUID] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            # When we "remove" this node, every parent that depended on it
            # loses one prerequisite.
            for parent in sorted(self.incoming.get(node, set()), key=str):
                dep_count[parent] -= 1
                if dep_count[parent] == 0:
                    queue.append(parent)

        if len(order) != len(self.nodes):
            return []  # cycle detected
        return order

    def get_transitive_prerequisites(
        self, topic_id: uuid.UUID
    ) -> dict[uuid.UUID, int]:
        """Return all transitive prerequisites mapped to their depth.

        Uses BFS; depth 1 = direct prerequisite, 2+ = indirect.
        Returns empty dict if topic_id not in graph.
        """
        if topic_id not in self.nodes:
            return {}
        result: dict[uuid.UUID, int] = {}
        visited: set[uuid.UUID] = {topic_id}
        queue: deque[tuple[uuid.UUID, int]] = deque([(topic_id, 0)])

        while queue:
            node, depth = queue.popleft()
            for child in self.outgoing.get(node, set()):
                if child not in visited:
                    visited.add(child)
                    child_depth = depth + 1
                    result[child] = child_depth
                    queue.append((child, child_depth))
        return result

    def get_all_ancestors(self, topic_id: uuid.UUID) -> set[uuid.UUID]:
        """Return all ancestors (topics that depend on this one, transitively)."""
        if topic_id not in self.nodes:
            return set()
        ancestors: set[uuid.UUID] = set()
        queue: deque[uuid.UUID] = deque([topic_id])
        visited: set[uuid.UUID] = {topic_id}

        while queue:
            node = queue.popleft()
            for parent in self.incoming.get(node, set()):
                if parent not in visited:
                    visited.add(parent)
                    ancestors.add(parent)
                    queue.append(parent)
        return ancestors


# ── factory helpers (bridge from repository models) ────────────────────────


def build_graph_from_models(
    topics: list,  # SQLAlchemy Topic models
    edges: list,   # SQLAlchemy TopicEdge models
) -> KnowledgeGraph:
    """Build a KnowledgeGraph from Sprint 1 SQLAlchemy model instances.

    Args:
        topics: Iterable of ``app.db.models.Topic`` instances.
        edges: Iterable of ``app.db.models.TopicEdge`` instances.

    Returns:
        A fully constructed ``KnowledgeGraph``.
    """
    kg = KnowledgeGraph()
    for t in topics:
        kg.add_node(
            TopicNode(
                id=t.id,
                name=t.name,
                slug=t.slug,
                difficulty=t.difficulty.value
                if hasattr(t.difficulty, "value")
                else str(t.difficulty),
                learning_depth=t.learning_depth,
                mastery_threshold=t.mastery_threshold,
            )
        )
    for e in edges:
        kg.add_edge(
            TopicEdgeData(
                id=e.id,
                parent_id=e.parent_topic_id,
                child_id=e.child_topic_id,
                relationship_type=e.relationship_type.value
                if hasattr(e.relationship_type, "value")
                else str(e.relationship_type),
                weight=e.weight,
            )
        )
    return kg
