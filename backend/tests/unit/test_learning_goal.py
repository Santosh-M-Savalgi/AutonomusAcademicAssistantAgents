"""Tests for create_learning_goal duplicate TopicEdge prevention (Sprint 15).

Covers:
- Duplicate edges from same request (LLM returns same prereq twice)
- Duplicate edges already existing in the database
- Learning goal creation succeeds with duplicate prevention
- No IntegrityError is raised when edges already exist
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure Settings() can initialize in tests
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-for-validation")

from app.api.v2.learning import (
    _make_slug,
    create_learning_goal,
)
from app.agents.syllabus_parser import ParsedSyllabus, ParsedTopic, SyllabusParser
from app.db.models import Topic, TopicEdge, User
from app.db.models.enums import (
    DifficultyLevel,
    EdgeCreatedBy,
    EdgeRelationshipType,
    SyllabusStatus,
)


# ── Pure logic tests (no DB) ──────────────────────────────────────────────


class TestSlugCreation:
    def test_make_slug_basic(self) -> None:
        assert _make_slug("Python Basics") == "python-basics"

    def test_make_slug_special_chars(self) -> None:
        assert _make_slug("C++ & Java/JS") == "c-and-java-js"

    def test_make_slug_already_slug(self) -> None:
        assert _make_slug("python-basics") == "python-basics"

    def test_make_slug_idempotent(self) -> None:
        slug = "error-handling-file-io"
        assert _make_slug(slug) == slug
        assert _make_slug(_make_slug(slug)) == _make_slug(slug)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        username="testuser",
        role="student",
        is_active=True,
    )


def _make_db_topic(
    name: str,
    slug: str | None = None,
    topic_id: uuid.UUID | None = None,
) -> Topic:
    """Create a Topic with a pre-set ID (same as the DB would assign on flush).
    
    In production, ``Topic`` gets its ``id`` from the DB on flush.  In unit
    tests we must set it explicitly so the code can compare IDs.
    """
    t = Topic(
        name=name,
        slug=slug or _make_slug(name),
        description=f"About {name}",
        difficulty=DifficultyLevel.beginner,
        learning_depth=15,
        mastery_threshold=0.75,
    )
    object.__setattr__(t, "id", topic_id or uuid.uuid4())
    return t


def _make_result_mock(scalars_return: list | None = None) -> MagicMock:
    """Create a MagicMock that mimics an AsyncResult."""
    rm = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_return or []
    rm.scalars.return_value = scalars_mock
    return rm


@pytest.fixture
def mock_db() -> AsyncMock:
    """Base mock DB: no existing topics, no existing edges."""
    db = AsyncMock(spec=AsyncSession)
    # By default all execute() calls return empty results.
    # Tests that need specific return values override side_effect or return_value.
    db.execute.return_value = _make_result_mock([])
    return db


class _IdAssigner:
    """Track objects added to the session and assign UUIDs on flush."""

    def __init__(self) -> None:
        self._pending: list[object] = []

    def on_add(self, obj: object) -> None:
        from app.db.models.base import IdMixin
        # Ensure IdMixin objects can accept __setattr__ for 'id'
        if isinstance(obj, IdMixin):
            object.__setattr__(obj, "_sa_id_tracker", True)
        self._pending.append(obj)

    def on_flush(self) -> None:
        from app.db.models.base import IdMixin
        for obj in self._pending:
            if isinstance(obj, IdMixin):
                current = getattr(obj, "id", None)
                if current is None:
                    object.__setattr__(obj, "id", uuid.uuid4())
        self._pending.clear()


def _install_id_assigner(mock_db: AsyncMock) -> None:
    """Hook into ``db.add`` and ``db.flush`` to assign UUIDs on flush.

    SQLAlchemy ``default=uuid.uuid4`` fires at INSERT time, but the mock DB
    never actually flushes.  This bridge ensures newly created Topic/Syllabus
    objects get their IDs when the endpoint calls ``await db.flush()``.
    """
    assigner = _IdAssigner()
    mock_db.add.side_effect = assigner.on_add
    mock_db.flush.side_effect = assigner.on_flush


async def _call_create_goal(
    mock_db: AsyncMock,
    mock_user: User,
    parsed_syllabus: ParsedSyllabus,
) -> None:
    """Call create_learning_goal with mocked SyllabusParser and DB.

    Also mocks SessionManager and CheckpointStore so the test does not
    require a real Redis connection.
    """
    _install_id_assigner(mock_db)

    mock_session_mgr = MagicMock()
    mock_session_mgr.create_session = AsyncMock(
        return_value=MagicMock(session_id="test-session-id")
    )

    mock_checkpoint = MagicMock()
    mock_checkpoint.save_checkpoint = AsyncMock()

    patches = [
        patch.object(SyllabusParser, "parse", return_value=parsed_syllabus),
        patch("app.api.v2.learning.SessionManager", return_value=mock_session_mgr),
        patch("app.api.v2.learning.CheckpointStore", return_value=mock_checkpoint),
    ]
    for p in patches:
        p.start()
    try:
        result = await create_learning_goal(
            request=MagicMock(goal="test goal"),
            current_user=mock_user,
            db=mock_db,
        )
    finally:
        for p in patches:
            p.stop()


# ── Tests ─────────────────────────────────────────────────────────────────


class TestTopicEdgeDeduplication:
    """Verify that the same edge is NOT created twice in one request."""

    @pytest.mark.asyncio
    async def test_duplicate_prereqs_in_same_request_not_inserted_twice(
        self,
        mock_user: User,
    ) -> None:
        """When the LLM returns the same prerequisite slug twice for a topic,
        only ONE TopicEdge should be created."""
        # ── Arrange ──────────────────────────────────────────────────
        mock_db = AsyncMock(spec=AsyncSession)

        # First execute: slug lookup — no existing topics
        # Second execute: existing edges query — will return empty (no candidate_pairs
        # because topic slugs aren't created until flush, so the mock is harmless)
        mock_db.execute.return_value = _make_result_mock([])

        parsed = ParsedSyllabus(
            title="Test Syllabus",
            topics=[
                ParsedTopic("Topic A", "topic-a", "First topic", "beginner", []),
                ParsedTopic(
                    "Topic B", "topic-b", "Second topic", "beginner",
                    # SAME prereq slug listed 3 times — simulates LLM duplicate
                    prerequisites=["topic-a", "topic-a", "topic-a"],
                ),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topics_added = [item for item in added_items if isinstance(item, Topic)]
        topic_edges = [item for item in added_items if isinstance(item, TopicEdge)]

        # Debug: show what was added
        add_types = [type(a).__name__ for a in added_items]

        assert len(topics_added) == 2, (
            f"Expected 2 Topic objects added, got {len(topics_added)}. "
            f"All adds: {add_types}"
        )

        assert len(topic_edges) == 1, (
            f"Expected exactly 1 TopicEdge for (B -> A), "
            f"got {len(topic_edges)} edge(s). "
            f"Duplicate prerequisites were not filtered."
        )

        edge = topic_edges[0]
        topics = [item for item in added_items if isinstance(item, Topic)]
        topic_a = [t for t in topics if t.slug == "topic-a"][0]
        topic_b = [t for t in topics if t.slug == "topic-b"][0]

        assert edge.parent_topic_id == topic_b.id
        assert edge.child_topic_id == topic_a.id
        assert edge.relationship_type == EdgeRelationshipType.direct_prerequisite

    @pytest.mark.asyncio
    async def test_edges_already_in_db_are_not_inserted_again(
        self,
        mock_user: User,
    ) -> None:
        """When TopicEdge records already exist in the database,
        they should NOT be re-inserted."""
        # ── Arrange ──────────────────────────────────────────────────
        topic_a_id = uuid.uuid4()
        topic_b_id = uuid.uuid4()
        topic_a = _make_db_topic("Topic A", "topic-a", topic_a_id)
        topic_b = _make_db_topic("Topic B", "topic-b", topic_b_id)

        mock_db = AsyncMock(spec=AsyncSession)

        existing_edge = TopicEdge(
            parent_topic_id=topic_b_id,
            child_topic_id=topic_a_id,
            relationship_type=EdgeRelationshipType.direct_prerequisite,
            weight=1.0,
            created_by=EdgeCreatedBy.llm_inferred,
        )
        # Override pk so SQLAlchemy doesn't complain about transient instance
        existing_edge.id = uuid.uuid4()

        # execute calls in order:
        # 1. slug lookup        -> existing topics
        # 2. existing edges     -> edge already in DB
        # 3+. KG build query    -> return empty (not used in assertion)
        empty_result = _make_result_mock([])
        mock_db.execute.side_effect = [
            _make_result_mock([topic_a, topic_b]),
            _make_result_mock([existing_edge]),
            empty_result,
            empty_result,
        ]

        parsed = ParsedSyllabus(
            title="Test Syllabus",
            topics=[
                ParsedTopic("Topic A", "topic-a", "First topic", "beginner", []),
                ParsedTopic("Topic B", "topic-b", "Second topic", "beginner", ["topic-a"]),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topic_edges_added = [item for item in added_items if isinstance(item, TopicEdge)]

        # Should NOT create any TopicEdge since it already exists in DB
        assert len(topic_edges_added) == 0, (
            f"Expected 0 TopicEdge adds (edge already in DB), "
            f"got {len(topic_edges_added)}"
        )

    @pytest.mark.asyncio
    async def test_unique_edges_still_created_normally(
        self,
        mock_user: User,
    ) -> None:
        """When there are no duplicates, the standard edges are still
        created correctly with the right count."""
        # ── Arrange ──────────────────────────────────────────────────
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute.return_value = _make_result_mock([])

        parsed = ParsedSyllabus(
            title="Test Syllabus",
            topics=[
                ParsedTopic("A", "a", "Topic A", "beginner"),
                ParsedTopic("B", "b", "Topic B", "beginner", ["a"]),
                ParsedTopic("C", "c", "Topic C", "intermediate", ["b"]),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topic_edges = [item for item in added_items if isinstance(item, TopicEdge)]

        # A -> B depends on A, C depends on B = 2 edges
        assert len(topic_edges) == 2, (
            f"Expected 2 TopicEdge records for A←B←C chain, "
            f"got {len(topic_edges)}"
        )

    @pytest.mark.asyncio
    async def test_no_integrity_error_with_duplicates_across_multiple_goals(
        self,
        mock_user: User,
    ) -> None:
        """Simulate existing edges in DB + new topics with mixed prereqs.
        The endpoint should succeed without raising any exception."""
        # ── Arrange ──────────────────────────────────────────────────
        topic_a_id = uuid.uuid4()
        topic_b_id = uuid.uuid4()
        topic_c_id = uuid.uuid4()
        topic_a = _make_db_topic("A", "a", topic_a_id)
        topic_b = _make_db_topic("B", "b", topic_b_id)
        topic_c = _make_db_topic("C", "c", topic_c_id)

        mock_db = AsyncMock(spec=AsyncSession)

        existing_edge = TopicEdge(
            parent_topic_id=topic_b_id,
            child_topic_id=topic_a_id,
            relationship_type=EdgeRelationshipType.direct_prerequisite,
        )
        existing_edge.id = uuid.uuid4()

        # execute calls:
        # 1. slug lookup   -> A, B, C already exist
        # 2. existing edges -> (B->A) already in DB
        # 3+. KG build query -> return empty (not used in assertion)
        empty_result = _make_result_mock([])
        mock_db.execute.side_effect = [
            _make_result_mock([topic_a, topic_b, topic_c]),
            _make_result_mock([existing_edge]),
            empty_result,
            empty_result,
        ]

        parsed = ParsedSyllabus(
            title="Test Syllabus",
            topics=[
                ParsedTopic("A", "a", "Topic A", "beginner", []),
                ParsedTopic("B", "b", "Topic B", "beginner", ["a"]),
                ParsedTopic("C", "c", "Topic C", "intermediate", ["a", "b"]),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topic_edges = [item for item in added_items if isinstance(item, TopicEdge)]

        # Should have: (C -> A), (C -> B)
        # (B -> A) is already in DB so skipped
        assert len(topic_edges) == 2, (
            f"Expected 2 new edges (C->A and C->B), got {len(topic_edges)}"
        )

        edge_keys = {(e.parent_topic_id, e.child_topic_id) for e in topic_edges}
        assert (topic_c_id, topic_a_id) in edge_keys, "Missing C -> A"
        assert (topic_c_id, topic_b_id) in edge_keys, "Missing C -> B"

    @pytest.mark.asyncio
    async def test_edge_count_matches_prereq_spec(
        self,
        mock_user: User,
    ) -> None:
        """Verify that the total number of TopicEdge records added
        matches the expected count from the mock syllabus."""
        # ── Arrange ──────────────────────────────────────────────────
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute.return_value = _make_result_mock([])

        # "Python" mock syllabus from SyllabusParser._mock_syllabus
        parsed = ParsedSyllabus(
            title="Python Programming",
            topics=[
                ParsedTopic("Python Basics", "python-basics", "Variables, data types, and basic syntax", "beginner"),
                ParsedTopic("Control Flow", "control-flow", "Conditionals, loops, and logic", "beginner", ["python-basics"]),
                ParsedTopic("Functions & Modules", "functions-modules", "Writing reusable code with functions and modules", "beginner", ["control-flow"]),
                ParsedTopic("Data Structures", "data-structures", "Lists, dicts, sets, and tuples", "intermediate", ["functions-modules"]),
                ParsedTopic("OOP in Python", "oop-python", "Classes, inheritance, and polymorphism", "intermediate", ["data-structures"]),
                ParsedTopic("Error Handling & File I/O", "error-handling-file-io", "Exceptions, file operations, and context managers", "intermediate", ["functions-modules"]),
                ParsedTopic("Advanced Python", "advanced-python", "Decorators, generators, and async", "advanced", ["oop-python", "error-handling-file-io"]),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topic_edges = [item for item in added_items if isinstance(item, TopicEdge)]

        # There are 7 unique (parent, child) pairs: each topic's prereq list
        # has 1 or 2 prereqs, total 7 edges
        assert len(topic_edges) == 7, (
            f"Expected 7 TopicEdge records for Python mock syllabus, "
            f"got {len(topic_edges)}"
        )

    @pytest.mark.asyncio
    async def test_two_topics_with_same_prereq_both_created(
        self,
        mock_user: User,
    ) -> None:
        """Two topics depending on the same prerequisite = two edges, not one.
        This is NOT a duplicate — different parent IDs."""
        # ── Arrange ──────────────────────────────────────────────────
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute.return_value = _make_result_mock([])

        parsed = ParsedSyllabus(
            title="Test",
            topics=[
                ParsedTopic("Root", "root", "Root topic", "beginner", []),
                ParsedTopic("Branch A", "branch-a", "Depends on root", "beginner", ["root"]),
                ParsedTopic("Branch B", "branch-b", "Also depends on root", "beginner", ["root"]),
            ],
        )

        # ── Act ──────────────────────────────────────────────────────
        await _call_create_goal(mock_db, mock_user, parsed)

        # ── Assert ───────────────────────────────────────────────────
        added_items = [call.args[0] for call in mock_db.add.call_args_list]
        topic_edges = [item for item in added_items if isinstance(item, TopicEdge)]

        # Branch A -> Root, Branch B -> Root = 2 distinct edges
        assert len(topic_edges) == 2, (
            f"Expected 2 TopicEdge records (BranchA->Root, BranchB->Root), "
            f"got {len(topic_edges)} — false deduplication would be wrong!"
        )
