"""Tests for Sprint 3 Phase C — QuizService.

Covers: quiz generation, response parsing, schema validation (4 options,
correct answer in options), difficulty distribution, prerequisite topics,
and error handling.
"""

from __future__ import annotations

import json

import pytest

from app.llm.providers.mock import MockProvider
from app.llm.quiz_service import Quiz, QuizQuestion, QuizService, _build_quiz_prompt


class TestQuizPrompt:
    def test_build_prompt_basic(self) -> None:
        prompt = _build_quiz_prompt(
            topic_name="Python Lists",
            topic_description="Ordered collections in Python",
            topic_difficulty="beginner",
            mastery_score=0.5,
            num_questions=5,
        )
        assert "Python Lists" in prompt
        assert "5" in prompt
        assert "developing" in prompt or "0.50" in prompt

    def test_build_prompt_difficulty_by_mastery_low(self) -> None:
        prompt = _build_quiz_prompt(
            topic_name="Test",
            topic_description="",
            topic_difficulty="beginner",
            mastery_score=0.3,
        )
        assert "struggling" in prompt

    def test_build_prompt_difficulty_by_mastery_high(self) -> None:
        prompt = _build_quiz_prompt(
            topic_name="Test",
            topic_description="",
            topic_difficulty="advanced",
            mastery_score=0.85,
        )
        assert "proficient" in prompt

    def test_build_prompt_with_prerequisites(self) -> None:
        prompt = _build_quiz_prompt(
            topic_name="NumPy",
            topic_description="",
            topic_difficulty="intermediate",
            mastery_score=0.6,
            prerequisite_topics=[
                {"name": "Lists", "mastery": 0.9},
                {"name": "Loops", "mastery": 0.4},
            ],
        )
        assert "Lists" in prompt
        assert "Loops" in prompt
        assert "0.40" in prompt or "0.9" in prompt


class TestQuizService:
    @pytest.fixture
    def service(self) -> QuizService:
        provider = MockProvider()
        return QuizService(provider=provider)

    @pytest.mark.asyncio
    async def test_generate_quiz_basic(self, service: QuizService) -> None:
        service._provider.add_quiz_rule("Python")

        quiz = await service.generate_quiz(
            topic_name="Python",
            topic_description="Programming language",
            topic_difficulty="beginner",
            mastery_score=0.5,
        )

        assert quiz.topic_name == "Python"
        assert quiz.total_questions > 0

    @pytest.mark.asyncio
    async def test_generate_quiz_with_prerequisites(self, service: QuizService) -> None:
        service._provider.add_quiz_rule("Advanced Topic")

        quiz = await service.generate_quiz(
            topic_name="Advanced Topic",
            topic_description="Topic with prereqs",
            topic_difficulty="advanced",
            mastery_score=0.3,
            num_questions=3,
            prerequisite_topics=[
                {"id": "p1", "name": "Basics", "mastery": 0.7},
            ],
        )

        assert quiz.total_questions > 0

    @pytest.mark.asyncio
    async def test_parse_quiz_response_valid(self, service: QuizService) -> None:
        content = json.dumps({
            "questions": [
                {
                    "id": "q1",
                    "question": "What is Python?",
                    "options": ["A language", "A snake", "A tool", "A game"],
                    "correct_answer": "A language",
                    "explanation": "Python is a programming language",
                    "difficulty": "easy",
                    "concept_tag": "basics",
                    "bloom_level": "remember",
                    "estimated_time_seconds": 30,
                },
                {
                    "id": "q2",
                    "question": "What is a list?",
                    "options": ["Ordered", "Unordered", "Set", "Tuple"],
                    "correct_answer": "Ordered",
                    "explanation": "Lists are ordered",
                    "difficulty": "medium",
                    "concept_tag": "data_structures",
                    "bloom_level": "understand",
                    "estimated_time_seconds": 45,
                },
            ],
        })

        quiz = service._parse_quiz_response(content, "Python")

        assert quiz.total_questions == 2
        assert quiz.difficulty_breakdown["easy"] == 1
        assert quiz.difficulty_breakdown["medium"] == 1

    @pytest.mark.asyncio
    async def test_parse_quiz_validates_options_count(self, service: QuizService) -> None:
        """Questions with != 4 options should be filtered out."""
        content = json.dumps({
            "questions": [
                {
                    "id": "q1",
                    "question": "Valid?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "A",
                    "explanation": "OK",
                    "difficulty": "easy",
                    "concept_tag": "t",
                },
                {
                    "id": "q2",
                    "question": "Invalid (3 options)?",
                    "options": ["A", "B", "C"],
                    "correct_answer": "A",
                    "explanation": "Bad",
                    "difficulty": "easy",
                    "concept_tag": "t",
                },
            ],
        })

        quiz = service._parse_quiz_response(content, "Test")
        assert quiz.total_questions == 1

    @pytest.mark.asyncio
    async def test_parse_quiz_validates_correct_in_options(self, service: QuizService) -> None:
        """Questions where correct_answer isn't in options should be filtered."""
        content = json.dumps({
            "questions": [
                {
                    "id": "q1",
                    "question": "Valid?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "A",
                    "explanation": "OK",
                    "difficulty": "easy",
                    "concept_tag": "t",
                },
                {
                    "id": "q2",
                    "question": "Invalid?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "Z",  # Not in options
                    "explanation": "Bad",
                    "difficulty": "easy",
                    "concept_tag": "t",
                },
            ],
        })

        quiz = service._parse_quiz_response(content, "Test")
        assert quiz.total_questions == 1

    @pytest.mark.asyncio
    async def test_parse_invalid_json_returns_empty(self, service: QuizService) -> None:
        quiz = service._parse_quiz_response("not json", "Empty")
        assert quiz.total_questions == 0
        assert quiz.topic_name == "Empty"

    @pytest.mark.asyncio
    async def test_parse_with_markdown_fences(self, service: QuizService) -> None:
        content = '```json\n{"questions": [{"id": "q1", "question": "Q?", "options": ["A","B","C","D"], "correct_answer": "A", "explanation": "E", "difficulty": "easy", "concept_tag": "t"}]}\n```'

        quiz = service._parse_quiz_response(content, "Test")
        assert quiz.total_questions == 1

    def test_quiz_question_dataclass(self) -> None:
        q = QuizQuestion(
            id="q1", question="Test?", options=["A", "B", "C", "D"],
            correct_answer="A", explanation="E",
        )
        assert q.difficulty == "medium"  # default
        assert q.estimated_time_seconds == 60  # default

    def test_quiz_dataclass(self) -> None:
        quiz = Quiz(topic_id="t1", topic_name="Test")
        assert quiz.total_questions == 0
        assert quiz.difficulty_breakdown == {"easy": 0, "medium": 0, "hard": 0}
