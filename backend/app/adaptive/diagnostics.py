"""Root Cause Diagnosis Engine — deterministic prerequisite traversal.

When a learner repeatedly fails a topic, this engine traverses the
Knowledge Graph backwards to identify the underlying prerequisite
concepts responsible. Diagnosis is reproducible and explainable.

No LLM calls. Pure deterministic graph traversal.

Reference: Sprint 8 Part 4.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from app.adaptive.models import (
    DiagnosisReport,
    Explanation,
    MasteryEvaluation,
    MasteryState,
)
from app.db.models import ConceptMastery
from app.services.knowledge_graph_service import KnowledgeGraph


@dataclass
class _DiagnosisContext:
    """Internal context for diagnosis traversal."""

    topic_id: uuid.UUID
    topic_name: str
    graph: KnowledgeGraph
    mastery_map: dict[uuid.UUID, MasteryEvaluation]
    max_depth: int = 5
    min_confidence: float = 0.3


class DiagnosisEngine:
    """Root-cause diagnosis via Knowledge Graph traversal.

    When a learner repeatedly fails a topic, this engine:
    1. Traverses prerequisites backwards using the Knowledge Graph.
    2. Identifies weak prerequisites (below mastery threshold).
    3. Finds the deepest weak prerequisite as the root cause.
    4. Produces a reproducible, explainable diagnosis report.

    Usage::

        engine = DiagnosisEngine()
        report = engine.diagnose(
            topic_id=failing_topic_id,
            topic_name="Calculus",
            graph=kg,
            mastery_map={topic_id: MasteryEvaluation, ...},
        )
    """

    # Maximum depth for prerequisite traversal
    DEFAULT_MAX_DEPTH: int = 5

    # Minimum mastery score to not be considered "missing"
    DEFAULT_MASTERY_THRESHOLD: float = 0.75

    def diagnose(
        self,
        topic_id: uuid.UUID,
        topic_name: str,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        max_depth: int | None = None,
    ) -> DiagnosisReport:
        """Diagnose the root cause of struggles on a topic.

        Traverses the Knowledge Graph backwards from the failing topic
        through its prerequisites to identify missing foundation concepts.

        Args:
            topic_id: The topic the learner is failing.
            topic_name: Human-readable name of the failing topic.
            graph: The KnowledgeGraph with prerequisite edges.
            mastery_map: Current mastery evaluations keyed by topic_id.
            max_depth: Maximum prerequisite depth to traverse (default: 5).

        Returns:
            A ``DiagnosisReport`` with root cause, missing prerequisites,
            and reasoning chain.
        """
        if max_depth is None:
            max_depth = self.DEFAULT_MAX_DEPTH

        # Collect all transitive prerequisites
        prereq_depths = graph.get_transitive_prerequisites(topic_id)

        # Classify prerequisites
        missing: list[tuple[uuid.UUID, int, float]] = []   # (id, depth, score)
        weak: list[tuple[uuid.UUID, int, float]] = []      # below threshold
        strong: list[tuple[uuid.UUID, int, float]] = []    # above threshold
        not_evaluated: list[uuid.UUID] = []

        reasoning: list[str] = []
        reasoning.append(f"Diagnosing root cause for '{topic_name}' (id={topic_id})")

        for pid, depth in prereq_depths.items():
            if depth > max_depth:
                continue

            if pid not in mastery_map:
                not_evaluated.append(pid)
                reasoning.append(
                    f"  Prerequisite '{self._node_name(graph, pid)}' "
                    f"(depth {depth}) has NOT been evaluated — assumed weak."
                )
                missing.append((pid, depth, 0.0))
                continue

            meval = mastery_map[pid]
            node_name = meval.topic_name

            if meval.mastery_state in (MasteryState.NOT_STARTED,):
                reasoning.append(
                    f"  Prerequisite '{node_name}' (depth {depth}) is NOT_STARTED."
                )
                missing.append((pid, depth, meval.score))
            elif meval.score < self.DEFAULT_MASTERY_THRESHOLD:
                reasoning.append(
                    f"  Prerequisite '{node_name}' (depth {depth}) is WEAK "
                    f"(score={meval.score:.2f}, state={meval.mastery_state.value})."
                )
                weak.append((pid, depth, meval.score))
            else:
                reasoning.append(
                    f"  Prerequisite '{node_name}' (depth {depth}) is STRONG "
                    f"(score={meval.score:.2f})."
                )
                strong.append((pid, depth, meval.score))

        # Find root cause: deepest weak/missing prerequisite
        root_entry = self._find_root_cause(missing, weak, graph)

        # Build the report
        if root_entry is not None:
            root_id, root_depth, root_score = root_entry
            root_name = self._node_name(graph, root_id)
            reasoning.append(
                f"  ROOT CAUSE: '{root_name}' (depth {root_depth}, "
                f"score={root_score:.2f}) — deepest weak prerequisite."
            )
        else:
            root_id = None
            root_name = None
            if not missing and not weak:
                reasoning.append(
                    "  No weak prerequisites found — the issue may be "
                    "with the topic content itself, not prerequisites."
                )
            else:
                reasoning.append(
                    "  Unable to determine a single root cause from "
                    "available data."
                )

        # All supporting concepts (all prerequisites examined)
        all_prereqs = [pid for pid, _, _ in missing + weak + strong]
        all_prereqs.sort()

        # Missing prerequisites (NOT_STARTED or not evaluated)
        missing_ids = [pid for pid, _, _ in missing]

        # Confidence based on how many prerequisites were actually evaluated
        total_found = len(missing) + len(weak) + len(strong)
        total_prereqs = len(prereq_depths)
        if total_prereqs == 0:
            confidence = 0.0
        else:
            confidence = min(total_found / total_prereqs, 1.0)

        return DiagnosisReport(
            topic_id=topic_id,
            topic_name=topic_name,
            root_concept_id=root_id,
            root_concept_name=root_name,
            supporting_concepts=all_prereqs,
            missing_prerequisites=missing_ids,
            reasoning_chain=reasoning,
            confidence=round(confidence, 4),
            explanation=Explanation(
                decision="diagnose",
                reason=(
                    f"Root cause: {root_name}" if root_name
                    else "No definitive root cause identified"
                ),
                evidence=[
                    f"Examined {total_found}/{total_prereqs} prerequisites.",
                    f"Missing/unevaluated: {len(missing)}",
                    f"Weak (below threshold): {len(weak)}",
                    f"Strong (above threshold): {len(strong)}",
                ],
                metrics_used={
                    "prerequisites_examined": float(total_found),
                    "missing_count": float(len(missing)),
                    "weak_count": float(len(weak)),
                    "strong_count": float(len(strong)),
                },
                confidence=confidence,
                rules_triggered=["root_cause_diagnosis"],
                prerequisites_examined=[
                    self._node_name(graph, pid)
                    for pid in all_prereqs[:20]  # limit for readability
                ],
            ),
        )

    def diagnose_simple(
        self,
        topic_id: uuid.UUID,
        topic_name: str,
        graph: KnowledgeGraph,
        mastery_scores: dict[uuid.UUID, float],
        threshold: float = 0.75,
        max_depth: int = 5,
    ) -> DiagnosisReport:
        """Simplified diagnosis using raw mastery scores.

        Convenience wrapper that doesn't require full MasteryEvaluation objects.

        Args:
            topic_id: The failing topic ID.
            topic_name: The failing topic name.
            graph: KnowledgeGraph with prerequisite edges.
            mastery_scores: Raw mastery scores (0.0–1.0) keyed by topic_id.
            threshold: Mastery threshold.
            max_depth: Maximum prerequisite depth.

        Returns:
            A ``DiagnosisReport``.
        """
        eval_map: dict[uuid.UUID, MasteryEvaluation] = {}
        for tid, score in mastery_scores.items():
            state = MasteryState.MASTERED if score >= threshold else MasteryState.PRACTICING
            eval_map[tid] = MasteryEvaluation(
                topic_id=tid,
                topic_name=self._node_name(graph, tid),
                mastery_state=state,
                score=score,
                confidence=0.5,
            )
        return self.diagnose(
            topic_id=topic_id,
            topic_name=topic_name,
            graph=graph,
            mastery_map=eval_map,
            max_depth=max_depth,
        )

    # ── helpers ────────────────────────────────────────────────────────────

    def _find_root_cause(
        self,
        missing: list[tuple[uuid.UUID, int, float]],
        weak: list[tuple[uuid.UUID, int, float]],
        graph: KnowledgeGraph,
    ) -> tuple[uuid.UUID, int, float] | None:
        """Find the deepest weak/missing prerequisite as the root cause.

        Priority:
        1. Deepest missing (NOT_STARTED) prerequisite.
        2. Deepest weak (below threshold) prerequisite.
        3. None if no weak or missing prerequisites.

        Ties broken by lowest score.
        """
        candidates = list(missing) + list(weak)
        if not candidates:
            return None

        # Sort by depth (descending), then by score (ascending — weakest first)
        candidates.sort(key=lambda x: (-x[1], x[2]))
        return candidates[0]

    def _node_name(self, graph: KnowledgeGraph, topic_id: uuid.UUID) -> str:
        """Get the human-readable name of a topic node."""
        node = graph.nodes.get(topic_id)
        if node is not None:
            return node.name
        return f"topic-{topic_id}"

    def get_missing_prerequisites(
        self,
        topic_id: uuid.UUID,
        graph: KnowledgeGraph,
        mastery_scores: dict[uuid.UUID, float],
        threshold: float = 0.75,
    ) -> list[uuid.UUID]:
        """Quick check: return prerequisite IDs below mastery threshold.

        Args:
            topic_id: The topic to check prerequisites for.
            graph: KnowledgeGraph.
            mastery_scores: Current mastery scores keyed by topic_id.
            threshold: Mastery threshold.

        Returns:
            List of prerequisite topic IDs that are below threshold.
        """
        prereqs = graph.get_prerequisites(topic_id)
        return [
            pid for pid in prereqs
            if mastery_scores.get(pid, 0.0) < threshold
        ]
