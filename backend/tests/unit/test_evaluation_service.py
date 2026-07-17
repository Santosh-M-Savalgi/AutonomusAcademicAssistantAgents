"""Tests for Sprint 3 Phase D — EvaluationService.

Covers: deterministic scoring, weak/strong concept tag identification,
feedback generation, routing instruction production, and error handling.
"""

from __future__ import annotations

import pytest

from app.llm.evaluation_service import (
    AnswerSubmission,
    EvaluationResult,
    EvaluationService,
    RoutingInstruction,
    _build_evaluation_prompt,
)
from app.llm.providers.mock import MockProvider


class TestEvaluationPrompt:
    def test_build_prompt(self) -> None:
        prompt = _build_evaluation_prompt(
            topic_name="Python",
            submissions=[
                {
                    "question": "What is Python?",
                    "selected_answer": "A language",
                    "correct_answer": "A language",
                    "is_correct": True,
                    "concept_tag": "basics",
                },
                {
                    "question": "What is a list?",
                    "selected_answer": "Set",
                    "correct_answer": "Ordered",
                    "is_correct": False,
                    "concept_tag": "data_structures",
                },
            ],
        )
        assert "Python" in prompt
        assert "✓ Correct" in prompt
        assert "✗ Incorrect" in prompt
        assert "data_structures" in prompt


class TestEvaluationService:
    @pytest.fixture
    def service(self) -> EvaluationService:
        provider = MockProvider()
        return EvaluationService(provider=provider)

    @pytest.mark.asyncio
    async def test_evaluate_all_correct(self, service: EvaluationService) -> None:
        result = await service.evaluate(
            topic_name="Python",
            questions=[
                {
                    "question_id": "q1",
                    "question": "Q1?",
                    "selected_answer": "A",
                    "correct_answer": "A",
                    "is_correct": True,
                    "concept_tag": "basics",
                    "time_taken_seconds": 30,
                },
                {
                    "question_id": "q2",
                    "question": "Q2?",
                    "selected_answer": "B",
                    "correct_answer": "B",
                    "is_correct": True,
                    "concept_tag": "basics",
                    "time_taken_seconds": 45,
                },
            ],
        )

        assert result.score == 1.0
        assert result.correct_count == 2
        assert result.incorrect_count == 0
        assert result.total_questions == 2

    @pytest.mark.asyncio
    async def test_evaluate_partial(self, service: EvaluationService) -> None:
        result = await service.evaluate(
            topic_name="Test",
            questions=[
                {"question_id": "q1", "question": "Q1?", "selected_answer": "A", "correct_answer": "A", "is_correct": True, "concept_tag": "easy", "time_taken_seconds": 30},
                {"question_id": "q2", "question": "Q2?", "selected_answer": "B", "correct_answer": "C", "is_correct": False, "concept_tag": "hard", "time_taken_seconds": 60},
                {"question_id": "q3", "question": "Q3?", "selected_answer": "A", "correct_answer": "A", "is_correct": True, "concept_tag": "medium", "time_taken_seconds": 45},
                {"question_id": "q4", "question": "Q4?", "selected_answer": "D", "correct_answer": "A", "is_correct": False, "concept_tag": "hard", "time_taken_seconds": 90},
            ],
        )

        assert result.score == 0.5
        assert result.correct_count == 2
        assert result.incorrect_count == 2

    @pytest.mark.asyncio
    async def test_evaluate_all_incorrect(self, service: EvaluationService) -> None:
        result = await service.evaluate(
            topic_name="Test",
            questions=[
                {"question_id": "q1", "question": "Q1?", "selected_answer": "B", "correct_answer": "A", "is_correct": False, "concept_tag": "t1"},
                {"question_id": "q2", "question": "Q2?", "selected_answer": "C", "correct_answer": "A", "is_correct": False, "concept_tag": "t2"},
            ],
        )

        assert result.score == 0.0
        assert result.correct_count == 0

    @pytest.mark.asyncio
    async def test_weak_strong_concept_tags(self, service: EvaluationService) -> None:
        result = await service.evaluate(
            topic_name="Test",
            questions=[
                {"question_id": "q1", "question": "Q1?", "selected_answer": "A", "correct_answer": "A", "is_correct": True, "concept_tag": "strong_1"},
                {"question_id": "q2", "question": "Q2?", "selected_answer": "B", "correct_answer": "B", "is_correct": True, "concept_tag": "strong_2"},
                {"question_id": "q3", "question": "Q3?", "selected_answer": "C", "correct_answer": "A", "is_correct": False, "concept_tag": "weak_1"},
                {"question_id": "q4", "question": "Q4?", "selected_answer": "D", "correct_answer": "A", "is_correct": False, "concept_tag": "weak_2"},
            ],
        )

        assert "strong_1" in result.strong_concept_tags
        assert "strong_2" in result.strong_concept_tags
        assert "weak_1" in result.weak_concept_tags
        assert "weak_2" in result.weak_concept_tags

    @pytest.mark.asyncio
    async def test_tags_both_correct_and_incorrect_are_neutral(self, service: EvaluationService) -> None:
        """A tag that appears in both correct and incorrect answers should not be in weak."""
        result = await service.evaluate(
            topic_name="Test",
            questions=[
                {"question_id": "q1", "question": "Q1?", "selected_answer": "A", "correct_answer": "A", "is_correct": True, "concept_tag": "mixed"},
                {"question_id": "q2", "question": "Q2?", "selected_answer": "B", "correct_answer": "A", "is_correct": False, "concept_tag": "mixed"},
            ],
        )

        assert "mixed" not in result.weak_concept_tags
        assert "mixed" in result.strong_concept_tags

    @pytest.mark.asyncio
    async def test_empty_questions(self, service: EvaluationService) -> None:
        result = await service.evaluate(
            topic_name="Empty",
            questions=[],
        )

        assert result.score == 0.0
        assert result.total_questions == 0
        assert result.correct_count == 0

    def test_routing_instruction(self, service: EvaluationService) -> None:
        result = EvaluationResult(
            score=0.85,
            total_questions=4,
            correct_count=3,
            incorrect_count=1,
            weak_concept_tags=["loops"],
        )

        from app.services.adaptive_routing import RoutingDecision, RoutingResult

        adapter_result = RoutingResult(
            decision=RoutingDecision.NEXT_TOPIC,
            current_topic_id=None,  # We'll convert using the service
            next_topic_id=None,
            weak_concept_report=None,
            reason="Score above threshold",
        )

        instruction = service.produce_routing_instruction(
            result=result,
            current_topic_id="topic-uuid-123",
            adaptive_router_result=adapter_result,
        )

        assert instruction.decision == "NEXT_TOPIC"
        assert instruction.current_topic_id == "topic-uuid-123"
        assert instruction.reason == "Score above threshold"
        assert "loops" in instruction.weak_concepts

    def test_routing_instruction_revisit(self, service: EvaluationService) -> None:
        result = EvaluationResult(
            score=0.4,
            total_questions=5,
            correct_count=2,
            incorrect_count=3,
            weak_concept_tags=["prereq_math"],
        )

        from app.services.adaptive_routing import RoutingDecision, RoutingResult

        adapter_result = RoutingResult(
            decision=RoutingDecision.REVISIT_PREREQUISITE,
            current_topic_id=None,
            next_topic_id="prereq-uuid",
            weak_concept_report=None,
            reason="Prerequisite deficiency detected",
        )

        instruction = service.produce_routing_instruction(
            result=result,
            current_topic_id="topic-uuid-123",
            adaptive_router_result=adapter_result,
        )

        assert instruction.decision == "REVISIT_PREREQUISITE"
        assert instruction.next_topic_id == "prereq-uuid"

    def test_fallback_feedback_high(self, service: EvaluationService) -> None:
        feedback = service._build_fallback_feedback(0.9, 9, 10)
        assert "Great work" in feedback

    def test_fallback_feedback_medium(self, service: EvaluationService) -> None:
        feedback = service._build_fallback_feedback(0.6, 3, 5)
        assert "Good effort" in feedback

    def test_fallback_feedback_low(self, service: EvaluationService) -> None:
        feedback = service._build_fallback_feedback(0.3, 1, 4)
        assert "more work" in feedback or "answered 1/4" in feedback
