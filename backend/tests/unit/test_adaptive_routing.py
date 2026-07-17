"""Tests for Adaptive Routing Engine (Phase D).

Covers every routing decision and edge cases.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.adaptive_routing import AdaptiveRouter, RoutingDecision
from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    TopicEdgeData,
    TopicNode,
)
from app.services.mastery_service import MasteryEngine
from app.services.learning_path_service import LearningPathService


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


@pytest.fixture
def router() -> AdaptiveRouter:
    return AdaptiveRouter()


# ── READY_FOR_QUIZ ──────────────────────────────────────────────────────────


class TestReadyForQuiz:
    def test_prereqs_met_no_quiz(self, router: AdaptiveRouter) -> None:
        """Topic has no unmet prereqs, no quiz taken → READY_FOR_QUIZ."""
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.READY_FOR_QUIZ

    def test_already_mastered_no_quiz(self, router: AdaptiveRouter) -> None:
        """Topic already mastered, no quiz needed → NEXT_TOPIC."""
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.85},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.NEXT_TOPIC


# ── REVISIT_PREREQUISITE ────────────────────────────────────────────────────


class TestRevisitPrerequisite:
    def test_unmet_prereq_before_quiz(self, router: AdaptiveRouter) -> None:
        """Prerequisites unmet, no quiz taken → REVISIT_PREREQUISITE."""
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build(
            [a, b],
            [_make_edge(a.id, b.id)],  # A depends on B
        )
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.5, b.id: 0.2},  # B is weak
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.REVISIT_PREREQUISITE
        assert result.next_topic_id == b.id

    def test_weak_prereq_after_quiz(self, router: AdaptiveRouter) -> None:
        """Quiz failed, root cause is a weak prereq → REVISIT_PREREQUISITE."""
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build(
            [a, b],
            [_make_edge(a.id, b.id)],
        )
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.3, b.id: 0.1},  # B very weak
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id],
            quiz_score=0.4,  # Failed quiz
        )
        assert result.decision == RoutingDecision.REVISIT_PREREQUISITE
        assert result.next_topic_id == b.id


# ── NEXT_TOPIC ─────────────────────────────────────────────────────────────


class TestNextTopic:
    def test_mastered_after_quiz(self, router: AdaptiveRouter) -> None:
        """Quiz passed → NEXT_TOPIC."""
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build([a, b], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.85},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id],
            quiz_score=0.80,
        )
        assert result.decision == RoutingDecision.NEXT_TOPIC
        assert result.next_topic_id == b.id

    def test_nonexistent_topic(self, router: AdaptiveRouter) -> None:
        """Topic not in graph → NEXT_TOPIC with None."""
        kg = KnowledgeGraph()
        result = router.route(
            graph=kg,
            mastery_scores={},
            current_topic_id=uuid.uuid4(),
            syllabus_topic_ids=[],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.NEXT_TOPIC
        assert result.next_topic_id is None


# ── REPEAT_TOPIC ───────────────────────────────────────────────────────────


class TestRepeatTopic:
    def test_failed_quiz_retries_remain(self, router: AdaptiveRouter) -> None:
        """Quiz failed, retries remain, no weak prereq → REPEAT_TOPIC."""
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.3},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=0.4,       # below threshold
            attempts_on_current=1,  # retries remain
        )
        assert result.decision == RoutingDecision.REPEAT_TOPIC


# ── REVIEW_TOPIC ───────────────────────────────────────────────────────────


class TestReviewTopic:
    def test_too_many_retries_reviews(self, router: AdaptiveRouter) -> None:
        """Quiz failed, retries exhausted, no weak prereq → REVIEW_TOPIC."""
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.3},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=0.4,         # below threshold
            attempts_on_current=3,   # exactly MAX_RETRY_ATTEMPTS
        )
        assert result.decision == RoutingDecision.REVIEW_TOPIC

    def test_exceeded_retries_reviews(self, router: AdaptiveRouter) -> None:
        """Quiz failed, retries exceeded → REVIEW_TOPIC."""
        a = _make_node("A")
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.3},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=0.4,
            attempts_on_current=5,
        )
        assert result.decision == RoutingDecision.REVIEW_TOPIC


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_mastery_from_history_without_quiz(self, router: AdaptiveRouter) -> None:
        """Topic already mastered from history → NEXT_TOPIC even without quiz."""
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build([a, b], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.80, b.id: 0.0},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.NEXT_TOPIC
        assert result.next_topic_id is None  # b is the next but not in path (b is unmastered)

    def test_all_topics_mastered(self, router: AdaptiveRouter) -> None:
        """Everything mastered, including prereqs."""
        a = _make_node("A")
        b = _make_node("B")
        kg = KnowledgeGraph.build(
            [a, b],
            [_make_edge(a.id, b.id)],
        )
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.85, b.id: 0.85},
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id],
            quiz_score=0.80,
        )
        assert result.decision == RoutingDecision.NEXT_TOPIC

    def test_custom_thresholds(self, router: AdaptiveRouter) -> None:
        """Topics with high thresholds require higher scores."""
        a = _make_node("A", mastery_threshold=0.90)
        kg = KnowledgeGraph.build([a], [])
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.85},  # below 0.90 threshold
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id],
            quiz_score=None,
        )
        assert result.decision == RoutingDecision.READY_FOR_QUIZ

    def test_revisit_prereq_selects_weakest(self, router: AdaptiveRouter) -> None:
        """Multiple weak prereqs → revisit the weakest one."""
        a = _make_node("A")
        b = _make_node("B")
        c = _make_node("C")
        kg = KnowledgeGraph.build(
            [a, b, c],
            [
                _make_edge(a.id, b.id),
                _make_edge(a.id, c.id),
            ],
        )
        result = router.route(
            graph=kg,
            mastery_scores={a.id: 0.5, b.id: 0.2, c.id: 0.6},  # B weakest
            current_topic_id=a.id,
            syllabus_topic_ids=[a.id, b.id, c.id],
            quiz_score=0.45,
        )
        assert result.decision == RoutingDecision.REVISIT_PREREQUISITE
        assert result.next_topic_id == b.id  # weakest
