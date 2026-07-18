"""Tests for Analytics Calculations (Sprint 7).

Covers: completion, mastery, average score, learning streak, time spent,
topic progress, dashboard summary, recommendations, trends, activity grouping.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

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


# ── Completion ────────────────────────────────────────────────────────────────


class TestCalculateCompletion:
    def test_all_completed(self) -> None:
        assert calculate_completion(10, 10) == 100.0

    def test_half_completed(self) -> None:
        assert calculate_completion(5, 10) == 50.0

    def test_none_completed(self) -> None:
        assert calculate_completion(0, 10) == 0.0

    def test_no_topics(self) -> None:
        assert calculate_completion(0, 0) == 100.0

    def test_partial_completion(self) -> None:
        assert calculate_completion(3, 7) == pytest.approx(42.9, rel=0.1)


# ── Mastery ───────────────────────────────────────────────────────────────────


class TestCalculateMastery:
    def test_all_perfect(self) -> None:
        assert calculate_mastery([100.0, 100.0, 100.0]) == 100.0

    def test_mixed_scores(self) -> None:
        assert calculate_mastery([80.0, 90.0, 70.0]) == 80.0

    def test_empty_scores(self) -> None:
        assert calculate_mastery([]) == 0.0

    def test_single_score(self) -> None:
        assert calculate_mastery([85.5]) == 85.5


# ── Average Score ─────────────────────────────────────────────────────────────


class TestCalculateAverageScore:
    def test_average_of_scores(self) -> None:
        assert calculate_average_score([70.0, 80.0, 90.0]) == 80.0

    def test_empty_scores(self) -> None:
        assert calculate_average_score([]) == 0.0

    def test_single_score(self) -> None:
        assert calculate_average_score([75.5]) == 75.5


# ── Learning Streak ───────────────────────────────────────────────────────────


class TestCalculateLearningStreak:
    def test_consecutive_days(self) -> None:
        dates = [
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 17),
        ]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 17))
        assert current == 3
        assert longest == 3

    def test_broken_streak(self) -> None:
        dates = [
            date(2026, 7, 14),
            date(2026, 7, 17),  # Gap on 15-16
        ]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 17))
        assert current == 1
        assert longest == 1

    def test_longest_streak_with_gap(self) -> None:
        dates = [
            date(2026, 7, 10),
            date(2026, 7, 11),
            date(2026, 7, 12),
            date(2026, 7, 13),
            date(2026, 7, 15),
            date(2026, 7, 16),
        ]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 16))
        assert current == 2
        assert longest == 4

    def test_no_activity(self) -> None:
        current, longest = calculate_learning_streak([], today=date(2026, 7, 17))
        assert current == 0
        assert longest == 0

    def test_yesterday_activity(self) -> None:
        dates = [date(2026, 7, 16)]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 17))
        assert current == 1
        assert longest == 1

    def test_stale_activity_broken_streak(self) -> None:
        dates = [date(2026, 7, 10)]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 17))
        assert current == 0
        assert longest == 1

    def test_duplicate_dates(self) -> None:
        dates = [
            date(2026, 7, 16),
            date(2026, 7, 16),
            date(2026, 7, 17),
        ]
        current, longest = calculate_learning_streak(dates, today=date(2026, 7, 17))
        assert current == 2
        assert longest == 2


# ── Time Spent ────────────────────────────────────────────────────────────────


class TestCalculateTimeSpent:
    def test_duration_minutes(self) -> None:
        events = [
            {"payload": {"duration_minutes": 30}},
            {"payload": {"duration_minutes": 45}},
        ]
        assert calculate_time_spent(events) == 75.0

    def test_time_spent_field(self) -> None:
        events = [
            {"payload": {"time_spent_minutes": 20}},
            {"payload": {"time_spent_minutes": 10}},
        ]
        assert calculate_time_spent(events) == 30.0

    def test_empty_events(self) -> None:
        assert calculate_time_spent([]) == 0.0

    def test_mixed_time_fields(self) -> None:
        events = [
            {"payload": {"duration_minutes": 30}},
            {"payload": {"time_spent_minutes": 15}},
        ]
        assert calculate_time_spent(events) == 45.0


# ── Topic Progress ────────────────────────────────────────────────────────────


class TestCalculateTopicProgress:
    def test_full_progress(self) -> None:
        result = calculate_topic_progress(85.0, 75.0, 3, confidence=0.9)
        assert result["mastery_percentage"] == 85.0
        assert result["confidence_score"] == 90.0
        assert result["recommended_review"] is False

    def test_below_threshold(self) -> None:
        result = calculate_topic_progress(50.0, 75.0, 2, confidence=0.5)
        assert result["recommended_review"] is True
        assert result["completion_percentage"] == pytest.approx(66.7, rel=0.1)

    def test_zero_threshold(self) -> None:
        result = calculate_topic_progress(0.0, 0.0, 0, confidence=0.0)
        assert result["completion_percentage"] == 100.0


# ── Dashboard Summary ─────────────────────────────────────────────────────────


class TestCalculateDashboardSummary:
    def test_basic_summary(self) -> None:
        summary = calculate_dashboard_summary(
            current_topic="Python Lists",
            current_course="Python 101",
            overall_completion=65.0,
            overall_mastery=72.0,
            average_quiz_score=78.0,
            current_streak_days=5,
        )
        assert summary["current_topic"] == "Python Lists"
        assert summary["overall_completion"] == 65.0
        assert summary["current_streak_days"] == 5

    def test_empty_summary(self) -> None:
        summary = calculate_dashboard_summary()
        assert summary["current_topic"] == ""
        assert summary["overall_completion"] == 0.0
        assert summary["current_streak_days"] == 0


# ── Recommendations ──────────────────────────────────────────────────────────


class TestCalculateRecommendations:
    def test_no_recommendations_for_empty_data(self) -> None:
        recs = calculate_recommendations([])
        assert recs == []

    def test_next_topic_recommended(self) -> None:
        tid = uuid.uuid4()
        topic_scores = [
            {"topic_id": tid, "topic_name": "Python Lists", "topic_slug": "python-lists",
             "score": 0.0, "threshold": 75.0, "last_studied_at": None, "attempts": 0},
        ]
        recs = calculate_recommendations(
            topic_scores,
            syllabus_topic_ids=[tid],
            completed_topic_ids=set(),
        )
        assert len(recs) >= 1
        assert recs[0]["recommendation_type"] in ("next",)

    def test_weak_topic_recommended(self) -> None:
        tid1 = uuid.uuid4()
        tid2 = uuid.uuid4()
        topic_scores = [
            {"topic_id": tid1, "topic_name": "Strong Topic", "topic_slug": "strong",
             "score": 85.0, "threshold": 75.0, "last_studied_at": None, "attempts": 5},
            {"topic_id": tid2, "topic_name": "Weak Topic", "topic_slug": "weak",
             "score": 30.0, "threshold": 75.0, "last_studied_at": None, "attempts": 2},
        ]
        recs = calculate_recommendations(
            topic_scores,
            syllabus_topic_ids=None,
            completed_topic_ids={tid1},
        )
        weak_recs = [r for r in recs if r["recommendation_type"] == "weak"]
        assert len(weak_recs) >= 1
        assert weak_recs[0]["topic_name"] == "Weak Topic"

    def test_max_recommendations(self) -> None:
        topics = [
            {"topic_id": uuid.uuid4(), "topic_name": f"Topic {i}", "topic_slug": f"topic-{i}",
             "score": float(i * 10), "threshold": 75.0, "last_studied_at": None, "attempts": 1}
            for i in range(10)
        ]
        recs = calculate_recommendations(topics, max_recommendations=3)
        assert len(recs) <= 3

    def test_no_duplicates(self) -> None:
        tid = uuid.uuid4()
        topic_scores = [
            {"topic_id": tid, "topic_name": "My Topic", "topic_slug": "my-topic",
             "score": 40.0, "threshold": 75.0, "last_studied_at": None, "attempts": 1},
        ]
        recs = calculate_recommendations(topic_scores, max_recommendations=10)
        tids = [r["topic_id"] for r in recs]
        assert len(tids) == len(set(tids))


# ── Trends ────────────────────────────────────────────────────────────────────


class TestCalculateTrends:
    def test_empty_trends(self) -> None:
        trends = calculate_trends([], [])
        assert trends["weekly_trend"] == "stable"
        assert trends["daily_activity"] == []
        assert trends["weekly_scores"] == []

    def test_positive_trend(self) -> None:
        weekly = [
            {"week": "2026-W25", "score": 60.0},
            {"week": "2026-W26", "score": 65.0},
            {"week": "2026-W27", "score": 75.0},
            {"week": "2026-W28", "score": 85.0},
        ]
        trends = calculate_trends([], weekly)
        assert trends["weekly_trend"] == "positive"

    def test_negative_trend(self) -> None:
        weekly = [
            {"week": "2026-W25", "score": 85.0},
            {"week": "2026-W26", "score": 75.0},
            {"week": "2026-W27", "score": 65.0},
            {"week": "2026-W28", "score": 55.0},
        ]
        trends = calculate_trends([], weekly)
        assert trends["weekly_trend"] == "negative"


# ── Activity Grouping ─────────────────────────────────────────────────────────


class TestGroupActivityByDay:
    def test_empty_events(self) -> None:
        activity = group_activity_by_day([], days=7)
        assert len(activity) == 7
        assert all(a["minutes"] == 0.0 for a in activity)

    def test_single_event(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            {"created_at": now.isoformat(), "payload": {"duration_minutes": 30}},
        ]
        activity = group_activity_by_day(events, days=1)
        assert len(activity) == 1
        assert activity[0]["minutes"] == 30.0


# ── Weekly Score Grouping ─────────────────────────────────────────────────────


class TestGroupScoresByWeek:
    def test_empty_events(self) -> None:
        weekly = group_scores_by_week([], weeks=4)
        assert len(weekly) == 4

    def test_quiz_score_event(self) -> None:
        now = datetime.now(timezone.utc)
        events = [
            {"created_at": now.isoformat(), "event_type": "quiz_completed",
             "payload": {"score": 85.0}},
        ]
        weekly = group_scores_by_week(events, weeks=4)
        # The current week should have the score
        assert any(w["score"] > 0.0 for w in weekly)


# ── Mastery History ───────────────────────────────────────────────────────────


class TestCalculateMasteryHistory:
    def test_empty_events(self) -> None:
        history = calculate_mastery_history([], {})
        assert history == []

    def test_mastery_update_event(self) -> None:
        tid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        events = [
            {"created_at": now.isoformat(), "event_type": "mastery_update",
             "payload": {"topic_id": str(tid), "mastery": 85.0}},
        ]
        topics = {tid: "Python Lists"}
        history = calculate_mastery_history(events, topics)
        assert len(history) == 1
        assert history[0]["topic_name"] == "Python Lists"
        assert history[0]["mastery"] == 85.0
