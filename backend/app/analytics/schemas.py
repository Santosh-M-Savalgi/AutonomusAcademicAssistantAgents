"""Pydantic schemas for Analytics API request/response serialization (Sprint 7).

These schemas are used by the dashboard and analytics API endpoints to
serialize/deserialize data. They are separate from the domain models to keep
the API contract independent from internal data structures.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TopicProgressResponse(BaseModel):
    """Progress information for a single topic."""

    topic_id: str = ""
    topic_name: str = ""
    topic_slug: str = ""
    completion_percentage: float = 0.0
    mastery_percentage: float = 0.0
    quiz_attempts: int = 0
    average_score: float = 0.0
    last_studied: str | None = None
    confidence_score: float = 0.0
    recommended_review: bool = False
    time_spent_minutes: float = 0.0


class DailyActivityResponse(BaseModel):
    """Daily activity for a specific date."""

    date: str = ""
    minutes: float = 0.0


class WeeklyScoreResponse(BaseModel):
    """Average quiz score for a calendar week."""

    week: str = ""
    score: float = 0.0


class TopicMasteryResponse(BaseModel):
    """Mastery level for a single topic (chart-ready)."""

    topic: str = ""
    mastery: float = 0.0


class TimelineEventResponse(BaseModel):
    """A single chronological learning event."""

    timestamp: str = ""
    student_id: str = ""
    session_id: str = ""
    topic: str = ""
    event_type: str = ""
    metadata: dict = Field(default_factory=dict)


class DashboardSummaryResponse(BaseModel):
    """Full dashboard summary response."""

    current_topic: str = ""
    current_course: str = ""
    overall_completion: float = 0.0
    overall_mastery: float = 0.0
    average_quiz_score: float = 0.0
    weekly_study_time_minutes: float = 0.0
    daily_study_time_minutes: float = 0.0
    recent_sessions: int = 0
    current_streak_days: int = 0
    weakest_topic: str = ""
    strongest_topic: str = ""
    recommended_next_topic: str = ""
    recent_activity: list[TimelineEventResponse] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    """A single learning recommendation."""

    topic_id: str = ""
    topic_name: str = ""
    topic_slug: str = ""
    reason: str = ""
    priority: str = ""
    recommendation_type: str = ""


class LearningStreakResponse(BaseModel):
    """Current learning streak information."""

    current_streak_days: int = 0
    longest_streak_days: int = 0
    last_activity_date: str = ""
    streak_active: bool = False


class MasteryHistoryEntryResponse(BaseModel):
    """Mastery score at a point in time for a specific topic."""

    topic_id: str = ""
    topic_name: str = ""
    date: str = ""
    mastery: float = 0.0


class StudyStatsResponse(BaseModel):
    """Aggregated study statistics."""

    total_lessons_started: int = 0
    total_lessons_completed: int = 0
    total_quizzes_attempted: int = 0
    total_quizzes_completed: int = 0
    completed_topics: int = 0
    in_progress_topics: int = 0
    weak_topics: int = 0
    strong_topics: int = 0
    current_topic: str = ""
    current_syllabus: str = ""
    last_activity: str | None = None
    learning_streak_days: int = 0
    total_study_hours: float = 0.0
    completed_sessions: int = 0


class TrendsResponse(BaseModel):
    """Learning trends response."""

    daily_activity: list[DailyActivityResponse] = Field(default_factory=list)
    weekly_scores: list[WeeklyScoreResponse] = Field(default_factory=list)
    weekly_trend: str = "stable"
