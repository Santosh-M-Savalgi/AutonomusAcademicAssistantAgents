"""Resource models: Resources, YouTubeResources, TrustedChannels (Section 15.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import DateTime as SATime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, IdMixin
from app.db.models.enums import DifficultyLevel, ResourceType


class TrustedChannel(Base, IdMixin):
    """Curated allow-list of trusted YouTube channels (Section 8)."""

    __tablename__ = "trusted_channels"

    channel_name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    authority_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    def __repr__(self) -> str:
        return f"<TrustedChannel {self.channel_name!r} tier={self.authority_tier}>"


class Resource(Base, IdMixin):
    """Web/docs/blog/research resource recommended for a topic."""

    __tablename__ = "resources"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ResourceType] = mapped_column(
        String(20), nullable=False, default=ResourceType.web
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_recommended: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        String(20), nullable=False, default=DifficultyLevel.intermediate
    )
    embedding_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Resource {self.title!r}>"


class YouTubeResource(Base, IdMixin):
    """YouTube video resource, channel-must-be-trusted filtered."""

    __tablename__ = "youtube_resources"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transcript_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        SATime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<YouTubeResource {self.video_id!r}>"
