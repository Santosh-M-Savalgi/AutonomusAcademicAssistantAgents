"""Adaptive Routing Engine — deterministic routing policies (Phase D).

Implements the routing decisions described in Section 14.2 of the architecture.
All decisions are pure deterministic functions — no LLM calls.

Possible routing decisions:
- NEXT_TOPIC: advance to the next topic in the learning path
- REVIEW_TOPIC: review (re-teach) the current topic
- REPEAT_TOPIC: retry the same topic with alternate quiz/teaching
- REVISIT_PREREQUISITE: pause current topic, go to weakest prerequisite
- READY_FOR_QUIZ: the topic is ready for quiz assessment
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from app.services.knowledge_graph_service import KnowledgeGraph
from app.services.learning_path_service import LearningPath, LearningPathService
from app.services.mastery_service import MasteryEngine, WeakConceptReport


class RoutingDecision(str, enum.Enum):
    """Deterministic routing decisions for the adaptive engine."""

    NEXT_TOPIC = "NEXT_TOPIC"
    """Advance to the next topic in the learning path."""

    REVIEW_TOPIC = "REVIEW_TOPIC"
    """Re-teach the current topic (score below threshold, no weak ancestor)."""

    REPEAT_TOPIC = "REPEAT_TOPIC"
    """Retry the same topic with alternate approach (below mastery, first retry)."""

    REVISIT_PREREQUISITE = "REVISIT_PREREQUISITE"
    """Pause current topic, navigate to weakest identified prerequisite."""

    READY_FOR_QUIZ = "READY_FOR_QUIZ"
    """Topic prerequisites are met — student is ready for quiz assessment."""


@dataclass
class RoutingResult:
    """The output of a routing decision."""

    decision: RoutingDecision
    current_topic_id: uuid.UUID | None
    next_topic_id: uuid.UUID | None       # for NEXT_TOPIC or REVISIT_PREREQUISITE
    weak_concept_report: WeakConceptReport | None
    reason: str


# ── Adaptive Router ─────────────────────────────────────────────────────────


class AdaptiveRouter:
    """Deterministic adaptive routing engine.

    Usage::

        router = AdaptiveRouter()
        result = router.route(
            graph=kg,
            mastery_scores={...},
            current_topic_id=tid,
            syllabus_topic_ids=[...],
            quiz_score=0.65,
            attempts_on_current=2,
        )
    """

    # Re-teach threshold: below this, a topic needs re-teaching
    RETEACH_THRESHOLD = 0.50

    # Mastery threshold: at or above this, the topic is considered mastered
    MASTERY_THRESHOLD = 0.70

    # Max retry attempts before escalating
    MAX_RETRY_ATTEMPTS = 3

    def __init__(
        self,
        mastery_engine: MasteryEngine | None = None,
        path_service: LearningPathService | None = None,
    ):
        self.mastery_engine = mastery_engine or MasteryEngine()
        self.path_service = path_service or LearningPathService()

    def route(
        self,
        graph: KnowledgeGraph,
        mastery_scores: dict[uuid.UUID, float],
        current_topic_id: uuid.UUID,
        syllabus_topic_ids: list[uuid.UUID],
        quiz_score: float | None = None,
        attempts_on_current: int = 0,
    ) -> RoutingResult:
        """Determine the next routing decision.

        Args:
            graph: The KnowledgeGraph.
            mastery_scores: Current mastery scores per topic (0.0–1.0).
            current_topic_id: The topic the student is currently on.
            syllabus_topic_ids: All topic IDs in the syllabus.
            quiz_score: The student's latest quiz score on current topic (0.0–1.0).
                If None, the student hasn't taken a quiz yet.
            attempts_on_current: Number of quiz attempts on current topic.

        Returns:
            A ``RoutingResult`` with the decision and supporting data.
        """
        node = graph.nodes.get(current_topic_id)
        if node is None:
            return RoutingResult(
                decision=RoutingDecision.NEXT_TOPIC,
                current_topic_id=current_topic_id,
                next_topic_id=None,
                weak_concept_report=None,
                reason=f"Topic {current_topic_id} not found in graph",
            )

        threshold = node.mastery_threshold
        current_score = mastery_scores.get(current_topic_id, 0.0)

        # 1. No quiz taken yet → check if ready for quiz
        if quiz_score is None:
            if current_score >= threshold:
                return RoutingResult(
                    decision=RoutingDecision.NEXT_TOPIC,
                    current_topic_id=current_topic_id,
                    next_topic_id=None,
                    weak_concept_report=None,
                    reason=f"Already mastered (score {current_score:.2f} >= {threshold:.2f})",
                )
            # Check if prerequisites are met
            prereqs = graph.get_prerequisites(current_topic_id)
            unmet = [
                pid for pid in prereqs
                if mastery_scores.get(pid, 0.0) < graph.nodes[pid].mastery_threshold
            ]
            if unmet:
                # Build weak concept report for prerequisite deficiencies
                report = self._build_weak_report(graph, mastery_scores, current_topic_id)
                root = report.root_cause(current_topic_id)
                return RoutingResult(
                    decision=RoutingDecision.REVISIT_PREREQUISITE,
                    current_topic_id=current_topic_id,
                    next_topic_id=root.topic_id if root else None,
                    weak_concept_report=report,
                    reason=f"Unmet prerequisites: {len(unmet)} topics below threshold",
                )
            # Prerequisites met → ready for quiz
            return RoutingResult(
                decision=RoutingDecision.READY_FOR_QUIZ,
                current_topic_id=current_topic_id,
                next_topic_id=None,
                weak_concept_report=None,
                reason="Prerequisites met, ready for quiz assessment",
            )

        # 2. Quiz score at or above threshold → mastered, move on
        if quiz_score >= threshold:
            report = self._build_weak_report(graph, mastery_scores, current_topic_id)
            # Find next topic in learning path
            path = self.path_service.generate(
                graph, syllabus_topic_ids, mastery_scores
            )
            next_id = path.next_topic_id
            return RoutingResult(
                decision=RoutingDecision.NEXT_TOPIC,
                current_topic_id=current_topic_id,
                next_topic_id=next_id,
                weak_concept_report=report,
                reason=f"Mastered (score {quiz_score:.2f} >= {threshold:.2f})",
            )

        # 3. Quiz score below threshold — analyze root cause
        report = self._build_weak_report(graph, mastery_scores, current_topic_id)
        root = report.root_cause(current_topic_id)

        # 3a. Root cause is a different (prerequisite) topic → revisit it
        if root is not None and root.topic_id != current_topic_id:
            return RoutingResult(
                decision=RoutingDecision.REVISIT_PREREQUISITE,
                current_topic_id=current_topic_id,
                next_topic_id=root.topic_id,
                weak_concept_report=report,
                reason=(
                    f"Root cause is prerequisite '{root.topic_name}' "
                    f"(score {root.score:.2f} < {root.threshold:.2f})"
                ),
            )

        # 3b. Root cause is the current topic itself
        if attempts_on_current >= self.MAX_RETRY_ATTEMPTS:
            # Too many retries — review/re-teach
            return RoutingResult(
                decision=RoutingDecision.REVIEW_TOPIC,
                current_topic_id=current_topic_id,
                next_topic_id=None,
                weak_concept_report=report,
                reason=(
                    f"Review needed after {attempts_on_current} attempts "
                    f"(score {quiz_score:.2f} < {threshold:.2f})"
                ),
            )

        # 3c. Score is low but retries remain → repeat
        return RoutingResult(
            decision=RoutingDecision.REPEAT_TOPIC,
            current_topic_id=current_topic_id,
            next_topic_id=None,
            weak_concept_report=report,
            reason=(
                f"Retry topic (attempt {attempts_on_current + 1}/{self.MAX_RETRY_ATTEMPTS}, "
                f"score {quiz_score:.2f} < {threshold:.2f})"
            ),
        )

    def _build_weak_report(
        self,
        graph: KnowledgeGraph,
        mastery_scores: dict[uuid.UUID, float],
        current_topic_id: uuid.UUID,
    ) -> WeakConceptReport:
        """Build a WeakConceptReport from mastery score dict."""
        class FakeRow:
            def __init__(self, tid, score, confidence, attempts):
                self.topic_id = tid
                self.score = score
                self.confidence = confidence
                self.attempts_count = attempts

        rows = [
            FakeRow(tid, score, 0.0, 0)
            for tid, score in mastery_scores.items()
        ]
        return self.mastery_engine.analyze(graph, rows, current_topic_id)
