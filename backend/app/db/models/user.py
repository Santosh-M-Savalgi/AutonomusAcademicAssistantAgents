"""User, profile, and refresh-token models (Section 15.3).

Sprint 6: adds username, is_active, last_login fields to User model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, IdMixin, TimestampMixin
from app.db.models.enums import LearningMode, UserRole

if TYPE_CHECKING:
    pass


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(20), nullable=False, default=UserRole.student, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    profile: Mapped["StudentProfile | None"] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<User {self.email!r}>"


class StudentProfile(Base):  # PK is user_id — no IdMixin
    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    learning_goals: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_learning_mode: Mapped[LearningMode | None] = mapped_column(
        String(20), nullable=True, default=LearningMode.journey
    )
    prefers_analogies: Mapped[float] = mapped_column(default=0.5, nullable=False)
    prefers_code_examples: Mapped[float] = mapped_column(default=0.5, nullable=False)
    prefers_shorter_lessons: Mapped[float] = mapped_column(default=0.5, nullable=False)
    known_struggle_patterns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    study_streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_study_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="profile")

    def __repr__(self) -> str:
        return f"<StudentProfile user_id={self.user_id!r}>"


class RefreshToken(Base, IdMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    def __repr__(self) -> str:
        return f"<RefreshToken user_id={self.user_id!r} revoked={self.revoked}>"
