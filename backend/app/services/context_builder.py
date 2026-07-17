"""Context Builder — assemble retrieval context for TutorService and QuizService (Sprint 4 Phase F).

Responsibilities:
- Combine retrieved chunks with topic metadata
- Incorporate prerequisite summaries from prerequisite chunks
- Include learning objectives and mastery information
- Respect configurable token limits (estimated ~4 chars per token)
- Rank retrieved context by relevance score

Does NOT generate prompts — it prepares the *information* that the
prompt builders in TutorService and QuizService consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.retrieval_service import RetrievalResult, RetrievedChunk


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class TutorContext:
    """Assembled context for the TutorService.

    This is the structured information payload that the TutorService
    prompt builder receives instead of raw strings.
    """

    topic_name: str
    topic_description: str
    relevant_chunks: list[dict] = field(default_factory=list)
    prerequisite_summaries: list[str] = field(default_factory=list)
    learning_objectives: list[str] = field(default_factory=list)
    mastery_score: float = 0.0
    estimated_tokens: int = 0


@dataclass
class QuizContext:
    """Assembled context for the QuizService."""

    topic_name: str
    topic_description: str
    relevant_chunks: list[dict] = field(default_factory=list)
    prerequisite_topics: list[dict] = field(default_factory=list)
    mastery_score: float = 0.0
    estimated_tokens: int = 0


# ── ContextBuilder ──────────────────────────────────────────────────────────


class ContextBuilder:
    """Assembles retrieval context for TutorService and QuizService.

    Usage::

        builder = ContextBuilder(max_context_tokens=2000)
        tutor_ctx = builder.build_tutor_context(
            topic_name="Python Lists",
            topic_description="Ordered collections in Python",
            retrieval_result=retrieval_result,
            mastery_score=0.5,
        )
    """

    def __init__(self, max_context_tokens: int = 2000):
        """Initialize the context builder.

        Args:
            max_context_tokens: Maximum estimated tokens for assembled
                context. The builder will truncate chunks if this limit
                is exceeded. Default 2000 (~8000 chars at 4 chars/token).
        """
        self.max_context_tokens = max_context_tokens
        # Rough estimation: ~4 characters per token for English text
        self._chars_per_token = 4

    def _estimate_tokens(self, text: str) -> int:
        """Rough token count estimation."""
        return len(text) // self._chars_per_token

    def build_tutor_context(
        self,
        topic_name: str,
        topic_description: str,
        retrieval_result: RetrievalResult | None = None,
        prerequisite_context: str = "",
        mastery_score: float = 0.0,
        learning_objectives: list[str] | None = None,
    ) -> TutorContext:
        """Build context for lesson generation.

        Args:
            topic_name: Name of the topic to teach.
            topic_description: Description of the topic.
            retrieval_result: Optional result from RetrievalService.
            prerequisite_context: Optional text describing prerequisites.
            mastery_score: Current mastery score (0.0-1.0).
            learning_objectives: Optional learning objectives.

        Returns:
            A ``TutorContext`` with assembled information.
        """
        relevant_chunks: list[dict] = []
        prerequisite_summaries: list[str] = []
        estimated_tokens = 0
        chars_consumed = 0
        max_chars = self.max_context_tokens * self._chars_per_token

        # Process primary chunks
        if retrieval_result:
            for chunk in retrieval_result.chunks:
                chunk_chars = len(chunk.content) + len(" ".join(chunk.headings))
                if chars_consumed + chunk_chars > max_chars:
                    break

                chunk_dict = {
                    "content": chunk.content,
                    "score": chunk.score,
                    "headings": chunk.headings,
                    "topic_tags": chunk.topic_tags,
                    "source_type": chunk.source_type,
                }
                relevant_chunks.append(chunk_dict)
                chars_consumed += chunk_chars

            # Process prerequisite chunks
            for chunk in retrieval_result.prerequisite_chunks:
                chunk_chars = len(chunk.content) + 50  # 50 char overhead for formatting
                if chars_consumed + chunk_chars > max_chars:
                    break

                summary = f"[From {chunk.source_type or 'source'}]: {chunk.content[:300]}"
                if chunk.content not in prerequisite_summaries:
                    prerequisite_summaries.append(summary)
                    chars_consumed += chunk_chars

        estimated_tokens = chars_consumed // self._chars_per_token

        return TutorContext(
            topic_name=topic_name,
            topic_description=topic_description,
            relevant_chunks=relevant_chunks,
            prerequisite_summaries=prerequisite_summaries + ([prerequisite_context] if prerequisite_context else []),
            learning_objectives=learning_objectives or [],
            mastery_score=mastery_score,
            estimated_tokens=estimated_tokens,
        )

    def build_quiz_context(
        self,
        topic_name: str,
        topic_description: str,
        retrieval_result: RetrievalResult | None = None,
        prerequisite_topics: list[dict] | None = None,
        mastery_score: float = 0.0,
    ) -> QuizContext:
        """Build context for quiz generation.

        Args:
            topic_name: Name of the topic to quiz on.
            topic_description: Description of the topic.
            retrieval_result: Optional result from RetrievalService.
            prerequisite_topics: Optional list of prerequisite topic info.
            mastery_score: Current mastery score (0.0-1.0).

        Returns:
            A ``QuizContext`` with assembled information.
        """
        relevant_chunks: list[dict] = []
        estimated_tokens = 0
        chars_consumed = 0
        max_chars = self.max_context_tokens * self._chars_per_token

        # For quiz context, prioritize chunks with high relevance
        if retrieval_result:
            for chunk in retrieval_result.chunks:
                chunk_chars = len(chunk.content)
                if chars_consumed + chunk_chars > max_chars:
                    break

                chunk_dict = {
                    "content": chunk.content,
                    "score": chunk.score,
                    "headings": chunk.headings,
                    "topic_tags": chunk.topic_tags,
                }
                relevant_chunks.append(chunk_dict)
                chars_consumed += chunk_chars

        estimated_tokens = chars_consumed // self._chars_per_token

        return QuizContext(
            topic_name=topic_name,
            topic_description=topic_description,
            relevant_chunks=relevant_chunks,
            prerequisite_topics=prerequisite_topics or [],
            mastery_score=mastery_score,
            estimated_tokens=estimated_tokens,
        )

    def format_tutor_context_for_prompt(self, ctx: TutorContext) -> str:
        """Format a TutorContext into a plain text block for prompt injection.

        This produces the ``prerequisite_context`` and additional context
        strings that get passed to TutorService's prompt builder.
        """
        parts: list[str] = []

        # Prerequisite summaries
        if ctx.prerequisite_summaries:
            parts.append("## Prerequisite Context")
            for summary in ctx.prerequisite_summaries:
                parts.append(f"- {summary}")

        # Relevant chunks
        if ctx.relevant_chunks:
            parts.append("## Source Material")
            for i, chunk in enumerate(ctx.relevant_chunks, 1):
                heading_info = ""
                if chunk.get("headings"):
                    heading_info = f" (from section: {' > '.join(chunk['headings'])})"
                parts.append(f"\n### Source {i}{heading_info}")
                parts.append(chunk["content"])
                parts.append("")

        # Learning objectives
        if ctx.learning_objectives:
            parts.append("## Learning Objectives")
            for obj in ctx.learning_objectives:
                parts.append(f"- {obj}")

        # Mastery context
        if ctx.mastery_score > 0:
            parts.append(f"\n## Current Mastery Level: {ctx.mastery_score:.0%}")

        return "\n".join(parts)

    def format_quiz_context_for_prompt(self, ctx: QuizContext) -> str:
        """Format a QuizContext into a plain text block for prompt injection."""
        parts: list[str] = []

        # Source material
        if ctx.relevant_chunks:
            parts.append("## Source Material for Quiz")
            for i, chunk in enumerate(ctx.relevant_chunks, 1):
                parts.append(f"\n### Source {i}")
                parts.append(chunk["content"])

        # Prerequisite topics
        if ctx.prerequisite_topics:
            parts.append("## Prerequisite Topics")
            for prereq in ctx.prerequisite_topics:
                name = prereq.get("name", "Unknown")
                mastery = prereq.get("mastery", 0.0)
                parts.append(f"- {name} (mastery: {mastery:.0%})")

        # Mastery context
        if ctx.mastery_score > 0:
            parts.append(f"\n## Current Mastery Level: {ctx.mastery_score:.0%}")

        return "\n".join(parts)
