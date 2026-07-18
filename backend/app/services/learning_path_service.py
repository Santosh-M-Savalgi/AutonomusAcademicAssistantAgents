"""Learning Path Engine — deterministic learning path generation (Phase B).

Generates ordered topic sequences using the Knowledge Graph, mastery scores,
completed topics, and preferred learning mode. All pure deterministic logic.

Architecture reference: Section 14 (Adaptive Learning Pipeline).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from app.services.knowledge_graph_service import KnowledgeGraph


class LearningMode(str, enum.Enum):
    """Learning path generation modes."""
    BEGINNER = "beginner"       # Slower, includes all prerequisites
    STANDARD = "standard"       # Normal prerequisite-aware ordering
    FAST_TRACK = "fast_track"   # Skips mastered, prioritizes efficiency


@dataclass
class LearningPathStep:
    """A single step in a generated learning path."""

    topic_id: uuid.UUID
    topic_name: str
    topic_slug: str
    difficulty: str
    depth: int                   # 0 = no prerequisites needed, 1+ = depth
    mastery_score: float          # 0.0–1.0, current mastery
    is_completed: bool            # mastery >= threshold
    is_blocked: bool              # has unmet prerequisites
    unmet_prerequisites: list[uuid.UUID] = field(default_factory=list)


@dataclass
class LearningPath:
    """A generated ordered learning path."""

    mode: LearningMode
    steps: list[LearningPathStep]
    total_topics: int
    completed_topics: int
    remaining_topics: int

    @property
    def next_topic_id(self) -> uuid.UUID | None:
        """The first uncompleted, unblocked topic in the path."""
        for step in self.steps:
            if not step.is_completed and not step.is_blocked:
                return step.topic_id
        return None

    @property
    def is_complete(self) -> bool:
        """True when all topics in the path are mastered."""
        return self.remaining_topics == 0


# ── Learning Path Service ──────────────────────────────────────────────────


class LearningPathService:
    """Generates deterministic learning paths from syllabus + mastery data.

    Usage::

        svc = LearningPathService()
        path = svc.generate(
            graph=kg,
            syllabus_topic_ids=[...],
            mastery_scores={topic_id: 0.85, ...},
            mode=LearningMode.STANDARD,
        )
    """

    def generate(
        self,
        graph: KnowledgeGraph,
        syllabus_topic_ids: list[uuid.UUID],
        mastery_scores: dict[uuid.UUID, float],
        mode: LearningMode = LearningMode.STANDARD,
    ) -> LearningPath:
        """Generate an ordered learning path.

        Args:
            graph: The KnowledgeGraph with all topics and edges.
            syllabus_topic_ids: The topic IDs that belong to the syllabus.
            mastery_scores: Current mastery score per topic (0.0–1.0).
                Topics not in this dict are treated as unstarted (score=0).
            mode: The learning path generation mode.

        Returns:
            A ``LearningPath`` with ordered steps.
        """
        # 1. Get all topics in the graph that are part of the syllabus.
        syllabus_topics = [
            graph.nodes[tid]
            for tid in syllabus_topic_ids
            if tid in graph.nodes
        ]

        # 2. Build a subgraph of just the syllabus topics for topological sort.
        subgraph = self._build_subgraph(graph, syllabus_topic_ids)
        topo_order = subgraph.topological_sort()
        if not topo_order:
            # Cycle detected — fall back to syllabus topic order
            topo_order = [t.id for t in syllabus_topics]

        # 3. Score each topic with mastery and completion status.
        step_map: dict[uuid.UUID, LearningPathStep] = {}
        for tid in topo_order:
            node = graph.nodes[tid]
            score = mastery_scores.get(tid, 0.0)
            threshold = node.mastery_threshold
            prereqs = graph.get_prerequisites(tid)
            unmet: list[uuid.UUID] = []
            for pid in prereqs:
                if pid not in graph.nodes:
                    raise ValueError(
                        f"Graph inconsistency: prerequisite {pid} of topic {tid} "
                        f"({node.name}) exists in edges but is missing from graph.nodes. "
                        f"This indicates an edge referencing a topic outside the current "
                        f"syllabus. Run build_graph_from_models() which filters these."
                    )
                if mastery_scores.get(pid, 0.0) < graph.nodes[pid].mastery_threshold:
                    unmet.append(pid)
            step_map[tid] = LearningPathStep(
                topic_id=tid,
                topic_name=node.name,
                topic_slug=node.slug,
                difficulty=node.difficulty,
                depth=self._compute_max_depth(graph, tid, syllabus_topic_ids),
                mastery_score=score,
                is_completed=score >= threshold,
                is_blocked=len(unmet) > 0,
                unmet_prerequisites=unmet,
            )

        # 4. Apply mode-specific ordering.
        ordered_steps = self._apply_mode(step_map, topo_order, graph, mode)

        completed_count = sum(1 for s in ordered_steps if s.is_completed)

        return LearningPath(
            mode=mode,
            steps=ordered_steps,
            total_topics=len(ordered_steps),
            completed_topics=completed_count,
            remaining_topics=len(ordered_steps) - completed_count,
        )

    # ── helpers ─────────────────────────────────────────────────────────

    def _build_subgraph(
        self,
        graph: KnowledgeGraph,
        topic_ids: list[uuid.UUID],
    ) -> KnowledgeGraph:
        """Build a subgraph containing only the given topic IDs."""
        id_set = set(topic_ids)
        sub = KnowledgeGraph()
        for tid in topic_ids:
            if tid in graph.nodes:
                sub.add_node(graph.nodes[tid])
        for edge in graph.edges.values():
            if edge.parent_id in id_set and edge.child_id in id_set:
                sub.add_edge(edge)
        return sub

    def _compute_max_depth(
        self,
        graph: KnowledgeGraph,
        topic_id: uuid.UUID,
        syllabus_ids: list[uuid.UUID],
    ) -> int:
        """Compute the maximum prerequisite depth within the syllabus."""
        id_set = set(syllabus_ids)
        prereqs = graph.get_transitive_prerequisites(topic_id)
        if not prereqs:
            return 0
        return max(
            (d for pid, d in prereqs.items() if pid in id_set),
            default=0,
        )

    def _apply_mode(
        self,
        step_map: dict[uuid.UUID, LearningPathStep],
        topo_order: list[uuid.UUID],
        graph: KnowledgeGraph,
        mode: LearningMode,
    ) -> list[LearningPathStep]:
        """Apply mode-specific reordering/filtering to the path."""
        steps = [step_map[tid] for tid in topo_order]

        if mode == LearningMode.BEGINNER:
            return self._beginner_path(steps, graph)
        elif mode == LearningMode.FAST_TRACK:
            return self._fast_track_path(steps, graph)
        else:
            return self._standard_path(steps, graph)

    def _standard_path(
        self,
        steps: list[LearningPathStep],
        graph: KnowledgeGraph,
    ) -> list[LearningPathStep]:
        """Standard path: topological order, completed topics kept for reference."""
        return steps

    def _beginner_path(
        self,
        steps: list[LearningPathStep],
        graph: KnowledgeGraph,
    ) -> list[LearningPathStep]:
        """Beginner path: topological order, completed topics kept.

        Same as standard — topological order already ensures prerequisites
        come first, which is ideal for beginners.
        """
        return steps

    def _fast_track_path(
        self,
        steps: list[LearningPathStep],
        graph: KnowledgeGraph,
    ) -> list[LearningPathStep]:
        """Fast-track: skip completed topics, keep prerequisite ordering.

        Completed topics are removed from the path (they're already mastered).
        Uncompleted topics are kept, but blocked ones remain as they may
        become unblocked as prerequisites are completed.
        """
        return [s for s in steps if not s.is_completed]

    # ── utility queries ─────────────────────────────────────────────────

    def get_next_topic(
        self,
        graph: KnowledgeGraph,
        syllabus_topic_ids: list[uuid.UUID],
        mastery_scores: dict[uuid.UUID, float],
        mode: LearningMode = LearningMode.STANDARD,
    ) -> uuid.UUID | None:
        """Return the next ready topic ID, or None if all are complete."""
        path = self.generate(graph, syllabus_topic_ids, mastery_scores, mode)
        return path.next_topic_id
