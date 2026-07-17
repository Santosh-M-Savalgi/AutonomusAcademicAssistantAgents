"""QuizService — AI-powered quiz generation (Sprint 3 Phase C).

Responsibilities:
- Generate quiz for one topic
- Multiple-choice questions
- Difficulty based on mastery level
- Validate response schema
- Return structured quiz object

QuizService does NOT evaluate answers. Evaluation is handled by
EvaluationService.
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
class QuizQuestion:
    """A single multiple-choice question."""

    id: str
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    difficulty: str = "medium"  # easy, medium, hard
    concept_tag: str = "general"
    bloom_level: str = "understand"
    estimated_time_seconds: int = 60


@dataclass
class Quiz:
    """A complete quiz for one topic."""

    topic_id: str
    topic_name: str
    questions: list[QuizQuestion] = field(default_factory=list)
    total_questions: int = 0
    difficulty_breakdown: dict = field(default_factory=lambda: {"easy": 0, "medium": 0, "hard": 0})


# ── Quiz prompt templates ───────────────────────────────────────────────────


QUIZ_SYSTEM_PROMPT = """You are an expert quiz generator for adaptive learning systems.

Generate multiple-choice questions following these rules:
1. Each question must have EXACTLY 4 options (A, B, C, D)
2. Exactly one option must be correct
3. Questions must test genuine understanding, not trivia
4. Distractors must be plausible but incorrect
5. Include a clear explanation of why the correct answer is right
6. Tag each question with the specific sub-concept it tests

Difficulty guidelines:
- easy: Tests basic recall and recognition (Bloom: remember/understand)
- medium: Tests application and comprehension (Bloom: understand/apply)
- hard: Tests analysis and synthesis (Bloom: analyze/evaluate)

Respond ONLY with valid JSON matching this structure:
{
  "questions": [
    {
      "id": "q1",
      "question": "Question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "Option A",
      "explanation": "Explanation of why this is correct",
      "difficulty": "easy|medium|hard",
      "concept_tag": "specific_sub_concept",
      "bloom_level": "remember|understand|apply|analyze|evaluate|create",
      "estimated_time_seconds": 60
    }
  ]
}"""


def _build_quiz_prompt(
    topic_name: str,
    topic_description: str,
    topic_difficulty: str,
    mastery_score: float,
    num_questions: int = 5,
    prerequisite_topics: list[dict] | None = None,
) -> str:
    """Build a structured quiz generation prompt."""
    parts = [f"Generate a quiz for the topic: {topic_name}"]
    parts.append(f"Description: {topic_description}")
    parts.append(f"Topic difficulty: {topic_difficulty}")
    parts.append(f"Student's current mastery score: {mastery_score:.2f}")
    parts.append(f"Number of questions: {num_questions}")

    # Determine difficulty distribution based on mastery
    if mastery_score < 0.5:
        parts.append("Difficulty distribution: 70% easy, 30% medium (student is struggling)")
    elif mastery_score < 0.75:
        parts.append("Difficulty distribution: 40% easy, 40% medium, 20% hard (student is developing)")
    else:
        parts.append("Difficulty distribution: 20% medium, 80% hard (student is proficient)")

    if prerequisite_topics:
        prereq_summary = "; ".join(
            f"{p.get('name', 'unknown')} (score: {p.get('mastery', 0):.2f})"
            for p in prerequisite_topics
        )
        parts.append(f"Prerequisite topics: {prereq_summary}")

    parts.append("\nGenerate a structured JSON quiz as specified in the system prompt.")
    return "\n\n".join(parts)


# ── QuizService ─────────────────────────────────────────────────────────────


class QuizService:
    """Generates structured multiple-choice quizzes for a single topic.

    QuizService is stateless — it receives a topic + context, calls the
    LLM provider, and returns a normalized Quiz object.
    """

    def __init__(self, provider: BaseProvider | None = None):
        self._provider = provider

    def _get_provider(self) -> BaseProvider:
        if self._provider is not None:
            return self._provider
        factory = ProviderFactory.from_settings()
        self._provider = factory.get_provider()
        return self._provider

    async def generate_quiz(
        self,
        topic_name: str,
        topic_description: str,
        topic_difficulty: str = "beginner",
        mastery_score: float = 0.0,
        num_questions: int = 5,
        prerequisite_topics: list[dict] | None = None,
    ) -> Quiz:
        """Generate a quiz for the given topic.

        Args:
            topic_name: The name of the topic to quiz on.
            topic_description: A description of the topic.
            topic_difficulty: Difficulty level (beginner, intermediate, advanced).
            mastery_score: Current mastery score (0.0–1.0) for difficulty weighting.
            num_questions: Number of questions to generate.
            prerequisite_topics: Optional list of prerequisite topic data.

        Returns:
            A ``Quiz`` object with multiple-choice questions.

        Raises:
            ProviderError: If the LLM provider fails.
        """
        provider = self._get_provider()
        prompt = _build_quiz_prompt(
            topic_name=topic_name,
            topic_description=topic_description,
            topic_difficulty=topic_difficulty,
            mastery_score=mastery_score,
            num_questions=num_questions,
            prerequisite_topics=prerequisite_topics,
        )

        response = await provider.generate(
            prompt,
            system_prompt=QUIZ_SYSTEM_PROMPT,
            temperature=0.4,
        )

        return self._parse_quiz_response(response.content, topic_name)

    def _parse_quiz_response(self, content: str, topic_name: str) -> Quiz:
        """Parse the provider response into a Quiz object.

        Validates that each question has exactly 4 options, one correct answer,
        and all required fields.
        """
        json_str = content.strip()
        if json_str.startswith("```"):
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
            return Quiz(
                topic_id="",
                topic_name=topic_name,
                questions=[],
                total_questions=0,
            )

        questions_data = data.get("questions", [])
        questions: list[QuizQuestion] = []
        diff_breakdown = {"easy": 0, "medium": 0, "hard": 0}

        for i, q in enumerate(questions_data):
            options = q.get("options", [])
            # Validate: must have exactly 4 options
            if len(options) != 4:
                continue

            # Validate: correct_answer must be one of the options
            correct = q.get("correct_answer", "")
            if correct not in options:
                continue

            diff = q.get("difficulty", "medium")
            if diff in diff_breakdown:
                diff_breakdown[diff] += 1

            questions.append(QuizQuestion(
                id=q.get("id", f"q{i+1}"),
                question=q.get("question", ""),
                options=list(options),
                correct_answer=correct,
                explanation=q.get("explanation", ""),
                difficulty=diff,
                concept_tag=q.get("concept_tag", "general"),
                bloom_level=q.get("bloom_level", "understand"),
                estimated_time_seconds=q.get("estimated_time_seconds", 60),
            ))

        return Quiz(
            topic_id="",
            topic_name=topic_name,
            questions=questions,
            total_questions=len(questions),
            difficulty_breakdown=diff_breakdown,
        )
