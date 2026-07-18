"""Dashboard API endpoints — learning insights, progress tracking, study stats.

All endpoints require authentication. Students can only access their own
data. Admins can access all students.

Endpoints:
- GET /dashboard              — full dashboard summary
- GET /dashboard/summary      — high-level summary
- GET /dashboard/progress     — per-topic progress
- GET /dashboard/topics       — topic mastery list
- GET /dashboard/mastery      — mastery history
- GET /dashboard/activity     — daily activity
- GET /dashboard/streak       — learning streak
- GET /dashboard/recommendations — learning recommendations
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.repository import (
    get_user_events,
    get_user_topics,
)
from app.analytics.schemas import (
    DashboardSummaryResponse,
    DailyActivityResponse,
    LearningStreakResponse,
    MasteryHistoryEntryResponse,
    RecommendationResponse,
    StudyStatsResponse,
    TopicMasteryResponse,
    TopicProgressResponse,
    TrendsResponse,
    WeeklyScoreResponse,
)
from app.analytics.service import AnalyticsService
from app.auth.dependencies import get_current_user, require_admin
from app.db.models import User
from app.db.postgres import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _get_service() -> AnalyticsService:
    """Return an AnalyticsService instance."""
    return AnalyticsService()


def _validate_user_access(
    target_user_id: str | None,
    current_user: User,
) -> uuid.UUID:
    """Validate that the current user can access the target user's data.

    Students can only access their own data.
    Admins can access any user's data.

    Args:
        target_user_id: Optional target user ID string. If None, uses current user.
        current_user: The authenticated user.

    Returns:
        The validated target user UUID.

    Raises:
        HTTPException 403 if access is denied.
        HTTPException 400 if target_user_id is invalid.
    """
    if target_user_id is None or target_user_id == str(current_user.id):
        return current_user.id

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own dashboard data",
        )

    try:
        return uuid.UUID(target_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID",
        )


@router.get("", response_model=DashboardSummaryResponse)
async def get_dashboard(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Get the full dashboard summary for a student.

    Returns current topic, course, completion, mastery, quiz scores,
    study time, streak, weakest/strongest topics, and recent activity.
    """
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    summary = await service.get_dashboard_summary(db, target_id)

    return DashboardSummaryResponse(
        current_topic=summary.current_topic,
        current_course=summary.current_course,
        overall_completion=summary.overall_completion,
        overall_mastery=summary.overall_mastery,
        average_quiz_score=summary.average_quiz_score,
        weekly_study_time_minutes=summary.weekly_study_time_minutes,
        daily_study_time_minutes=summary.daily_study_time_minutes,
        recent_sessions=summary.recent_sessions,
        current_streak_days=summary.current_streak_days,
        weakest_topic=summary.weakest_topic,
        strongest_topic=summary.strongest_topic,
        recommended_next_topic=summary.recommended_next_topic,
        recent_activity=[
            {
                "timestamp": e.timestamp,
                "student_id": e.student_id,
                "session_id": e.session_id,
                "topic": e.topic,
                "event_type": e.event_type,
                "metadata": e.metadata,
            }
            for e in summary.recent_activity
        ],
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Get a high-level dashboard summary."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    summary = await service.get_dashboard_summary(db, target_id)

    return DashboardSummaryResponse(
        current_topic=summary.current_topic,
        current_course=summary.current_course,
        overall_completion=summary.overall_completion,
        overall_mastery=summary.overall_mastery,
        average_quiz_score=summary.average_quiz_score,
        weekly_study_time_minutes=summary.weekly_study_time_minutes,
        daily_study_time_minutes=summary.daily_study_time_minutes,
        recent_sessions=summary.recent_sessions,
        current_streak_days=summary.current_streak_days,
        weakest_topic=summary.weakest_topic,
        strongest_topic=summary.strongest_topic,
        recommended_next_topic=summary.recommended_next_topic,
    )


@router.get("/progress", response_model=list[TopicProgressResponse])
async def get_topic_progress(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TopicProgressResponse]:
    """Get per-topic progress details for a student."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    progress_list = await service.get_topic_progress(db, target_id)

    return [
        TopicProgressResponse(
            topic_id=str(p.topic_id),
            topic_name=p.topic_name,
            topic_slug=p.topic_slug,
            completion_percentage=p.completion_percentage,
            mastery_percentage=p.mastery_percentage,
            quiz_attempts=p.quiz_attempts,
            average_score=p.average_score,
            last_studied=str(p.last_studied) if p.last_studied else None,
            confidence_score=p.confidence_score,
            recommended_review=p.recommended_review,
            time_spent_minutes=p.time_spent_minutes,
        )
        for p in progress_list
    ]


@router.get("/topics", response_model=list[TopicMasteryResponse])
async def get_topic_mastery(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TopicMasteryResponse]:
    """Get topic mastery list (chart-ready) for a student."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    mastery_list = await service.get_chart_topic_mastery(db, target_id)

    return [
        TopicMasteryResponse(
            topic=m.topic,
            mastery=m.mastery,
        )
        for m in mastery_list
    ]


@router.get("/mastery", response_model=list[MasteryHistoryEntryResponse])
async def get_mastery_history(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    topic_id: str | None = Query(None, description="Filter by topic ID"),
    max_entries: int = Query(50, description="Maximum entries to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MasteryHistoryEntryResponse]:
    """Get mastery history for a student, optionally filtered by topic."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()

    if topic_id:
        try:
            tid = uuid.UUID(topic_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid topic ID",
            )
        history = await service.get_mastery_history_by_topic(db, target_id, tid)
    else:
        history = await service.get_mastery_history(db, target_id, max_entries=max_entries)

    return [
        MasteryHistoryEntryResponse(
            topic_id=h.topic_id,
            topic_name=h.topic_name,
            date=h.date,
            mastery=h.mastery,
        )
        for h in history
    ]


@router.get("/activity", response_model=list[DailyActivityResponse])
async def get_daily_activity(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    days: int = Query(14, description="Number of days to look back"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DailyActivityResponse]:
    """Get daily study activity for chart display."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    activity = await service.get_chart_daily_activity(db, target_id, days=min(days, 90))

    return [
        DailyActivityResponse(date=a.date, minutes=a.minutes)
        for a in activity
    ]


@router.get("/streak", response_model=LearningStreakResponse)
async def get_learning_streak(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LearningStreakResponse:
    """Get current and longest learning streak."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    streak = await service.get_learning_streak(db, target_id)

    return LearningStreakResponse(
        current_streak_days=streak.current_streak_days,
        longest_streak_days=streak.longest_streak_days,
        last_activity_date=streak.last_activity_date,
        streak_active=streak.streak_active,
    )


@router.get("/recommendations", response_model=list[RecommendationResponse])
async def get_dashboard_recommendations(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    max_recommendations: int = Query(5, description="Maximum recommendations"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RecommendationResponse]:
    """Get learning recommendations for a student.

    Pure deterministic logic — no LLM calls. Recommendations cover
    next topic, weak topics, revision topics, and prerequisite topics.
    """
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    recommendations = await service.get_recommendations(
        db, target_id, max_recommendations=max_recommendations,
    )

    return [
        RecommendationResponse(
            topic_id=str(r.topic_id),
            topic_name=r.topic_name,
            topic_slug=r.topic_slug,
            reason=r.reason,
            priority=r.priority,
            recommendation_type=r.recommendation_type,
        )
        for r in recommendations
    ]
