"""Analytics Service — orchestration layer for analytics computations (Sprint 7).

This service coordinates between:
- Analytics repository (DB queries)
- Calculations module (pure functions)
- Domain models (dataclasses)
- Session store (activity data)

It does NOT contain business logic — that lives in calculations.py.
It does NOT contain data access logic — that lives in repository.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.calculations import (
    calculate_average_score,
    calculate_completion,
    calculate_dashboard_summary,
    calculate_learning_streak,
    calculate_mastery,
    calculate_mastery_history,
    calculate_recommendations,
    calculate_time_spent,
    calculate_topic_progress,
    calculate_trends,
    group_activity_by_day,
    group_scores_by_week,
)
from app.analytics.models import (
    DashboardSummary,
    DailyActivity,
    LearningStreak,
    MasteryHistoryEntry,
    Recommendation,
    StudyStats,
    TimelineEvent,
    TopicMastery,
    TopicProgress,
    WeeklyScore,
)
from app.analytics.repository import (
    get_activity_dates,
    get_current_session,
    get_current_topic_name,
    get_latest_syllabus,
    get_mastery_stats,
    get_quiz_attempt_stats,
    get_session_stats,
    get_strongest_topic,
    get_topic_names,
    get_user_events,
    get_user_mastery_rows,
    get_user_quiz_attempts,
    get_user_sessions,
    get_user_syllabi,
    get_user_topics,
    get_weakest_topic,
    record_event as repo_record_event,
)
from app.services.knowledge_graph_service import KnowledgeGraph


class AnalyticsService:
    """High-level analytics service for dashboard and analytics operations.

    Usage::

        service = AnalyticsService()
        summary = await service.get_dashboard_summary(db, user_id)
        progress = await service.get_topic_progress(db, user_id)
    """

    async def get_dashboard_summary(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> DashboardSummary:
        """Get a full dashboard summary for a student.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            A DashboardSummary instance.
        """
        # Get basic data
        topics = await get_user_topics(db, user_id)
        syllabi = await get_user_syllabi(db, user_id)
        latest_syllabus = await get_latest_syllabus(db, user_id)

        topic_ids = {t.id for t in topics}
        topic_names = {t.id: t.name for t in topics}
        current_topic_name = await get_current_topic_name(db, user_id)

        # Get mastery stats
        mastery_stats = await get_mastery_stats(db, user_id, topic_names) if topic_ids else {
            "masteries": [], "completed": 0, "in_progress": 0,
            "weak_topics": [], "strong_topics": [], "all_scores": [],
        }

        # Get quiz stats
        quiz_stats = await get_quiz_attempt_stats(db, user_id)

        # Get session stats
        session_stats = await get_session_stats(db, user_id)

        # Get events for timeline and activity
        events = await get_user_events(db, user_id, limit=1000)

        # Calculate activity dates and streak
        activity_dates = await get_activity_dates(db, user_id, days=365)
        current_streak, longest_streak = calculate_learning_streak(
            activity_dates,
            today=date.today(),
        )

        # Calculate study time
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=now.weekday())
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        weekly_time = calculate_time_spent(
            [{"payload": {"time_spent_minutes": 30}}],  # placeholder — will compute from events
        )

        # Create recent activity timeline
        recent_events_list: list[TimelineEvent] = []
        for ev in events[:20]:
            recent_events_list.append(TimelineEvent(
                timestamp=str(ev.created_at),
                student_id=str(ev.user_id),
                session_id=str(ev.session_id) if ev.session_id else "",
                topic="",
                event_type=ev.event_type,
                metadata=ev.payload or {},
            ))

        # Overall completion and mastery
        total = max(len(topics), 1)
        completed = mastery_stats["completed"]

        overall_completion = calculate_completion(completed, total)
        overall_mastery = calculate_mastery(mastery_stats.get("all_scores", []))
        avg_quiz = calculate_average_score(quiz_stats.get("scores", []))

        # Weakest/strongest
        weakest = max(1, len(mastery_stats.get("weak_topics", [])))
        strongest = max(1, len(mastery_stats.get("strong_topics", [])))

        weakened_str = mastery_stats.get("weak_topics", [""])[0] if mastery_stats.get("weak_topics") else ""
        strengthened = mastery_stats.get("strong_topics", [""])[0] if mastery_stats.get("strong_topics") else ""

        return DashboardSummary(
            current_topic=current_topic_name,
            current_course=latest_syllabus.title if latest_syllabus else "",
            overall_completion=overall_completion,
            overall_mastery=overall_mastery,
            average_quiz_score=avg_quiz,
            weekly_study_time_minutes=weekly_time,
            daily_study_time_minutes=0.0,
            recent_sessions=session_stats.get("total", 0),
            current_streak_days=current_streak,
            weakest_topic=weakened_str,
            strongest_topic=strengthened,
            recommended_next_topic="",
            recent_activity=recent_events_list,
        )

    async def get_topic_progress(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[TopicProgress]:
        """Get progress for all topics of a student.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            List of TopicProgress instances.
        """
        topics = await get_user_topics(db, user_id)
        mastery_rows = await get_user_mastery_rows(db, user_id)
        mastery_map = {r.topic_id: r for r in mastery_rows}

        progress_list: list[TopicProgress] = []
        for topic in topics:
            mastery = mastery_map.get(topic.id)
            score = (mastery.score * 100.0) if mastery else 0.0
            attempts = mastery.attempts_count if mastery else 0
            confidence = mastery.confidence if mastery else 0.0
            last_studied = mastery.last_practiced_at if mastery else None

            progress = calculate_topic_progress(
                score=score,
                threshold=topic.mastery_threshold * 100.0,
                attempts=attempts,
                confidence=confidence,
            )

            progress_list.append(TopicProgress(
                topic_id=topic.id,
                topic_name=topic.name,
                topic_slug=topic.slug,
                completion_percentage=progress["completion_percentage"],
                mastery_percentage=progress["mastery_percentage"],
                quiz_attempts=attempts,
                average_score=score,
                last_studied=last_studied,
                confidence_score=progress["confidence_score"],
                recommended_review=progress["recommended_review"],
                time_spent_minutes=0.0,
            ))

        return progress_list

    async def get_study_stats(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> StudyStats:
        """Get aggregated study statistics.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            A StudyStats instance.
        """
        topics = await get_user_topics(db, user_id)
        syllabi = await get_user_syllabi(db, user_id)
        topic_names = {t.id: t.name for t in topics}
        mastery_stats = await get_mastery_stats(db, user_id, topic_names)
        quiz_stats = await get_quiz_attempt_stats(db, user_id)
        session_stats = await get_session_stats(db, user_id)
        current_topic = await get_current_topic_name(db, user_id)
        latest_syllabus = await get_latest_syllabus(db, user_id)
        activity_dates = await get_activity_dates(db, user_id, days=365)
        current_streak, _ = calculate_learning_streak(activity_dates, today=date.today())

        # Last activity from events
        events = await get_user_events(db, user_id, limit=1)
        last_activity = events[0].created_at if events else None

        return StudyStats(
            total_lessons_started=session_stats.get("total", 0),
            total_lessons_completed=session_stats.get("completed", 0),
            total_quizzes_attempted=quiz_stats.get("total_attempts", 0),
            total_quizzes_completed=quiz_stats.get("total_completed", 0),
            completed_topics=mastery_stats.get("completed", 0),
            in_progress_topics=mastery_stats.get("in_progress", 0),
            weak_topics=len(mastery_stats.get("weak_topics", [])),
            strong_topics=len(mastery_stats.get("strong_topics", [])),
            current_topic=current_topic,
            current_syllabus=latest_syllabus.title if latest_syllabus else "",
            last_activity=last_activity,
            learning_streak_days=current_streak,
            total_study_hours=0.0,
            completed_sessions=session_stats.get("completed", 0),
        )

    async def get_timeline_events(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        event_types: list[str] | None = None,
    ) -> list[TimelineEvent]:
        """Get chronological timeline events for a student.

        Args:
            db: Database session.
            user_id: The student's UUID.
            limit: Maximum number of events.
            event_types: Optional filter by event types.

        Returns:
            List of TimelineEvent instances.
        """
        events = await get_user_events(
            db, user_id, event_types=event_types, limit=limit,
        )

        return [
            TimelineEvent(
                timestamp=str(e.created_at),
                student_id=str(e.user_id),
                session_id=str(e.session_id) if e.session_id else "",
                topic="",
                event_type=e.event_type,
                metadata=e.payload or {},
            )
            for e in events
        ]

    async def get_learning_streak(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> LearningStreak:
        """Get current and longest learning streak.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            A LearningStreak instance.
        """
        activity_dates = await get_activity_dates(db, user_id, days=365)
        current_streak, longest_streak = calculate_learning_streak(
            activity_dates, today=date.today(),
        )

        last_date = activity_dates[-1] if activity_dates else date.today()

        return LearningStreak(
            current_streak_days=current_streak,
            longest_streak_days=longest_streak,
            last_activity_date=last_date.isoformat(),
            streak_active=current_streak > 0,
        )

    async def get_mastery_history(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        max_entries: int = 50,
    ) -> list[MasteryHistoryEntry]:
        """Get mastery history across topics.

        Args:
            db: Database session.
            user_id: The student's UUID.
            max_entries: Maximum entries to return.

        Returns:
            List of MasteryHistoryEntry instances.
        """
        topics = await get_user_topics(db, user_id)
        topic_names = {t.id: t.name for t in topics}
        events = await get_user_events(db, user_id, limit=2000)

        history = calculate_mastery_history(
            [{"created_at": str(e.created_at), "event_type": e.event_type, "payload": e.payload or {}}
             for e in events],
            topic_names,
            max_entries=max_entries,
        )

        return [
            MasteryHistoryEntry(
                topic_id=str(e["topic_id"]),
                topic_name=e["topic_name"],
                date=e["date"],
                mastery=e["mastery"],
            )
            for e in history
        ]

    async def get_chart_daily_activity(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        days: int = 14,
    ) -> list[DailyActivity]:
        """Get daily activity data for charts.

        Args:
            db: Database session.
            user_id: The student's UUID.
            days: Number of days to look back.

        Returns:
            List of DailyActivity instances.
        """
        events = await get_user_events(db, user_id, limit=2000)
        daily = group_activity_by_day(
            [{"created_at": str(e.created_at), "payload": e.payload or {}}
             for e in events],
            days=days,
        )

        return [
            DailyActivity(date=d["date"], minutes=d["minutes"])
            for d in daily
        ]

    async def get_chart_weekly_scores(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        weeks: int = 8,
    ) -> list[WeeklyScore]:
        """Get weekly quiz score averages for charts.

        Args:
            db: Database session.
            user_id: The student's UUID.
            weeks: Number of weeks to look back.

        Returns:
            List of WeeklyScore instances.
        """
        events = await get_user_events(db, user_id, limit=2000)
        weekly = group_scores_by_week(
            [{"created_at": str(e.created_at), "event_type": e.event_type, "payload": e.payload or {}}
             for e in events],
            weeks=weeks,
        )

        return [
            WeeklyScore(week=w["week"], score=w["score"])
            for w in weekly
        ]

    async def get_chart_topic_mastery(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[TopicMastery]:
        """Get topic mastery data for charts.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            List of TopicMastery instances.
        """
        topics = await get_user_topics(db, user_id)
        topic_names = {t.id: t.name for t in topics}
        mastery_stats = await get_mastery_stats(db, user_id, topic_names)

        return [
            TopicMastery(
                topic=m.get("topic_name", str(m["topic_id"])),
                mastery=m.get("score", 0.0),
            )
            for m in mastery_stats.get("masteries", [])
        ]

    async def get_recommendations(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        graph: KnowledgeGraph | None = None,
        max_recommendations: int = 5,
    ) -> list[Recommendation]:
        """Get learning recommendations for a student.

        Pure deterministic logic — no LLM calls.

        Args:
            db: Database session.
            user_id: The student's UUID.
            graph: Optional KnowledgeGraph for prerequisite lookups.
            max_recommendations: Maximum number of recommendations.

        Returns:
            List of Recommendation instances.
        """
        topics = await get_user_topics(db, user_id)
        syllabus = await get_latest_syllabus(db, user_id)
        mastery_rows = await get_user_mastery_rows(db, user_id)
        current_session = await get_current_session(db, user_id)

        topic_scores: list[dict[str, Any]] = []
        for topic in topics:
            mastery = next((r for r in mastery_rows if r.topic_id == topic.id), None)
            topic_scores.append({
                "topic_id": topic.id,
                "topic_name": topic.name,
                "topic_slug": topic.slug,
                "score": (mastery.score * 100.0) if mastery else 0.0,
                "threshold": topic.mastery_threshold * 100.0,
                "last_studied_at": mastery.last_practiced_at if mastery else None,
                "attempts": mastery.attempts_count if mastery else 0,
            })

        syllabus_topic_ids = [t.id for t in topics] if syllabus else None
        completed_ids = {
            r.topic_id for r in mastery_rows
            if r.score * 100.0 >= (next(
                (t.mastery_threshold * 100.0 for t in topics if t.id == r.topic_id),
                75.0,
            ))
        }

        prereq_map: dict[uuid.UUID, list[uuid.UUID]] = {}
        if graph:
            for topic in topics:
                prereqs = graph.get_prerequisites(topic.id)
                if prereqs:
                    prereq_map[topic.id] = list(prereqs)

        recs = calculate_recommendations(
            topic_scores,
            syllabus_topic_ids=syllabus_topic_ids,
            completed_topic_ids=completed_ids,
            current_topic_id=current_session.current_topic_id if current_session else None,
            prerequisites_map=prereq_map,
            max_recommendations=max_recommendations,
        )

        return [
            Recommendation(
                topic_id=r["topic_id"],
                topic_name=r["topic_name"],
                topic_slug=r["topic_slug"],
                reason=r["reason"],
                priority=r["priority"],
                recommendation_type=r["recommendation_type"],
            )
            for r in recs
        ]

    async def record_event(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        event_type: str,
        payload: dict | None = None,
        session_id: uuid.UUID | None = None,
    ) -> None:
        """Record an analytics event.

        Args:
            db: Database session.
            user_id: The user's UUID.
            event_type: The event type string.
            payload: Optional metadata.
            session_id: Optional associated session ID.
        """
        await repo_record_event(
            db,
            user_id=user_id,
            event_type=event_type,
            payload=payload,
            session_id=session_id,
        )

    async def get_trends(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Get learning trends.

        Args:
            db: Database session.
            user_id: The student's UUID.

        Returns:
            Dict with 'daily_activity', 'weekly_scores', 'weekly_trend'.
        """
        daily = await self.get_chart_daily_activity(db, user_id, days=30)
        weekly = await self.get_chart_weekly_scores(db, user_id, weeks=8)

        return calculate_trends(
            [{"date": d.date, "minutes": d.minutes} for d in daily],
            [{"week": w.week, "score": w.score} for w in weekly],
        )

    async def get_mastery_history_by_topic(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        topic_id: uuid.UUID,
    ) -> list[MasteryHistoryEntry]:
        """Get mastery history for a specific topic.

        Args:
            db: Database session.
            user_id: The student's UUID.
            topic_id: The topic UUID.

        Returns:
            List of MasteryHistoryEntry instances.
        """
        from app.db.repository import get_topic_by_id

        topic = await get_topic_by_id(db, topic_id)
        topic_name = topic.name if topic else str(topic_id)

        events = await get_user_events(
            db, user_id, event_types=["mastery_update"], limit=500,
        )

        history = calculate_mastery_history(
            [{"created_at": str(e.created_at), "event_type": e.event_type, "payload": e.payload or {}}
             for e in events],
            {topic_id: topic_name},
            max_entries=50,
        )

        return [
            MasteryHistoryEntry(
                topic_id=str(e["topic_id"]),
                topic_name=e["topic_name"],
                date=e["date"],
                mastery=e["mastery"],
            )
            for e in history
        ]
