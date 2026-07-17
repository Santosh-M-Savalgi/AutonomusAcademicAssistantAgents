"""Tests for Learning Path Engine (Phase B).

Covers: beginner, standard, fast-track paths, completed syllabus,
missing prerequisites, next-topic lookup.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    TopicEdgeData,
    TopicNode,
)
from app.services.learning_path_service import (
    LearningMode,
    LearningPathService,
)


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
def three_topic_chain() -> tuple[KnowledgeGraph, list[uuid.UUID], uuid.UUID, uuid.UUID, uuid.UUID]:
    """A -> B -> C.  A depends on B, B depends on C. C is the root (no prereqs)."""
    c = _make_node("C")
    b = _make_node("B")
    a = _make_node("A")
    kg = KnowledgeGraph.build(
        [a, b, c],
        [_make_edge(a.id, b.id), _make_edge(b.id, c.id)],
    )
    return kg, [a.id, b.id, c.id], a.id, b.id, c.id


@pytest.fixture
def simple_chain() -> tuple[KnowledgeGraph, list[uuid.UUID]]:
    """Two independent topics, no edges."""
    a = _make_node("Topic A")
    b = _make_node("Topic B")
    kg = KnowledgeGraph.build([a, b], [])
    return kg, [a.id, b.id]


# ── tests ───────────────────────────────────────────────────────────────────


class TestLearningPathStandardMode:
    def test_standard_path_order(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        path = svc.generate(kg, syllabus_ids, {})

        assert path.mode == LearningMode.STANDARD
        assert path.total_topics == 3
        assert path.completed_topics == 0
        assert path.remaining_topics == 3
        # Topological order: C (no prereqs) → B → A
        names = [s.topic_name for s in path.steps]
        assert names.index("C") < names.index("B") < names.index("A")

    def test_next_topic_is_first_unblocked(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        # No mastery — next should be C
        next_id = svc.get_next_topic(kg, syllabus_ids, {})
        assert next_id == c_id

    def test_all_mastered_completes_path(
        self,
        simple_chain: tuple,
    ) -> None:
        kg, syllabus_ids = simple_chain
        svc = LearningPathService()
        a_id, b_id = syllabus_ids
        path = svc.generate(kg, syllabus_ids, {a_id: 0.85, b_id: 0.90})
        assert path.completed_topics == 2
        assert path.remaining_topics == 0
        assert path.is_complete
        assert path.next_topic_id is None


class TestLearningPathFastTrack:
    def test_fast_track_skips_completed(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        # C is mastered
        path = svc.generate(kg, syllabus_ids, {c_id: 0.80}, mode=LearningMode.FAST_TRACK)
        assert path.mode == LearningMode.FAST_TRACK
        # C should be skipped
        names = [s.topic_name for s in path.steps]
        assert "C" not in names
        assert len(path.steps) == 2  # A, B only

    def test_fast_track_empty_when_all_done(
        self,
        simple_chain: tuple,
    ) -> None:
        kg, syllabus_ids = simple_chain
        svc = LearningPathService()
        a_id, b_id = syllabus_ids
        path = svc.generate(
            kg, syllabus_ids,
            {a_id: 0.80, b_id: 0.80},
            mode=LearningMode.FAST_TRACK,
        )
        assert path.steps == []
        assert path.is_complete


class TestLearningPathBeginnerMode:
    def test_beginner_keeps_order(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        path = svc.generate(kg, syllabus_ids, {}, mode=LearningMode.BEGINNER)
        assert path.mode == LearningMode.BEGINNER
        # Same topological order
        names = [s.topic_name for s in path.steps]
        assert names.index("C") < names.index("B") < names.index("A")


class TestBlockedTopics:
    def test_topic_blocked_by_unmet_prereq(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        # B is mastered, C is not — A is blocked (needs B, which is done;
        # but A also needs C transitively? No, A only directly depends on B)
        # A directly depends on B, B directly depends on C
        # If only C is mastered, B is blocked by nothing (except C), but wait:
        # B depends on C. If C is not mastered, B is blocked.
        path = svc.generate(kg, syllabus_ids, {})
        # C should be unblocked (no prereqs), B blocked (needs C), A blocked (needs B)
        steps = {s.topic_name: s for s in path.steps}
        assert not steps["C"].is_blocked
        assert steps["B"].is_blocked
        assert steps["A"].is_blocked

    def test_topic_unblocks_when_prereq_met(
        self,
        three_topic_chain: tuple,
    ) -> None:
        kg, syllabus_ids, a_id, b_id, c_id = three_topic_chain
        svc = LearningPathService()
        # C is mastered
        path = svc.generate(kg, syllabus_ids, {c_id: 0.80})
        steps = {s.topic_name: s for s in path.steps}
        assert not steps["C"].is_blocked  # mastered
        assert not steps["B"].is_blocked  # C is mastered → B unblocked
        assert steps["A"].is_blocked       # B not mastered yet → A blocked


class TestMissingPrerequisites:
    def test_topic_not_in_graph_ignored(
        self,
        simple_chain: tuple,
    ) -> None:
        kg, syllabus_ids = simple_chain
        svc = LearningPathService()
        # Include a non-existent topic ID
        fake_id = uuid.uuid4()
        path = svc.generate(kg, syllabus_ids + [fake_id], {})
        # Only the two real topics
        assert path.total_topics == 2

    def test_completed_syllabus(
        self,
        simple_chain: tuple,
    ) -> None:
        kg, syllabus_ids = simple_chain
        svc = LearningPathService()
        a_id, b_id = syllabus_ids
        path = svc.generate(kg, syllabus_ids, {a_id: 1.0, b_id: 1.0})
        assert path.completed_topics == 2
        assert path.remaining_topics == 0
        assert path.is_complete
