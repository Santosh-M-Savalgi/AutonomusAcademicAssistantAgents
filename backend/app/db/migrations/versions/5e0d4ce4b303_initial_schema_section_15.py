"""initial_schema_section_15

Revision ID: 5e0d4ce4b303
Revises:
Create Date: 2026-07-17 11:54:52.894287

Creates all 17 tables defined in Section 15 of the AAA v2 architecture,
plus PostgreSQL enum types and critical indexes (Section 15.4).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "5e0d4ce4b303"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Enum types (Section 15.3 + Sections 7, 8, 13, 18)
# ---------------------------------------------------------------------------
ENUM_DEFS = {
    "user_role": ("student", "admin", "instructor"),
    "difficulty_level": ("beginner", "intermediate", "advanced"),
    "quiz_difficulty_level": ("easy", "medium", "hard"),
    "bloom_level": (
        "remember", "understand", "apply", "analyze", "evaluate", "create",
    ),
    "edge_relationship_type": (
        "direct_prerequisite", "related_concept", "part_of",
    ),
    "edge_created_by": ("llm_inferred", "human_curated"),
    "learning_mode": ("sprint", "journey", "mastery"),
    "syllabus_status": ("parsing", "ready", "failed"),
    "resource_type": ("web", "docs", "blog", "research"),
    "session_status": ("active", "idle", "completed"),
}


def _create_enums() -> None:
    for name, values in ENUM_DEFS.items():
        pg_enum = postgresql.ENUM(*values, name=name, create_type=True)
        pg_enum.create(op.get_bind(), checkfirst=True)


def _drop_enums() -> None:
    for name in ENUM_DEFS:
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    _create_enums()

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])

    # --- student_profiles ---
    op.create_table(
        "student_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("learning_goals", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("preferred_language", sa.String(50), nullable=True),
        sa.Column(
            "default_learning_mode",
            sa.String(20), nullable=True, server_default="journey",
        ),
        sa.Column(
            "prefers_analogies", sa.Float(), nullable=False, server_default="0.5",
        ),
        sa.Column(
            "prefers_code_examples", sa.Float(), nullable=False, server_default="0.5",
        ),
        sa.Column(
            "prefers_shorter_lessons",
            sa.Float(), nullable=False, server_default="0.5",
        ),
        sa.Column(
            "known_struggle_patterns", postgresql.JSONB(), nullable=True,
        ),
        sa.Column(
            "study_streak_days", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column(
            "total_study_time_seconds",
            sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- refresh_tokens ---
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked", sa.Boolean(), nullable=False, server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"],
    )
    op.create_index(
        "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"],
    )

    # --- syllabi ---
    op.create_table(
        "syllabi",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_file_url", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="parsing",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_syllabi_user_id", "syllabi", ["user_id"])

    # --- topics ---
    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(300), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "difficulty",
            sa.String(20), nullable=False, server_default="beginner",
        ),
        sa.Column(
            "learning_depth", sa.Integer(), nullable=False, server_default="15",
        ),
        sa.Column(
            "bloom_target_level",
            sa.String(20), nullable=False, server_default="understand",
        ),
        sa.Column(
            "syllabus_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("syllabi.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding_id", sa.Text(), nullable=True),
        sa.Column(
            "mastery_threshold", sa.Float(), nullable=False, server_default="0.75",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_topics_slug", "topics", ["slug"])
    op.create_index("ix_topics_syllabus_id", "topics", ["syllabus_id"])

    # --- topic_edges ---
    op.create_table(
        "topic_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parent_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relationship_type",
            sa.String(30), nullable=False, server_default="direct_prerequisite",
        ),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_by",
            sa.String(20), nullable=False, server_default="llm_inferred",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "parent_topic_id", "child_topic_id", name="uq_topic_edge_pair",
        ),
    )
    op.create_index(
        "ix_topic_edges_parent_topic_id", "topic_edges", ["parent_topic_id"],
    )
    op.create_index(
        "ix_topic_edges_child_topic_id", "topic_edges", ["child_topic_id"],
    )

    # --- topic_closure ---
    op.create_table(
        "topic_closure",
        sa.Column(
            "ancestor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "descendant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("depth", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_topic_closure_ancestor_id", "topic_closure", ["ancestor_id"],
    )
    op.create_index(
        "ix_topic_closure_descendant_id", "topic_closure", ["descendant_id"],
    )

    # --- trusted_channels ---
    op.create_table(
        "trusted_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_name", sa.String(256), unique=True, nullable=False,
        ),
        sa.Column(
            "authority_tier", sa.Integer(), nullable=False, server_default="5",
        ),
    )

    # --- resources ---
    op.create_table(
        "resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(20), nullable=False, server_default="web"),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why_recommended", sa.Text(), nullable=True),
        sa.Column(
            "relevance_score", sa.Float(), nullable=False, server_default="0.0",
        ),
        sa.Column(
            "difficulty",
            sa.String(20), nullable=False, server_default="intermediate",
        ),
        sa.Column("embedding_id", sa.Text(), nullable=True),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_resources_topic_id", "resources", ["topic_id"])

    # --- youtube_resources ---
    op.create_table(
        "youtube_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("video_id", sa.String(20), nullable=False),
        sa.Column("channel_name", sa.String(256), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "duration_seconds", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column(
            "relevance_score", sa.Float(), nullable=False, server_default="0.0",
        ),
        sa.Column("transcript_summary", sa.Text(), nullable=True),
        sa.Column("embedding_id", sa.Text(), nullable=True),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_youtube_resources_topic_id", "youtube_resources", ["topic_id"],
    )
    op.create_index(
        "ix_youtube_resources_video_id", "youtube_resources", ["video_id"],
    )

    # --- quiz_questions ---
    op.create_table(
        "quiz_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("concept_tag", sa.String(200), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "difficulty", sa.String(20), nullable=False, server_default="medium",
        ),
        sa.Column(
            "bloom_level",
            sa.String(20), nullable=False, server_default="understand",
        ),
        sa.Column(
            "estimated_time_seconds",
            sa.Integer(), nullable=False, server_default="60",
        ),
        sa.Column(
            "confidence_score", sa.Float(), nullable=False, server_default="1.0",
        ),
        sa.Column(
            "question_tag", postgresql.ARRAY(sa.Text()), nullable=True,
        ),
        sa.Column("embedding_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_quiz_questions_topic_id", "quiz_questions", ["topic_id"],
    )
    op.create_index(
        "ix_quiz_questions_concept_tag", "quiz_questions", ["concept_tag"],
    )
    # Section 15.4: bank-lookup hot-path composite index
    op.create_index(
        "ix_quiz_questions_bank_lookup",
        "quiz_questions",
        ["topic_id", "difficulty", "concept_tag"],
    )

    # --- sessions (before quiz_attempts FK) ---
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("path_stack", postgresql.JSONB(), nullable=True),
        sa.Column("graph_checkpoint_id", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active",
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # --- quiz_attempts ---
    op.create_table(
        "quiz_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("ratio_current_vs_prereq", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"])
    op.create_index("ix_quiz_attempts_topic_id", "quiz_attempts", ["topic_id"])
    op.create_index(
        "ix_quiz_attempts_session_id", "quiz_attempts", ["session_id"],
    )

    # --- quiz_attempt_answers ---
    op.create_table(
        "quiz_attempt_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quiz_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("selected_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column(
            "time_taken_seconds", sa.Integer(), nullable=False, server_default="0",
        ),
    )
    op.create_index(
        "ix_quiz_attempt_answers_attempt_id",
        "quiz_attempt_answers", ["attempt_id"],
    )
    op.create_index(
        "ix_quiz_attempt_answers_question_id",
        "quiz_attempt_answers", ["question_id"],
    )

    # --- concept_mastery ---
    op.create_table(
        "concept_mastery",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("last_practiced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts_count", sa.Integer(), nullable=False, server_default="0",
        ),
    )
    op.create_index(
        "ix_concept_mastery_user_id", "concept_mastery", ["user_id"],
    )
    op.create_index(
        "ix_concept_mastery_topic_id", "concept_mastery", ["topic_id"],
    )

    # --- preferences ---
    op.create_table(
        "preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("notification_settings", postgresql.JSONB(), nullable=True),
        sa.Column("theme", sa.String(50), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True),
    )

    # --- analytics_events ---
    op.create_table(
        "analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_analytics_events_user_id", "analytics_events", ["user_id"],
    )
    op.create_index(
        "ix_analytics_events_session_id", "analytics_events", ["session_id"],
    )
    op.create_index(
        "ix_analytics_events_event_type", "analytics_events", ["event_type"],
    )
    op.create_index(
        "ix_analytics_events_created_at", "analytics_events", ["created_at"],
    )
    # Section 15.4: composite (user_id, event_type, created_at) for dashboards
    op.create_index(
        "ix_analytics_events_dashboard",
        "analytics_events",
        ["user_id", "event_type", "created_at"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("preferences")
    op.drop_table("concept_mastery")
    op.drop_table("quiz_attempt_answers")
    op.drop_table("quiz_attempts")
    op.drop_table("sessions")
    op.drop_table("quiz_questions")
    op.drop_table("youtube_resources")
    op.drop_table("resources")
    op.drop_table("trusted_channels")
    op.drop_table("topic_closure")
    op.drop_table("topic_edges")
    op.drop_table("topics")
    op.drop_table("syllabi")
    op.drop_table("refresh_tokens")
    op.drop_table("student_profiles")
    op.drop_table("users")
    _drop_enums()
