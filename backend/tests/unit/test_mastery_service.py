"""Tests for Mastery Engine (Phase C).

Covers: mastery calculation, confidence score, weak concept detection,
prerequisite deficiency detection.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    TopicEdgeData,
    TopicNode,
)
from app.services.mastery_service import MasteryEngine, MasteryEntry, WeakConceptReport


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_node(name: str, mastery_threshold: float = 0.75) -> TopicNode:
    return TopicNode(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        difficulty="beginner",
        learning_depth=15,
        mastery_threshold=mastery_threshold,
    )


def _make_edge(parent_id: uuid.UUID, child_id: uuid.UUID) -> TopicEdgeData:
    return TopicEdgeData(
        id=uuid.uuid4(),
        parent_id=parent_id,
        child_id=child_id,
        relationship_type="direct_prerequisite",
        weight=1.0,
    )


class FakeMasteryRow:
    """Simulates a ConceptMastery SQLAlchemy model row."""

    def __init__(self, topic_id: uuid.UUID, score: float, confidence: float = 0.0, attempts_count: int = 1):
        self.topic_id = topic_id
        self.score = score
        self.confidence = confidence
        self.attempts_count = attempts_count


# ── Mastery Calculation ─────────────────────────────────────────────────────


class TestMasteryCalculation:
    def test_high_score_mastered(self) -> None:
        engine = MasteryEngine()
        score, conf, mastered = engine.compute_mastery(0.85, attempts_count=3)
        assert score == 0.85
        assert conf > 0.0
        assert mastered is True

    def test_low_score_not_mastered(self) -> None:
        engine = MasteryEngine()
        score, conf, mastered = engine.compute_mastery(0.30, attempts_count=1)
        assert score == 0.30
        assert mastered is False

    def test_exact_threshold(self) -> None:
        engine = MasteryEngine()
        score, conf, mastered = engine.compute_mastery(0.75, attempts_count=1)
        assert score == 0.75
        assert mastered is True  # >= threshold

    def test_score_clamped(self) -> None:
        engine = MasteryEngine()
        score, conf, mastered = engine.compute_mastery(1.5, attempts_count=2)
        assert score == 1.0

        score, conf, mastered = engine.compute_mastery(-0.5, attempts_count=2)
        assert score == 0.0


class TestConfidenceScore:
    def test_zero_attempts_zero_confidence(self) -> None:
        engine = MasteryEngine()
        _, conf, _ = engine.compute_mastery(0.0, attempts_count=0)
        assert conf == 0.0

    def test_confidence_grows_with_attempts(self) -> None:
        engine = MasteryEngine()
        _, conf1, _ = engine.compute_mastery(0.5, attempts_count=1)
        _, conf5, _ = engine.compute_mastery(0.5, attempts_count=5)
        _, conf10, _ = engine.compute_mastery(0.5, attempts_count=10)
        assert conf1 < conf5 < conf10

    def test_confidence_approaches_max(self) -> None:
        engine = MasteryEngine()
        _, conf, _ = engine.compute_mastery(0.5, attempts_count=100)
        assert conf >= 0.90
        assert conf <= 0.95


# ── Weak Concept Detection ──────────────────────────────────────────────────


class TestWeakConceptDetection:
    def test_detect_weak_below_threshold(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        weak = engine.detect_weak_concepts(kg, {a.id: 0.5})
        assert weak == [a.id]

    def test_no_weak_above_threshold(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        weak = engine.detect_weak_concepts(kg, {a.id: 0.85})
        assert weak == []

    def test_unknown_topic_ignored(self) -> None:
        engine = MasteryEngine()
        kg = KnowledgeGraph()
        weak = engine.detect_weak_concepts(kg, {uuid.uuid4(): 0.3})
        assert weak == []


# ── Analyze / WeakConceptReport ─────────────────────────────────────────────


class TestAnalyze:
    def test_empty_report(self) -> None:
        engine = MasteryEngine()
        kg = KnowledgeGraph()
        report = engine.analyze(kg, [])
        assert report.weak_concepts == []
        assert report.prerequisite_deficiencies == []
        assert report.strongest_concepts == []
        assert not report.has_deficiencies
        assert report.root_cause() is None

    def test_weak_and_strong_separation(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build([a, b], [])
        rows = [
            FakeMasteryRow(a.id, 0.85, attempts_count=3),  # strong
            FakeMasteryRow(b.id, 0.30, attempts_count=1),  # weak
        ]
        report = engine.analyze(kg, rows)
        assert len(report.weak_concepts) == 1
        assert report.weak_concepts[0].topic_id == b.id
        assert len(report.strongest_concepts) == 1
        assert report.strongest_concepts[0].topic_id == a.id

    def test_prerequisite_deficiency_detected(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build(
            [a, b],
            [_make_edge(a.id, b.id)],  # A depends on B
        )
        rows = [
            FakeMasteryRow(a.id, 0.50, attempts_count=1),
            FakeMasteryRow(b.id, 0.30, attempts_count=1),  # weak prereq
        ]
        report = engine.analyze(kg, rows, current_topic_id=a.id)
        assert report.has_deficiencies
        assert len(report.prerequisite_deficiencies) == 1
        assert report.prerequisite_deficiencies[0].topic_id == b.id

    def test_no_prereq_deficiency_when_prereqs_strong(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build(
            [a, b],
            [_make_edge(a.id, b.id)],
        )
        rows = [
            FakeMasteryRow(a.id, 0.50, attempts_count=1),
            FakeMasteryRow(b.id, 0.85, attempts_count=3),  # strong prereq
        ]
        report = engine.analyze(kg, rows, current_topic_id=a.id)
        assert not report.has_deficiencies
        assert len(report.prerequisite_deficiencies) == 0

    def test_root_cause_selects_weakest_prereq(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        b = _make_node("B")
        c = _make_node("C")
        kg = KnowledgeGraph.build(
            [a, b, c],
            [_make_edge(a.id, b.id), _make_edge(a.id, c.id)],
        )
        rows = [
            FakeMasteryRow(a.id, 0.50, attempts_count=1),
            FakeMasteryRow(b.id, 0.20, attempts_count=1),  # weakest
            FakeMasteryRow(c.id, 0.40, attempts_count=1),
        ]
        report = engine.analyze(kg, rows, current_topic_id=a.id)
        root = report.root_cause(a.id)
        assert root is not None
        assert root.topic_id == b.id  # weakest prereq

    def test_root_cause_falls_back_to_any_weak(self) -> None:
        engine = MasteryEngine()
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build([a, b], [])
        rows = [
            FakeMasteryRow(a.id, 0.85, attempts_count=3),
            FakeMasteryRow(b.id, 0.30, attempts_count=1),
        ]
        report = engine.analyze(kg, rows, current_topic_id=a.id)
        root = report.root_cause(a.id)
        assert root is not None
        assert root.topic_id == b.id
