"""Analytics repository — analytics-specific persistence queries (Sprint 7).

Provides aggregate queries over existing data stores. Reuses existing
repositories (Postgres, session store) rather than duplicating data.

All queries are N+1-safe and use aggregation at the database layer where
possible (SQL aggregate functions, COUNT, AVG, etc.).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalyticsEvent,
    ConceptMastery,
    QuizAttempt,
    Session,
    Syllabus,
    Topic,
    User,
)
from app.db.models.enums import SessionStatus


# ── Topic & Syllabus Queries ──────────────────────────────────────────────────


async def get_user_topics(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Topic]:
    """Get all topics associated with a user's syllabi.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        List of Topic instances.
    """
    result = await db.execute(
        select(Topic)
        .join(Syllabus, Topic.syllabus_id == Syllabus.id)
        .where(Syllabus.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_user_syllabi(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Syllabus]:
    """Get all syllabi for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        List of Syllabus instances.
    """
    result = await db.execute(
        select(Syllabus).where(Syllabus.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_latest_syllabus(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Syllabus | None:
    """Get the most recently created syllabus for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        The latest Syllabus, or None.
    """
    result = await db.execute(
        select(Syllabus)
        .where(Syllabus.user_id == user_id)
        .order_by(Syllabus.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Quiz Queries ──────────────────────────────────────────────────────────────


async def get_user_quiz_attempts(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    topic_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[QuizAttempt]:
    """Get quiz attempts for a user, optionally filtered by topic.

    Args:
        db: Database session.
        user_id: The user's UUID.
        topic_id: Optional topic filter.
        limit: Maximum number of results.

    Returns:
        List of QuizAttempt instances.
    """
    query = select(QuizAttempt).where(QuizAttempt.user_id == user_id)
    if topic_id is not None:
        query = query.where(QuizAttempt.topic_id == topic_id)
    query = query.order_by(QuizAttempt.submitted_at.desc().nullslast()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_quiz_attempt_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    topic_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Get aggregated quiz statistics for a user.

    Uses SQL aggregate functions for efficiency.

    Args:
        db: Database session.
        user_id: The user's UUID.
        topic_id: Optional topic filter.

    Returns:
        Dict with 'total_attempts', 'total_completed', 'avg_score', and 'scores'.
    """
    query = select(
        func.count(QuizAttempt.id).label("total"),
        func.sum(
            func.cast(
                QuizAttempt.submitted_at.isnot(None),
                type_=type(func.count(1)),
            )
        ),
        func.avg(QuizAttempt.score).label("avg_score"),
    ).where(QuizAttempt.user_id == user_id)

    if topic_id is not None:
        query = query.where(QuizAttempt.topic_id == topic_id)

    result = await db.execute(query)
    row = result.one()

    # Also fetch individual scores
    scores_query = select(QuizAttempt.score).where(
        QuizAttempt.user_id == user_id,
        QuizAttempt.score.isnot(None),
    )
    if topic_id is not None:
        scores_query = scores_query.where(QuizAttempt.topic_id == topic_id)
    scores_result = await db.execute(scores_query)
    scores = [float(r[0]) for r in scores_result.all() if r[0] is not None]

    return {
        "total_attempts": row.total or 0,
        "total_completed": row[1] or 0,
        "avg_score": float(row.avg_score) if row.avg_score else 0.0,
        "scores": scores,
    }


# ── Mastery Queries ───────────────────────────────────────────────────────────


async def get_user_mastery_rows(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[ConceptMastery]:
    """Get all concept mastery rows for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        List of ConceptMastery instances.
    """
    result = await db.execute(
        select(ConceptMastery).where(ConceptMastery.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_mastery_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic_names: dict[uuid.UUID, str],
) -> dict[str, Any]:
    """Get aggregated mastery statistics.

    Args:
        db: Database session.
        user_id: The user's UUID.
        topic_names: Dict of topic_id -> topic_name for display.

    Returns:
        Dict with 'masteries', 'completed', 'in_progress', 'weak', 'strong' keys.
    """
    rows = await get_user_mastery_rows(db, user_id)

    completed = 0
    weak_topics: list[str] = []
    strong_topics: list[str] = []
    all_scores: list[float] = []

    for row in rows:
        score = row.score * 100.0  # Convert 0.0-1.0 to 0.0-100.0
        all_scores.append(score)
        name = topic_names.get(row.topic_id, str(row.topic_id))

        if score >= 75.0:
            completed += 1
            strong_topics.append(name)
        else:
            weak_topics.append(name)

    return {
        "masteries": [
            {"topic_id": str(r.topic_id), "score": r.score * 100.0}
            for r in rows
        ],
        "completed": completed,
        "in_progress": len(rows) - completed,
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "all_scores": all_scores,
    }


# ── Session Queries ───────────────────────────────────────────────────────────


async def get_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[Session]:
    """Get sessions for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.
        status: Optional status filter (active, idle, completed).
        limit: Maximum number of results.

    Returns:
        List of Session instances.
    """
    query = select(Session).where(Session.user_id == user_id)
    if status:
        query = query.where(Session.status == status)
    query = query.order_by(Session.last_active_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_session_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """Get aggregated session statistics.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        Dict with 'total', 'active', 'completed', 'idle' counts.
    """
    result = await db.execute(
        select(
            func.count(Session.id).label("total"),
            func.sum(
                func.cast(Session.status == SessionStatus.active.value, type_=type(func.count(1)))
            ).label("active"),
            func.sum(
                func.cast(Session.status == SessionStatus.completed.value, type_=type(func.count(1)))
            ).label("completed"),
            func.sum(
                func.cast(Session.status == SessionStatus.idle.value, type_=type(func.count(1)))
            ).label("idle"),
        ).where(Session.user_id == user_id)
    )
    row = result.one()
    return {
        "total": row.total or 0,
        "active": row[1] or 0,
        "completed": row[2] or 0,
        "idle": row[3] or 0,
    }


async def get_current_session(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Session | None:
    """Get the most recent active session for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        The most recent active Session, or None.
    """
    result = await db.execute(
        select(Session)
        .where(
            Session.user_id == user_id,
            Session.status.in_([SessionStatus.active.value, SessionStatus.idle.value]),
        )
        .order_by(Session.last_active_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Analytics Event Queries ───────────────────────────────────────────────────


async def get_user_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    event_types: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> list[AnalyticsEvent]:
    """Get analytics events for a user with optional filters.

    Args:
        db: Database session.
        user_id: The user's UUID.
        event_types: Optional list of event type strings to filter by.
        since: Optional start datetime.
        until: Optional end datetime.
        limit: Maximum number of results.

    Returns:
        List of AnalyticsEvent instances.
    """
    query = select(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id)

    if event_types:
        query = query.where(AnalyticsEvent.event_type.in_(event_types))

    if since is not None:
        query = query.where(AnalyticsEvent.created_at >= since)

    if until is not None:
        query = query.where(AnalyticsEvent.created_at <= until)

    query = query.order_by(AnalyticsEvent.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def record_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    event_type: str,
    payload: dict | None = None,
    session_id: uuid.UUID | None = None,
) -> AnalyticsEvent:
    """Record a new analytics event. Delegates to the shared repository.

    Args:
        db: Database session.
        user_id: The user's UUID.
        event_type: The event type string.
        payload: Optional metadata dict.
        session_id: Optional associated session ID.

    Returns:
        The created AnalyticsEvent instance.
    """
    from app.db.repository import record_event as repo_record_event
    return await repo_record_event(
        db,
        user_id=user_id,
        event_type=event_type,
        payload=payload,
        session_id=session_id,
    )


# ── Activity & Streak Queries ─────────────────────────────────────────────────


async def get_activity_dates(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = 365,
) -> list[date]:
    """Get distinct activity dates for a user within a window.

    Args:
        db: Database session.
        user_id: The user's UUID.
        days: Lookback window in days.

    Returns:
        List of distinct date objects with activity.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date(AnalyticsEvent.created_at).label("activity_date")
        )
        .where(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.created_at >= cutoff,
        )
        .distinct()
        .order_by(func.date(AnalyticsEvent.created_at))
    )
    return [row[0] for row in result.all() if row[0] is not None]


async def get_weekly_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    weeks: int = 8,
) -> list[dict[str, Any]]:
    """Get weekly aggregated activity duration.

    Args:
        db: Database session.
        user_id: The user's UUID.
        weeks: Number of weeks to look back.

    Returns:
        List of dicts with 'week' and 'minutes'.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    events = await get_user_events(
        db,
        user_id,
        since=cutoff,
        limit=2000,
    )

    from app.analytics.calculations import group_activity_by_day
    return group_activity_by_day([{
        "created_at": str(e.created_at),
        "payload": e.payload or {},
    } for e in events], days=weeks * 7)


async def get_topic_names(
    db: AsyncSession,
    topic_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Get human-readable names for a set of topic IDs.

    Args:
        db: Database session.
        topic_ids: Set of topic UUIDs.

    Returns:
        Dict of topic_id -> topic_name.
    """
    if not topic_ids:
        return {}

    result = await db.execute(
        select(Topic.id, Topic.name).where(Topic.id.in_(topic_ids))
    )
    return {row[0]: row[1] for row in result.all()}


async def get_current_topic_name(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    """Get the name of the current topic for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.

    Returns:
        The current topic name, or empty string if none.
    """
    session = await get_current_session(db, user_id)
    if session is None or session.current_topic_id is None:
        return ""

    topic = await db.get(Topic, session.current_topic_id)
    return topic.name if topic else ""


async def get_weakest_topic(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic_names: dict[uuid.UUID, str],
) -> str:
    """Get the name of the weakest topic for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.
        topic_names: Dict of topic_id -> topic_name.

    Returns:
        The weakest topic name, or empty string if none.
    """
    rows = await get_user_mastery_rows(db, user_id)
    if not rows:
        return ""

    lowest = min(rows, key=lambda r: r.score)
    return topic_names.get(lowest.topic_id, str(lowest.topic_id))


async def get_strongest_topic(
    db: AsyncSession,
    user_id: uuid.UUID,
    topic_names: dict[uuid.UUID, str],
) -> str:
    """Get the name of the strongest topic for a user.

    Args:
        db: Database session.
        user_id: The user's UUID.
        topic_names: Dict of topic_id -> topic_name.

    Returns:
        The strongest topic name, or empty string if none.
    """
    rows = await get_user_mastery_rows(db, user_id)
    if not rows:
        return ""

    highest = max(rows, key=lambda r: r.score)
    return topic_names.get(highest.topic_id, str(highest.topic_id))
