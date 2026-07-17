"""Quiz models: QuizQuestions, QuizAttempts, QuizAttemptAnswers (Sections 13, 15)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import DateTime as SATime
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base
from app.db.models.enums import BloomLevel, QuizDifficultyLevel


class QuizQuestion(Base):
    """MCQ question bank entry (Section 13.3)."""

    __tablename__ = "quiz_questions"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concept_tag: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[QuizDifficultyLevel] = mapped_column(
        String(20), nullable=False, default=QuizDifficultyLevel.medium
    )
    bloom_level: Mapped[BloomLevel] = mapped_column(
        String(20), nullable=False, default=BloomLevel.understand
    )
    estimated_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    question_tag: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )

    # Composite index for the bank-lookup hot path (Section 15.4):
    # QuizQuestions(topic_id, difficulty, concept_tag)
    __table_args__ = (
        # Handled via explicit Index() in Alembic or via SQLAlchemy __table_args__
    )

    def __repr__(self) -> str:
        return f"<QuizQuestion topic={self.topic_id!r} concept={self.concept_tag!r}>"


class QuizAttempt(Base):
    """A single quiz submission by a student (Section 15.3)."""

    __tablename__ = "quiz_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ratio_current_vs_prereq: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(SATime(timezone=True), nullable=True)

    answers: Mapped[list["QuizAttemptAnswer"]] = relationship(
        back_populates="attempt", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<QuizAttempt user={self.user_id!r} topic={self.topic_id!r} score={self.score}>"


class QuizAttemptAnswer(Base):
    """Individual answer within a quiz attempt."""

    __tablename__ = "quiz_attempt_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quiz_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    selected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_taken_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    attempt: Mapped["QuizAttempt"] = relationship(back_populates="answers")

    def __repr__(self) -> str:
        return (
            f"<QuizAttemptAnswer attempt={self.attempt_id!r} "
            f"correct={self.is_correct}>"
        )
