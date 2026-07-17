"""Knowledge-graph models: Syllabi, Topics, TopicEdge, TopicClosure (Sections 7, 15)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base
from app.db.models.enums import (
    BloomLevel,
    DifficultyLevel,
    EdgeCreatedBy,
    EdgeRelationshipType,
    SyllabusStatus,
)


class Syllabus(Base):
    __tablename__ = "syllabi"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SyllabusStatus] = mapped_column(
        String(20), nullable=False, default=SyllabusStatus.parsing
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    topics: Mapped[list["Topic"]] = relationship(back_populates="syllabus", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Syllabus {self.title!r}>"


class Topic(Base):
    __tablename__ = "topics"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[DifficultyLevel] = mapped_column(
        String(20), nullable=False, default=DifficultyLevel.beginner
    )
    learning_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    bloom_target_level: Mapped[BloomLevel] = mapped_column(
        String(20), nullable=False, default=BloomLevel.understand
    )
    syllabus_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("syllabi.id", ondelete="SET NULL"), nullable=True, index=True
    )
    embedding_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    mastery_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    syllabus: Mapped["Syllabus | None"] = relationship(back_populates="topics")

    # Edges where this topic is the parent (depends on child)
    parent_edges: Mapped[list["TopicEdge"]] = relationship(
        back_populates="parent_topic",
        foreign_keys="TopicEdge.parent_topic_id",
        lazy="selectin",
    )
    # Edges where this topic is the child (prerequisite to parent)
    child_edges: Mapped[list["TopicEdge"]] = relationship(
        back_populates="child_topic",
        foreign_keys="TopicEdge.child_topic_id",
        lazy="selectin",
    )
    # Closure entries where this topic is the ancestor
    ancestor_closure: Mapped[list["TopicClosure"]] = relationship(
        back_populates="ancestor",
        foreign_keys="TopicClosure.ancestor_id",
        lazy="selectin",
    )
    # Closure entries where this topic is the descendant
    descendant_closure: Mapped[list["TopicClosure"]] = relationship(
        back_populates="descendant",
        foreign_keys="TopicClosure.descendant_id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Topic {self.slug!r}>"


class TopicEdge(Base):
    """Direct prerequisite edge: parent depends on child (Section 7.3)."""

    __tablename__ = "topic_edges"

    parent_topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[EdgeRelationshipType] = mapped_column(
        String(30), nullable=False, default=EdgeRelationshipType.direct_prerequisite
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_by: Mapped[EdgeCreatedBy] = mapped_column(
        String(20), nullable=False, default=EdgeCreatedBy.llm_inferred
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    parent_topic: Mapped["Topic"] = relationship(
        back_populates="parent_edges", foreign_keys=[parent_topic_id]
    )
    child_topic: Mapped["Topic"] = relationship(
        back_populates="child_edges", foreign_keys=[child_topic_id]
    )

    __table_args__ = (
        UniqueConstraint("parent_topic_id", "child_topic_id", name="uq_topic_edge_pair"),
    )

    def __repr__(self) -> str:
        return (
            f"<TopicEdge {self.parent_topic_id} --({self.relationship_type})--> "
            f"{self.child_topic_id}>"
        )


class TopicClosure(Base):
    """Materialized transitive closure (Section 7.4)."""

    __tablename__ = "topic_closure"

    ancestor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    descendant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    ancestor: Mapped["Topic"] = relationship(
        back_populates="ancestor_closure", foreign_keys=[ancestor_id]
    )
    descendant: Mapped["Topic"] = relationship(
        back_populates="descendant_closure", foreign_keys=[descendant_id]
    )

    def __repr__(self) -> str:
        return f"<TopicClosure {self.ancestor_id} -> {self.descendant_id} (depth={self.depth})>"
