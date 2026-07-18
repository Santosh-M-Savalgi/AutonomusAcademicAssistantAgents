"""Analytics API endpoints — detailed analytics data and trends.

All endpoints require authentication. Students can only access their own
data. Admins can access all students.

Endpoints:
- GET /analytics/stats       — aggregated study statistics
- GET /analytics/trends      — learning trends
- GET /analytics/timeline    — activity timeline
- POST /analytics/events     — record an analytics event
- GET /analytics/topics/{topic_id}/mastery — mastery history for topic
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import (
    MasteryHistoryEntryResponse,
    StudyStatsResponse,
    TimelineEventResponse,
    TrendsResponse,
)
from app.analytics.service import AnalyticsService
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.postgres import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


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
            detail="You can only access your own analytics data",
        )

    try:
        return uuid.UUID(target_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID",
        )


class RecordEventRequest(BaseModel):
    """Request schema for recording an analytics event."""

    event_type: str = Field(..., description="Type of analytics event")
    payload: dict[str, Any] | None = Field(None, description="Event metadata")
    session_id: str | None = Field(None, description="Associated session ID")


class RecordEventResponse(BaseModel):
    """Response schema for recording an analytics event."""

    recorded: bool = True
    event_type: str = ""


@router.get("/stats", response_model=StudyStatsResponse)
async def get_analytics_stats(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudyStatsResponse:
    """Get aggregated study statistics for a student.

    Returns counts of lessons, quizzes, topics, sessions, and overall stats.
    """
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    stats = await service.get_study_stats(db, target_id)

    return StudyStatsResponse(
        total_lessons_started=stats.total_lessons_started,
        total_lessons_completed=stats.total_lessons_completed,
        total_quizzes_attempted=stats.total_quizzes_attempted,
        total_quizzes_completed=stats.total_quizzes_completed,
        completed_topics=stats.completed_topics,
        in_progress_topics=stats.in_progress_topics,
        weak_topics=stats.weak_topics,
        strong_topics=stats.strong_topics,
        current_topic=stats.current_topic,
        current_syllabus=stats.current_syllabus,
        last_activity=str(stats.last_activity) if stats.last_activity else None,
        learning_streak_days=stats.learning_streak_days,
        total_study_hours=stats.total_study_hours,
        completed_sessions=stats.completed_sessions,
    )


@router.get("/trends", response_model=TrendsResponse)
async def get_analytics_trends(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrendsResponse:
    """Get learning trends including daily activity, weekly scores, and trend direction."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()
    trends = await service.get_trends(db, target_id)

    return TrendsResponse(
        daily_activity=[
            {"date": d["date"], "minutes": d["minutes"]}
            for d in trends.get("daily_activity", [])
        ],
        weekly_scores=[
            {"week": w["week"], "score": w["score"]}
            for w in trends.get("weekly_scores", [])
        ],
        weekly_trend=trends.get("weekly_trend", "stable"),
    )


@router.get("/timeline", response_model=list[TimelineEventResponse])
async def get_activity_timeline(
    user_id: str | None = Query(None, description="Target user ID (admin only)"),
    limit: int = Query(50, description="Maximum events to return"),
    event_types: str | None = Query(None, description="Comma-separated event type filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TimelineEventResponse]:
    """Get chronological activity timeline for a student."""
    target_id = _validate_user_access(user_id, current_user)
    service = _get_service()

    type_filter = None
    if event_types:
        type_filter = [t.strip() for t in event_types.split(",") if t.strip()]

    events = await service.get_timeline_events(
        db, target_id, limit=min(limit, 500), event_types=type_filter,
    )

    return [
        TimelineEventResponse(
            timestamp=e.timestamp,
            student_id=e.student_id,
            session_id=e.session_id,
            topic=e.topic,
            event_type=e.event_type,
            metadata=e.metadata,
        )
        for e in events
    ]


@router.post("/events", response_model=RecordEventResponse, status_code=201)
async def record_analytics_event(
    request: RecordEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecordEventResponse:
    """Record a new analytics event.

    Events are append-only and used for timeline, activity, and trend computation.
    """
    service = _get_service()

    session_uuid = None
    if request.session_id:
        try:
            session_uuid = uuid.UUID(request.session_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid session ID",
            )

    try:
        await service.record_event(
            db,
            user_id=current_user.id,
            event_type=request.event_type,
            payload=request.payload,
            session_id=session_uuid,
        )
    except Exception as exc:
        logger.error("Failed to record analytics event: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record event",
        )

    return RecordEventResponse(recorded=True, event_type=request.event_type)
