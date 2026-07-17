"""Session, mastery, preferences, and analytics-event models (Sections 15, 18, 19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import DateTime as SATime
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base
from app.db.models.enums import LearningMode, SessionStatus


class ConceptMastery(Base):
    """Per-user, per-topic mastery tracking (Section 15.3)."""

    __tablename__ = "concept_mastery"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(
        SATime(timezone=True), nullable=True
    )
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<ConceptMastery user={self.user_id!r} topic={self.topic_id!r} "
            f"score={self.score:.2f}>"
        )


class Session(Base):
    """Student learning session (Section 18)."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    path_stack: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    graph_checkpoint_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        String(20), nullable=False, default=SessionStatus.active
    )
    last_active_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )

    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates=None, lazy="select")

    def __repr__(self) -> str:
        return f"<Session user={self.user_id!r} status={self.status.value!r}>"


class Preference(Base):
    """Per-user UI/notification preferences (Section 15.3)."""

    __tablename__ = "preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    notification_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    theme: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<Preference user={self.user_id!r}>"


class AnalyticsEvent(Base):
    """Append-only analytics event log, partitioned monthly (Section 15.3, 19)."""

    __tablename__ = "analytics_events"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AnalyticsEvent {self.event_type!r} user={self.user_id!r}>"
