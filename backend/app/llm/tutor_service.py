"""TutorService — AI-powered lesson generation (Sprint 3 Phase B).

Responsibilities:
- Receive topic from AdaptiveRouter
- Retrieve topic context (via repository/get_topic_context bridge)
- Build structured teaching prompt
- Request lesson from Provider
- Return normalized lesson response

TutorService does NOT make curriculum decisions. It only teaches
the topic it receives. Curriculum decisions belong to AdaptiveRouter.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from app.llm.providers.base import (
    BaseProvider,
    ProviderError,
)
from app.llm.provider_router import ProviderFactory


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class TeachingCard:
    """A single micro-learning card within a lesson."""

    title: str
    body: str
    card_type: str = "concept"  # concept | example | analogy | takeaway


@dataclass
class Lesson:
    """A complete lesson for one topic."""

    topic_id: str
    topic_name: str
    title: str
    cards: list[TeachingCard] = field(default_factory=list)
    estimated_minutes: int = 5
    learning_mode: str = "journey"


# ── Teaching prompt templates ───────────────────────────────────────────────


TEACHING_SYSTEM_PROMPT = """You are an expert tutor generating structured micro-learning content.

Generate a lesson that follows these rules:
1. Each card teaches ONE concept with ONE explanation (2-4 sentences)
2. Include ONE example per card (code, diagram, or real-world analogy)
3. End each card with ONE takeaway sentence
4. Use clear, simple language appropriate for the student's current level
5. Format the response as valid JSON

Learning mode determines lesson length:
- sprint: 2-3 cards, definition + one example, minimal theory
- journey: 4-7 cards, explanation + example + analogy + mini-checkpoint
- mastery: 7-10 cards, theory + implementation + edge cases + advanced example

Respond ONLY with valid JSON matching this structure:
{
  "title": "Lesson title",
  "cards": [
    {
      "title": "Card title",
      "body": "Card body with explanation, example, and takeaway",
      "card_type": "concept|example|analogy|takeaway"
    }
  ],
  "estimated_minutes": 5
}"""


def _build_teaching_prompt(
    topic_name: str,
    topic_description: str,
    topic_difficulty: str,
    learning_mode: str,
    prerequisite_context: str = "",
    mastery_score: float | None = None,
    student_preferences: dict | None = None,
) -> str:
    """Build a structured teaching prompt from topic context."""
    parts = [f"Teach me the topic: {topic_name}"]
    parts.append(f"Description: {topic_description}")
    parts.append(f"Difficulty: {topic_difficulty}")
    parts.append(f"Learning mode: {learning_mode}")

    if prerequisite_context:
        parts.append(f"Prerequisite context (already covered): {prerequisite_context}")

    if mastery_score is not None:
        parts.append(f"Student's current mastery score: {mastery_score:.2f}")

    if student_preferences:
        pref_summary = []
        if student_preferences.get("prefers_analogies", 0) > 0.5:
            pref_summary.append("Include analogies")
        if student_preferences.get("prefers_code_examples", 0) > 0.5:
            pref_summary.append("Include code examples")
        if student_preferences.get("prefers_shorter_lessons", 0) > 0.5:
            pref_summary.append("Keep lessons concise")
        if pref_summary:
            parts.append(f"Student preferences: {', '.join(pref_summary)}")

    parts.append("\nGenerate a structured JSON lesson as specified in the system prompt.")
    return "\n\n".join(parts)


# ── TutorService ────────────────────────────────────────────────────────────


class TutorService:
    """Generates structured lessons for a single topic.

    TutorService is stateless — it receives a topic + context, calls the
    LLM provider, and returns a normalized Lesson object.
    """

    def __init__(self, provider: BaseProvider | None = None):
        self._provider = provider

    def _get_provider(self) -> BaseProvider:
        """Return the configured provider or the default."""
        if self._provider is not None:
            return self._provider
        factory = ProviderFactory.from_settings()
        self._provider = factory.get_provider()
        return self._provider

    async def generate_lesson(
        self,
        topic_name: str,
        topic_description: str,
        topic_difficulty: str = "beginner",
        learning_mode: str = "journey",
        prerequisite_context: str = "",
        mastery_score: float | None = None,
        student_preferences: dict | None = None,
    ) -> Lesson:
        """Generate a lesson for the given topic.

        Args:
            topic_name: The name of the topic to teach.
            topic_description: A description of the topic.
            topic_difficulty: Difficulty level (beginner, intermediate, advanced).
            learning_mode: Lesson length mode (sprint, journey, mastery).
            prerequisite_context: Text describing prerequisites already covered.
            mastery_score: Optional current mastery score.
            student_preferences: Optional student learning preferences.

        Returns:
            A ``Lesson`` object with structured teaching cards.

        Raises:
            ProviderError: If the LLM provider fails.
        """
        provider = self._get_provider()
        prompt = _build_teaching_prompt(
            topic_name=topic_name,
            topic_description=topic_description,
            topic_difficulty=topic_difficulty,
            learning_mode=learning_mode,
            prerequisite_context=prerequisite_context,
            mastery_score=mastery_score,
            student_preferences=student_preferences,
        )

        response = await provider.generate(
            prompt,
            system_prompt=TEACHING_SYSTEM_PROMPT,
            temperature=0.3,
        )

        return self._parse_lesson_response(response.content, topic_name, learning_mode)

    def _parse_lesson_response(self, content: str, topic_name: str, learning_mode: str = "journey") -> Lesson:
        """Parse the provider response into a Lesson object.

        Handles JSON parsing and provides graceful fallback for
        malformed responses.
        """
        # Try to extract JSON from the response (handle markdown code fences)
        json_str = content.strip()
        if json_str.startswith("```"):
            # Remove markdown code fences
            lines = json_str.split("\n")
            cleaned = []
            in_fence = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_fence = True
                    continue
                if in_fence:
                    cleaned.append(line)
            json_str = "\n".join(cleaned)

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            # Fallback: create a minimal lesson from raw text
            return Lesson(
                topic_id="",
                topic_name=topic_name,
                title=topic_name,
                cards=[
                    TeachingCard(
                        title=topic_name,
                        body=content[:2000],
                        card_type="concept",
                    )
                ],
                estimated_minutes=5,
                learning_mode="journey",
            )

        title = data.get("title", topic_name)
        cards_data = data.get("cards", [])
        estimated = data.get("estimated_minutes", 5)

        cards = []
        for c in cards_data:
            cards.append(TeachingCard(
                title=c.get("title", "Untitled"),
                body=c.get("body", ""),
                card_type=c.get("card_type", "concept"),
            ))

        return Lesson(
            topic_id="",
            topic_name=topic_name,
            title=title,
            cards=cards or [
                TeachingCard(title=topic_name, body=content[:500], card_type="concept"),
            ],
            estimated_minutes=estimated,
            learning_mode=learning_mode,
        )
