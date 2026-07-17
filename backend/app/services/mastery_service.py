"""Mastery Engine — deterministic mastery computation (Phase C).

Responsibilities:
- mastery calculation
- confidence score
- weak concept detection
- prerequisite deficiency detection

All pure deterministic logic. No LLM calls. Uses Sprint 1 persistence layer
data (ConceptMastery rows, Topic thresholds).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.services.knowledge_graph_service import KnowledgeGraph


@dataclass
class MasteryEntry:
    """Computed mastery state for a single topic."""

    topic_id: uuid.UUID
    topic_name: str
    score: float              # 0.0–1.0
    confidence: float          # 0.0–1.0, certainty of the score
    attempts_count: int
    threshold: float           # score required to be "mastered"
    is_mastered: bool          # score >= threshold
    is_weak: bool              # score < threshold (explicitly weak)


@dataclass
class WeakConceptReport:
    """Report of weak concepts and prerequisite deficiencies."""

    weak_concepts: list[MasteryEntry]          # topics below threshold
    prerequisite_deficiencies: list[MasteryEntry]  # weak prereqs of current topic
    strongest_concepts: list[MasteryEntry]     # topics above threshold (sorted)

    @property
    def has_deficiencies(self) -> bool:
        return len(self.prerequisite_deficiencies) > 0

    def root_cause(
        self, current_topic_id: uuid.UUID | None = None
    ) -> MasteryEntry | None:
        """Identify the single highest-priority weak concept.

        Priority: the weakest prerequisite of the current topic. If none,
        the overall weakest concept. Ties broken by weakest score.
        """
        if self.prerequisite_deficiencies:
            return min(self.prerequisite_deficiencies, key=lambda e: e.score)
        if self.weak_concepts:
            return min(self.weak_concepts, key=lambda e: e.score)
        return None


# ── Mastery Engine ──────────────────────────────────────────────────────────


class MasteryEngine:
    """Computes mastery state from raw ConceptMastery data.

    Usage::

        engine = MasteryEngine()
        report = engine.analyze(
            graph=kg,
            mastery_rows=[...],  # ConceptMastery model instances
            current_topic_id=some_uuid,
        )
    """

    # Confidence floor: minimum confidence for topics with 0 attempts.
    CONFIDENCE_FLOOR = 0.0

    # Confidence grows with attempts using a simple logistic-like curve.
    # After ~5 attempts, confidence approaches 0.95.
    CONFIDENCE_MAX = 0.95
    CONFIDENCE_GROWTH = 0.5  # steepness

    def compute_mastery(
        self,
        score: float,
        attempts_count: int,
        threshold: float = 0.75,
    ) -> tuple[float, float, bool]:
        """Compute mastery score, confidence, and mastery status.

        Args:
            score: Raw score from quiz evaluations (0.0–1.0).
            attempts_count: Number of quiz attempts for this topic.
            threshold: Score threshold for mastery.

        Returns:
            (score, confidence, is_mastered) tuple.
        """
        # Clamp score
        score = max(0.0, min(1.0, score))

        # Confidence: grows with attempts, saturates at CONFIDENCE_MAX
        if attempts_count == 0:
            confidence = self.CONFIDENCE_FLOOR
        else:
            confidence = self.CONFIDENCE_MAX * (
                1.0 - 1.0 / (1.0 + attempts_count * self.CONFIDENCE_GROWTH)
            )
        confidence = round(confidence, 4)

        is_mastered = score >= threshold
        return score, confidence, is_mastered

    def analyze(
        self,
        graph: KnowledgeGraph,
        mastery_rows: list,  # ConceptMastery model instances
        current_topic_id: uuid.UUID | None = None,
    ) -> WeakConceptReport:
        """Analyze mastery across topics and produce a weak-concept report.

        Args:
            graph: The KnowledgeGraph for prerequisite lookups.
            mastery_rows: Iterable of ConceptMastery model instances with
                ``.topic_id``, ``.score``, ``.confidence``, ``.attempts_count``.
            current_topic_id: Optional current topic to focus prerequisite
                deficiency detection on.

        Returns:
            A ``WeakConceptReport`` with categorized entries.
        """
        # Build mastery entries
        entries: dict[uuid.UUID, MasteryEntry] = {}
        for row in mastery_rows:
            node = graph.nodes.get(row.topic_id)
            if node is None:
                continue
            score, confidence, is_mastered = self.compute_mastery(
                row.score, row.attempts_count, node.mastery_threshold
            )
            entries[row.topic_id] = MasteryEntry(
                topic_id=row.topic_id,
                topic_name=node.name,
                score=score,
                confidence=min(confidence, row.confidence) if row.confidence > 0 else confidence,
                attempts_count=row.attempts_count,
                threshold=node.mastery_threshold,
                is_mastered=is_mastered,
                is_weak=not is_mastered,
            )

        weak = [e for e in entries.values() if e.is_weak]
        strong = [e for e in entries.values() if e.is_mastered]

        # Sort: weakest first (ascending score), strongest first (descending)
        weak.sort(key=lambda e: e.score)
        strong.sort(key=lambda e: e.score, reverse=True)

        # Prerequisite deficiencies: weak concepts that are prerequisites
        # of the current topic
        prereq_deficiencies: list[MasteryEntry] = []
        if current_topic_id is not None:
            prereq_ids = graph.get_prerequisites(current_topic_id)
            prereq_deficiencies = [
                e for tid, e in entries.items()
                if tid in prereq_ids and e.is_weak
            ]
            prereq_deficiencies.sort(key=lambda e: e.score)

        return WeakConceptReport(
            weak_concepts=weak,
            prerequisite_deficiencies=prereq_deficiencies,
            strongest_concepts=strong,
        )

    def detect_weak_concepts(
        self,
        graph: KnowledgeGraph,
        mastery_scores: dict[uuid.UUID, float],
        thresholds: dict[uuid.UUID, float] | None = None,
    ) -> list[uuid.UUID]:
        """Quick detection: return topic IDs below their mastery thresholds.

        Args:
            graph: KnowledgeGraph with node thresholds.
            mastery_scores: Current scores per topic_id.
            thresholds: Optional per-topic threshold overrides.

        Returns:
            List of topic IDs that are below threshold (weak).
        """
        weak: list[uuid.UUID] = []
        for tid, score in mastery_scores.items():
            node = graph.nodes.get(tid)
            if node is None:
                continue
            threshold = (
                thresholds.get(tid, node.mastery_threshold)
                if thresholds
                else node.mastery_threshold
            )
            if score < threshold:
                weak.append(tid)
        return weak
