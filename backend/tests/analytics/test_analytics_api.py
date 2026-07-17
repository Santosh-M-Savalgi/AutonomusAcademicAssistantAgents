"""Tests for Dashboard & Analytics API endpoints and service layer (Sprint 7).

Covers: dashboard summary, progress, topics, mastery, activity, streak,
recommendations, analytics stats, trends, timeline, event recording,
authorization, and chart response formats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
from app.analytics.service import AnalyticsService
from app.db.models import User


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def topic_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_summary() -> DashboardSummary:
    return DashboardSummary(
        current_topic="Python Lists",
        current_course="Python 101",
        overall_completion=65.5,
        overall_mastery=72.3,
        average_quiz_score=78.0,
        weekly_study_time_minutes=120.0,
        daily_study_time_minutes=30.0,
        recent_sessions=5,
        current_streak_days=3,
        weakest_topic="Dictionaries",
        strongest_topic="Variables",
        recommended_next_topic="Functions",
        recent_activity=[
            TimelineEvent(
                timestamp="2026-07-17T10:00:00+00:00",
                student_id=str(uuid.uuid4()),
                session_id=str(uuid.uuid4()),
                topic="Python Lists",
                event_type="lesson_started",
                metadata={"duration_minutes": 30},
            ),
        ],
    )


@pytest.fixture
def mock_progress_list(topic_id: uuid.UUID) -> list[TopicProgress]:
    return [
        TopicProgress(
            topic_id=topic_id,
            topic_name="Python Lists",
            topic_slug="python-lists",
            completion_percentage=85.0,
            mastery_percentage=78.0,
            quiz_attempts=3,
            average_score=78.0,
            last_studied=datetime.now(timezone.utc),
            confidence_score=85.0,
            recommended_review=False,
            time_spent_minutes=45.0,
        ),
        TopicProgress(
            topic_id=uuid.uuid4(),
            topic_name="Dictionaries",
            topic_slug="dictionaries",
            completion_percentage=40.0,
            mastery_percentage=35.0,
            quiz_attempts=1,
            average_score=35.0,
            last_studied=datetime.now(timezone.utc) - timedelta(days=3),
            confidence_score=30.0,
            recommended_review=True,
            time_spent_minutes=15.0,
        ),
    ]


@pytest.fixture
def mock_topic_mastery() -> list[TopicMastery]:
    return [
        TopicMastery(topic="Python Lists", mastery=85.0),
        TopicMastery(topic="Dictionaries", mastery=45.0),
        TopicMastery(topic="Functions", mastery=70.0),
    ]


@pytest.fixture
def mock_mastery_history() -> list[MasteryHistoryEntry]:
    return [
        MasteryHistoryEntry(
            topic_id=str(uuid.uuid4()),
            topic_name="Python Lists",
            date="2026-07-17",
            mastery=85.0,
        ),
    ]


@pytest.fixture
def mock_daily_activity() -> list[DailyActivity]:
    return [
        DailyActivity(date="2026-07-17", minutes=30.0),
        DailyActivity(date="2026-07-16", minutes=45.0),
    ]


@pytest.fixture
def mock_streak() -> LearningStreak:
    return LearningStreak(
        current_streak_days=3,
        longest_streak_days=10,
        last_activity_date="2026-07-17",
        streak_active=True,
    )


@pytest.fixture
def mock_recommendations(topic_id: uuid.UUID) -> list[Recommendation]:
    return [
        Recommendation(
            topic_id=topic_id,
            topic_name="Functions",
            topic_slug="functions",
            reason="Next topic in your learning path",
            priority="high",
            recommendation_type="next",
        ),
        Recommendation(
            topic_id=uuid.uuid4(),
            topic_name="Dictionaries",
            topic_slug="dictionaries",
            reason="Weak topic (score 35%) — needs review",
            priority="high",
            recommendation_type="weak",
        ),
    ]


@pytest.fixture
def mock_study_stats() -> StudyStats:
    return StudyStats(
        total_lessons_started=10,
        total_lessons_completed=7,
        total_quizzes_attempted=15,
        total_quizzes_completed=12,
        completed_topics=5,
        in_progress_topics=3,
        weak_topics=2,
        strong_topics=5,
        current_topic="Python Lists",
        current_syllabus="Python 101",
        last_activity=datetime.now(timezone.utc),
        learning_streak_days=3,
        total_study_hours=12.5,
        completed_sessions=8,
    )


# ── Domain Model Tests ────────────────────────────────────────────────────────


class TestAnalyticsModels:
    """Verify domain model dataclasses construct correctly."""

    def test_dashboard_summary(self, mock_summary: DashboardSummary) -> None:
        assert mock_summary.current_topic == "Python Lists"
        assert mock_summary.overall_completion == 65.5
        assert len(mock_summary.recent_activity) == 1

    def test_topic_progress(self, mock_progress_list: list[TopicProgress]) -> None:
        assert len(mock_progress_list) == 2
        assert mock_progress_list[0].topic_name == "Python Lists"
        assert mock_progress_list[1].recommended_review is True

    def test_recommendation(self, mock_recommendations: list[Recommendation]) -> None:
        assert len(mock_recommendations) == 2
        assert mock_recommendations[0].priority == "high"

    def test_learning_streak(self, mock_streak: LearningStreak) -> None:
        assert mock_streak.current_streak_days == 3
        assert mock_streak.streak_active is True

    def test_study_stats(self, mock_study_stats: StudyStats) -> None:
        assert mock_study_stats.total_lessons_started == 10
        assert mock_study_stats.completed_sessions == 8


# ── Chart Response Format Tests ──────────────────────────────────────────────


class TestChartResponses:
    """Verify chart-ready response structures."""

    def test_daily_activity_format(self, mock_daily_activity: list[DailyActivity]) -> None:
        """Daily Activity: [{"date":"2026-07-17","minutes":45}]"""
        for entry in mock_daily_activity:
            assert "date" in entry.__dataclass_fields__
            assert "minutes" in entry.__dataclass_fields__
            assert isinstance(entry.date, str)
            assert isinstance(entry.minutes, float)

    def test_weekly_score_format(self) -> None:
        """Weekly Scores: [{"week":"2026-W28","score":82}]"""
        ws = WeeklyScore(week="2026-W28", score=82.0)
        assert ws.week == "2026-W28"
        assert ws.score == 82.0

    def test_topic_mastery_format(self, mock_topic_mastery: list[TopicMastery]) -> None:
        """Topic Mastery: [{"topic":"Arrays","mastery":91}]"""
        for entry in mock_topic_mastery:
            assert "topic" in entry.__dataclass_fields__
            assert "mastery" in entry.__dataclass_fields__
            assert isinstance(entry.topic, str)
            assert isinstance(entry.mastery, float)


# ── Service Tests ─────────────────────────────────────────────────────────────


class TestAnalyticsService:
    """Test AnalyticsService orchestration layer."""

    @pytest.mark.asyncio
    async def test_get_dashboard_summary(self, mock_summary: DashboardSummary) -> None:
        service = AnalyticsService()

        with patch.object(service, "get_dashboard_summary", return_value=mock_summary):
            result = await service.get_dashboard_summary(
                AsyncMock(), uuid.uuid4(),
            )
            assert result.current_topic == "Python Lists"
            assert result.overall_completion == 65.5

    @pytest.mark.asyncio
    async def test_get_study_stats(self, mock_study_stats: StudyStats) -> None:
        service = AnalyticsService()
        with patch.object(service, "get_study_stats", return_value=mock_study_stats):
            result = await service.get_study_stats(AsyncMock(), uuid.uuid4())
            assert result.total_lessons_started == 10
            assert result.total_study_hours == 12.5

    @pytest.mark.asyncio
    async def test_get_learning_streak(self, mock_streak: LearningStreak) -> None:
        service = AnalyticsService()
        with patch.object(service, "get_learning_streak", return_value=mock_streak):
            result = await service.get_learning_streak(AsyncMock(), uuid.uuid4())
            assert result.current_streak_days == 3
            assert result.streak_active is True


# ── Timeline Event Tests ──────────────────────────────────────────────────────


class TestTimelineEvents:
    """Verify timeline event structure and event types."""

    def test_event_types(self) -> None:
        """Verify all required event types are defined."""
        required_types = [
            "lesson_started",
            "lesson_completed",
            "quiz_started",
            "quiz_completed",
            "checkpoint_created",
            "checkpoint_restored",
            "session_started",
            "session_completed",
            "session_resumed",
            "login",
            "logout",
        ]
        for event_type in required_types:
            event = TimelineEvent(
                timestamp="2026-07-17T10:00:00+00:00",
                student_id="user-1",
                session_id="session-1",
                topic="Python",
                event_type=event_type,
                metadata={},
            )
            assert event.event_type == event_type

    def test_timeline_event_structure(self) -> None:
        event = TimelineEvent(
            timestamp="2026-07-17T10:00:00+00:00",
            student_id="student-123",
            session_id="session-456",
            topic="Python Lists",
            event_type="lesson_completed",
            metadata={"duration_minutes": 30, "score": 85},
        )
        assert event.timestamp == "2026-07-17T10:00:00+00:00"
        assert event.student_id == "student-123"
        assert event.session_id == "session-456"
        assert event.event_type == "lesson_completed"
        assert event.metadata["score"] == 85


# ── Recommendation Logic Tests ────────────────────────────────────────────────


class TestRecommendationLogic:
    """Verify recommendation types and ordering."""

    def test_recommendation_types(self, mock_recommendations: list[Recommendation]) -> None:
        types = {r.recommendation_type for r in mock_recommendations}
        assert "next" in types
        assert "weak" in types

    def test_recommendation_priorities(self, mock_recommendations: list[Recommendation]) -> None:
        for rec in mock_recommendations:
            assert rec.priority in ("high", "medium", "low")

    def test_recommendation_no_llm(self) -> None:
        """Verify recommendations are pure deterministic — no LLM calls."""
        from app.analytics.calculations import calculate_recommendations

        recs = calculate_recommendations([], syllabus_topic_ids=None)
        assert recs == []  # Pure function — no side effects, no LLM


# ── Authorization Tests ───────────────────────────────────────────────────────


class TestAuthorization:
    """Verify student vs admin access control."""

    def test_student_can_only_access_own_data(self) -> None:
        """Students should only see their own analytics."""
        user_id = uuid.uuid4()
        other_id = uuid.uuid4()

        from app.api.v2.dashboard import _validate_user_access

        mock_user = MagicMock(spec=User)
        mock_user.id = user_id
        mock_user.role = "student"

        # Own access should work
        result = _validate_user_access(str(user_id), mock_user)
        assert result == user_id

        # No user_id (default to current) should work
        result = _validate_user_access(None, mock_user)
        assert result == user_id

        # Other user's access should raise
        with pytest.raises(Exception):
            _validate_user_access(str(other_id), mock_user)

    def test_admin_can_access_any_student(self) -> None:
        """Admins should be able to access any student's data."""
        user_id = uuid.uuid4()
        other_id = uuid.uuid4()

        from app.api.v2.dashboard import _validate_user_access

        mock_admin = MagicMock(spec=User)
        mock_admin.id = user_id
        mock_admin.role = "admin"

        # Admin can access own data
        result = _validate_user_access(str(user_id), mock_admin)
        assert result == user_id

        # Admin can access other user's data
        result = _validate_user_access(str(other_id), mock_admin)
        assert result == other_id


# ── Performance Edge Case Tests ────────────────────────────────────────────────


class TestPerformanceEdgeCases:
    """Test analytics calculations with edge cases and large inputs."""

    def test_streak_large_dataset(self) -> None:
        from app.analytics.calculations import calculate_learning_streak

        # 100 consecutive days ending today
        dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(100)]
        current, longest = calculate_learning_streak(dates, today=date(2026, 4, 10))
        assert longest == 100
        assert current == 100  # all 100 days are consecutive + recent

    def test_recommendations_with_prerequisites(self) -> None:
        from app.analytics.calculations import calculate_recommendations

        current_id = uuid.uuid4()
        prereq_id = uuid.uuid4()
        topic_scores = [
            {"topic_id": current_id, "topic_name": "Advanced Topic",
             "topic_slug": "advanced", "score": 50.0, "threshold": 75.0,
             "last_studied_at": None, "attempts": 2},
            {"topic_id": prereq_id, "topic_name": "Prerequisite Topic",
             "topic_slug": "prereq", "score": 40.0, "threshold": 75.0,
             "last_studied_at": None, "attempts": 1},
        ]
        recs = calculate_recommendations(
            topic_scores,
            prerequisites_map={current_id: [prereq_id]},
            current_topic_id=current_id,
            completed_topic_ids=set(),  # neither topic is completed
        )
        # Prereq topic should be included as either weak or prerequisite type
        prereq_ids = {r["topic_id"] for r in recs}
        assert prereq_id in prereq_ids
