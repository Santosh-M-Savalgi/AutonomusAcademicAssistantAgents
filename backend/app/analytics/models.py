"""Analytics domain types — lightweight dataclasses for analytics data.

These are independent of both SQLAlchemy models and Pydantic schemas.
They serve as the internal transfer objects for the analytics service layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TopicProgress:
    """Computed progress state for a single topic."""

    topic_id: uuid.UUID
    topic_name: str
    topic_slug: str
    completion_percentage: float  # 0.0–100.0
    mastery_percentage: float  # 0.0–100.0
    quiz_attempts: int
    average_score: float  # 0.0–100.0
    last_studied: datetime | None
    confidence_score: float  # 0.0–100.0
    recommended_review: bool
    time_spent_minutes: float


@dataclass
class DailyActivity:
    """Activity aggregated to a single day."""

    date: str  # ISO date string, e.g. "2026-07-17"
    minutes: float


@dataclass
class WeeklyScore:
    """Average quiz score for a calendar week."""

    week: str  # ISO week string, e.g. "2026-W28"
    score: float  # 0.0–100.0


@dataclass
class TopicMastery:
    """Mastery level for a single topic (chart-ready)."""

    topic: str  # human-readable name
    mastery: float  # 0.0–100.0


@dataclass
class TimelineEvent:
    """A single chronological learning event."""

    timestamp: str  # ISO-8601
    student_id: str
    session_id: str
    topic: str
    event_type: str
    metadata: dict = field(default_factory=dict)


@dataclass
class DashboardSummary:
    """Full dashboard summary for a student."""

    current_topic: str
    current_course: str
    overall_completion: float  # 0.0–100.0
    overall_mastery: float  # 0.0–100.0
    average_quiz_score: float  # 0.0–100.0
    weekly_study_time_minutes: float
    daily_study_time_minutes: float
    recent_sessions: int
    current_streak_days: int
    weakest_topic: str
    strongest_topic: str
    recommended_next_topic: str
    recent_activity: list[TimelineEvent] = field(default_factory=list)


@dataclass
class Recommendation:
    """A single learning recommendation."""

    topic_id: uuid.UUID
    topic_name: str
    topic_slug: str
    reason: str
    priority: str  # high | medium | low
    recommendation_type: str  # next | weak | revision | prerequisite | high_priority


@dataclass
class LearningStreak:
    """Current learning streak information."""

    current_streak_days: int
    longest_streak_days: int
    last_activity_date: str  # ISO date
    streak_active: bool


@dataclass
class MasteryHistoryEntry:
    """Mastery score at a point in time for a specific topic."""

    topic_id: uuid.UUID
    topic_name: str
    date: str  # ISO date
    mastery: float  # 0.0–100.0


@dataclass
class StudyStats:
    """Aggregated study statistics."""

    total_lessons_started: int
    total_lessons_completed: int
    total_quizzes_attempted: int
    total_quizzes_completed: int
    completed_topics: int
    in_progress_topics: int
    weak_topics: int
    strong_topics: int
    current_topic: str
    current_syllabus: str
    last_activity: datetime | None
    learning_streak_days: int
    total_study_hours: float
    completed_sessions: int
