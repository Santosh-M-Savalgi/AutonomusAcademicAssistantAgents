"""Tests for Sprint 3 Phase B — TutorService.

Covers: lesson generation, parsing, prompt building, mock provider integration,
response parsing with markdown fences, and error handling.
"""

from __future__ import annotations

import json

import pytest

from app.llm.providers.mock import MockProvider
from app.llm.tutor_service import (
    Lesson,
    TeachingCard,
    TutorService,
    _build_teaching_prompt,
)


class TestTeachingPrompt:
    def test_build_prompt_basic(self) -> None:
        prompt = _build_teaching_prompt(
            topic_name="Python Lists",
            topic_description="Ordered collections in Python",
            topic_difficulty="beginner",
            learning_mode="journey",
        )
        assert "Python Lists" in prompt
        assert "Ordered collections" in prompt
        assert "beginner" in prompt
        assert "journey" in prompt

    def test_build_prompt_with_prerequisites(self) -> None:
        prompt = _build_teaching_prompt(
            topic_name="NumPy",
            topic_description="Numerical computing in Python",
            topic_difficulty="intermediate",
            learning_mode="mastery",
            prerequisite_context="Python lists, loops, functions",
        )
        assert "Prerequisite context" in prompt
        assert "Python lists, loops, functions" in prompt

    def test_build_prompt_with_mastery_score(self) -> None:
        prompt = _build_teaching_prompt(
            topic_name="Python",
            topic_description="",
            topic_difficulty="beginner",
            learning_mode="sprint",
            mastery_score=0.45,
        )
        assert "0.45" in prompt

    def test_build_prompt_student_preferences(self) -> None:
        prompt = _build_teaching_prompt(
            topic_name="Python",
            topic_description="",
            topic_difficulty="beginner",
            learning_mode="journey",
            student_preferences={
                "prefers_analogies": 0.8,
                "prefers_code_examples": 0.9,
                "prefers_shorter_lessons": 0.3,
            },
        )
        assert "Include analogies" in prompt
        assert "Include code examples" in prompt
        # prefers_shorter_lessons is 0.3, below 0.5 threshold, should NOT appear
        assert "Keep lessons concise" not in prompt


class TestTutorService:
    @pytest.fixture
    def service(self) -> TutorService:
        provider = MockProvider()
        service = TutorService(provider=provider)
        return service

    @pytest.mark.asyncio
    async def test_generate_lesson_basic(self, service: TutorService) -> None:
        # Set up mock response
        service._provider.add_lesson_rule("Python Lists")

        lesson = await service.generate_lesson(
            topic_name="Python Lists",
            topic_description="Ordered collections in Python",
            topic_difficulty="beginner",
        )

        assert lesson.topic_name == "Python Lists"
        assert len(lesson.cards) > 0
        assert lesson.estimated_minutes > 0

    @pytest.mark.asyncio
    async def test_generate_lesson_with_all_params(self, service: TutorService) -> None:
        service._provider.add_lesson_rule("Dictionaries")

        lesson = await service.generate_lesson(
            topic_name="Dictionaries",
            topic_description="Key-value stores in Python",
            topic_difficulty="beginner",
            learning_mode="mastery",
            prerequisite_context="Python variables and lists",
            mastery_score=0.3,
            student_preferences={"prefers_analogies": 0.9},
        )

        assert lesson.topic_name == "Dictionaries"
        assert lesson.learning_mode == "mastery"

    @pytest.mark.asyncio
    async def test_parse_lesson_response_json(self, service: TutorService) -> None:
        content = json.dumps({
            "title": "Python Basics",
            "cards": [
                {"title": "Intro", "body": "Body text", "card_type": "concept"},
                {"title": "Example", "body": "Example text", "card_type": "example"},
            ],
            "estimated_minutes": 5,
        })

        lesson = service._parse_lesson_response(content, "Python Basics")

        assert lesson.title == "Python Basics"
        assert len(lesson.cards) == 2
        assert lesson.cards[0].title == "Intro"
        assert lesson.cards[1].card_type == "example"

    @pytest.mark.asyncio
    async def test_parse_lesson_with_markdown_fences(self, service: TutorService) -> None:
        content = '```json\n{"title": "Test", "cards": [{"title": "C1", "body": "B1", "card_type": "concept"}], "estimated_minutes": 3}\n```'

        lesson = service._parse_lesson_response(content, "Test")

        assert lesson.title == "Test"
        assert len(lesson.cards) == 1

    @pytest.mark.asyncio
    async def test_parse_invalid_json_fallback(self, service: TutorService) -> None:
        content = "This is not JSON at all"

        lesson = service._parse_lesson_response(content, "Fallback Topic")

        assert lesson.title == "Fallback Topic"
        assert len(lesson.cards) == 1
        assert "not JSON" in lesson.cards[0].body or "Fallback" in lesson.title

    @pytest.mark.asyncio
    async def test_provider_failure_propagates(self) -> None:
        # A MockProvider without matching rules uses default
        provider = MockProvider()
        service = TutorService(provider=provider)

        lesson = await service.generate_lesson(
            topic_name="Any Topic",
            topic_description="Desc",
            topic_difficulty="beginner",
        )

        # Should still work with default response + fallback parsing
        assert lesson.topic_name == "Any Topic"
        # The default mock response isn't JSON, so it'll fall back to raw text
        assert lesson.estimated_minutes == 5

    @pytest.mark.asyncio
    async def test_response_has_usage_metadata(self, service: TutorService) -> None:
        provider = service._get_provider()
        response = await provider.generate("test")
        assert response.finish_reason == "stop"
        assert response.model_used == "mock-model"

    def test_teaching_card_dataclass(self) -> None:
        card = TeachingCard(title="Test", body="Body", card_type="concept")
        assert card.title == "Test"
        assert card.card_type == "concept"

    def test_lesson_dataclass(self) -> None:
        cards = [TeachingCard(title="C1", body="B1")]
        lesson = Lesson(topic_id="t1", topic_name="Test", title="Lesson", cards=cards)
        assert lesson.title == "Lesson"
        assert lesson.learning_mode == "journey"  # default
