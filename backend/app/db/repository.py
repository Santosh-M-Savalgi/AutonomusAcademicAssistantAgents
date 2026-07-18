"""Repository layer — thin async helpers for AAA v2 hot-path queries.

Each function receives an ``AsyncSession`` and returns typed results.
No business logic — these are pure persistence helpers that the services
and agents layer on top of.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalyticsEvent,
    ConceptMastery,
    QuizQuestion,
    Session,
    Topic,
    TopicClosure,
    TopicEdge,
)


# ---------------------------------------------------------------------------
# Session / checkpoint
# ---------------------------------------------------------------------------


async def get_session_by_id(
    db: AsyncSession, session_id: uuid.UUID
) -> Session | None:
    """Retrieve a session row by primary key (checkpoint rehydration path)."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def upsert_session_checkpoint(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    graph_checkpoint_id: str | None = None,
    path_stack: dict | None = None,
    current_topic_id: uuid.UUID | None = None,
    status: str | None = None,
) -> Session | None:
    """Update a session's checkpoint pointer and metadata.

    Only UPDATES existing session rows. Does NOT create new sessions.
    If the session doesn't exist in Postgres, logs a warning and returns None.
    Session creation is handled by ``SessionRepository.create()`` / the API layer.

    Used by the LangGraph checkpointer to persist durable state
    after every graph-node transition (Section 18.1).
    """
    now = datetime.now(timezone.utc)
    session = await get_session_by_id(db, session_id)
    if session is None:
        import logging
        _log = logging.getLogger(__name__)
        _log.warning(
            "upsert_session_checkpoint: session %s not found in Postgres — "
            "skipping durable write. Sessions must be created by the API layer "
            "(SessionManager.create_session → SessionRepository.create).",
            session_id,
        )
        return None
    session.last_active_at = now
    if graph_checkpoint_id is not None:
        session.graph_checkpoint_id = graph_checkpoint_id
    if path_stack is not None:
        session.path_stack = path_stack
    if current_topic_id is not None:
        session.current_topic_id = current_topic_id
    if status is not None:
        session.status = status
    return session


# ---------------------------------------------------------------------------
# Concept mastery
# ---------------------------------------------------------------------------


async def get_mastery(
    db: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID
) -> ConceptMastery | None:
    """Return mastery row for a user-topic pair, or None."""
    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.topic_id == topic_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic_id: uuid.UUID,
    *,
    score: float,
    confidence: float,
    attempts_count: int = 0,
) -> ConceptMastery:
    """Insert or update a concept-mastery row (Section 15.4 hot path)."""
    now = datetime.now(timezone.utc)
    mastery = await get_mastery(db, user_id, topic_id)
    if mastery is None:
        mastery = ConceptMastery(
            user_id=user_id,
            topic_id=topic_id,
            score=score,
            confidence=confidence,
            attempts_count=1,
            last_practiced_at=now,
        )
        db.add(mastery)
    else:
        mastery.score = score
        mastery.confidence = confidence
        mastery.attempts_count += 1
        mastery.last_practiced_at = now
    return mastery


# ---------------------------------------------------------------------------
# Topic / knowledge-graph context
# ---------------------------------------------------------------------------


async def get_topic_by_id(db: AsyncSession, topic_id: uuid.UUID) -> Topic | None:
    """Single-topic lookup."""
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    return result.scalar_one_or_none()


async def get_topic_by_slug(db: AsyncSession, slug: str) -> Topic | None:
    """Lookup topic by its unique slug."""
    result = await db.execute(select(Topic).where(Topic.slug == slug))
    return result.scalar_one_or_none()


async def get_direct_prerequisites(
    db: AsyncSession, topic_id: uuid.UUID
) -> list[Topic]:
    """Return topics that *this* topic directly depends on (Section 7.7)."""
    result = await db.execute(
        select(Topic)
        .join(TopicEdge, TopicEdge.child_topic_id == Topic.id)
        .where(TopicEdge.parent_topic_id == topic_id)
    )
    return list(result.scalars().all())


async def get_transitive_prerequisites(
    db: AsyncSession, topic_id: uuid.UUID
) -> list[tuple[uuid.UUID, int]]:
    """Return all transitive prerequisites with depth (Section 7.7).

    Uses the materialized closure table for O(1) lookup.
    Returns ``(descendant_id, depth)`` tuples.
    """
    result = await db.execute(
        select(TopicClosure.descendant_id, TopicClosure.depth).where(
            TopicClosure.ancestor_id == topic_id
        )
    )
    return [(row.descendant_id, row.depth) for row in result.all()]


async def get_topic_context(
    db: AsyncSession, topic_id: uuid.UUID
) -> dict:
    """Assemble the full topic context used by the Teaching Agent.

    Returns::

        {
            "topic": <Topic>,
            "direct_prerequisites": [<Topic>, ...],
            "transitive_prerequisites": [(uuid, depth), ...],
        }

    This is the single call referenced by Section 7.7's
    ``get_topic_context(topic_id)`` operation.
    """
    topic = await get_topic_by_id(db, topic_id)
    direct = await get_direct_prerequisites(db, topic_id)
    transitive = await get_transitive_prerequisites(db, topic_id)
    return {
        "topic": topic,
        "direct_prerequisites": direct,
        "transitive_prerequisites": transitive,
    }


# ---------------------------------------------------------------------------
# Quiz question bank
# ---------------------------------------------------------------------------


async def get_questions_by_topic(
    db: AsyncSession,
    topic_ids: list[uuid.UUID],
    *,
    exclude_correct_for_user: uuid.UUID | None = None,
    limit: int = 50,
) -> list[QuizQuestion]:
    """Retrieve quiz questions for one or more topics (bank-lookup hot path).

    When ``exclude_correct_for_user`` is provided, questions the user has
    already answered *correctly* are excluded (Section 13.5 retake policy).
    """
    query = select(QuizQuestion).where(QuizQuestion.topic_id.in_(topic_ids))

    if exclude_correct_for_user is not None:
        from app.db.models import QuizAttemptAnswer, QuizAttempt

        # Exclude questions this user has already answered correctly
        correct_sub = (
            select(QuizAttemptAnswer.question_id)
            .join(QuizAttempt, QuizAttempt.id == QuizAttemptAnswer.attempt_id)
            .where(
                QuizAttempt.user_id == exclude_correct_for_user,
                QuizAttemptAnswer.is_correct == True,  # noqa: E712
            )
            .subquery()
        )
        query = query.where(QuizQuestion.id.not_in(select(correct_sub)))

    query = query.order_by(QuizQuestion.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Analytics events (append-only, Section 19)
# ---------------------------------------------------------------------------


async def record_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_type: str,
    payload: dict | None = None,
    session_id: uuid.UUID | None = None,
) -> AnalyticsEvent:
    """Append an analytics event (non-blocking — caller should not await)."""
    event = AnalyticsEvent(
        user_id=user_id,
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
    )
    db.add(event)
    return event
