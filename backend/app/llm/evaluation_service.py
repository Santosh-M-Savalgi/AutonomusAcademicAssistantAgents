"""EvaluationService — quiz answer evaluation and routing (Sprint 3 Phase D).

Responsibilities:
- Evaluate quiz answers
- Calculate score
- Update MasteryEngine
- Invoke AdaptiveRouter
- Produce routing decision

EvaluationService does NOT generate new lessons or new quizzes.
Those are separate concerns handled by TutorService and QuizService.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.llm.providers.base import (
    BaseProvider,
    ProviderError,
)
from app.llm.provider_router import ProviderFactory


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class AnswerSubmission:
    """A single answer submitted by the student."""

    question_id: str
    selected_answer: str
    correct_answer: str
    is_correct: bool = False
    time_taken_seconds: int = 30


@dataclass
class EvaluationResult:
    """The result of evaluating a quiz attempt."""

    score: float  # 0.0–1.0
    total_questions: int
    correct_count: int
    incorrect_count: int
    submissions: list[AnswerSubmission] = field(default_factory=list)
    weak_concept_tags: list[str] = field(default_factory=list)
    strong_concept_tags: list[str] = field(default_factory=list)
    feedback: str = ""


@dataclass
class RoutingInstruction:
    """Routing decision produced by EvaluationService.

    This instructs the orchestrator what to do next. The actual routing
    logic is delegated to AdaptiveRouter — EvaluationService just invokes it.
    """

    decision: str  # NEXT_TOPIC | REVIEW_TOPIC | REPEAT_TOPIC | REVISIT_PREREQUISITE | READY_FOR_QUIZ
    current_topic_id: str | None = None
    next_topic_id: str | None = None
    reason: str = ""
    weak_concepts: list[str] = field(default_factory=list)


# ── Evaluation prompt templates ─────────────────────────────────────────────


EVALUATION_SYSTEM_PROMPT = """You are an expert tutor analyzing quiz answers.

Analyze the student's answers and provide:
1. Which concepts they struggled with (weak areas)
2. Which concepts they demonstrated understanding of (strong areas)
3. Brief, encouraging feedback that identifies specific areas for improvement

Keep feedback concise (2-3 sentences) and constructive.
Focus on patterns in wrong answers, not individual mistakes.
"""


def _build_evaluation_prompt(
    topic_name: str,
    submissions: list[dict],
) -> str:
    """Build a structured evaluation prompt."""
    parts = [f"Evaluate the student's performance on topic: {topic_name}"]
    parts.append("\nStudent's answers:")
    for i, sub in enumerate(submissions, 1):
        parts.append(
            f"  {i}. Q: {sub.get('question', '')}"
            f"\n     Student answered: {sub.get('selected_answer', '')}"
            f"\n     Correct answer: {sub.get('correct_answer', '')}"
            f"\n     {('✓ Correct' if sub.get('is_correct') else '✗ Incorrect')}"
            f"\n     Concept tag: {sub.get('concept_tag', 'general')}"
        )

    parts.append("\nIdentify weak concept tags and strong concept tags from the answers.")
    return "\n\n".join(parts)


# ── EvaluationService ───────────────────────────────────────────────────────


class EvaluationService:
    """Evaluates quiz answers, computes scores, and produces routing decisions.

    EvaluationService delegates to:
    1. Deterministic scoring (correct/total)
    2. AdaptiveRouter for the routing decision
    """

    def __init__(
        self,
        provider: BaseProvider | None = None,
    ):
        self._provider = provider

    def _get_provider(self) -> BaseProvider:
        if self._provider is not None:
            return self._provider
        factory = ProviderFactory.from_settings()
        self._provider = factory.get_provider()
        return self._provider

    async def evaluate(
        self,
        topic_name: str,
        questions: list[dict],
    ) -> EvaluationResult:
        """Evaluate a set of question submissions.

        Args:
            topic_name: The topic being evaluated.
            questions: List of question submission dicts with keys:
                question_id, question, selected_answer, correct_answer,
                is_correct, concept_tag, time_taken_seconds.

        Returns:
            An ``EvaluationResult`` with score and analysis.
        """
        # 1. Deterministic scoring
        submissions: list[AnswerSubmission] = []
        correct_count = 0
        incorrect_count = 0

        for q in questions:
            is_correct = q.get("is_correct", False)
            sub = AnswerSubmission(
                question_id=q.get("question_id", ""),
                selected_answer=q.get("selected_answer", ""),
                correct_answer=q.get("correct_answer", ""),
                is_correct=is_correct,
                time_taken_seconds=q.get("time_taken_seconds", 30),
            )
            submissions.append(sub)
            if is_correct:
                correct_count += 1
            else:
                incorrect_count += 1

        total = len(questions)
        score = correct_count / total if total > 0 else 0.0

        # 2. Identify weak/strong concept tags
        weak_tags: set[str] = set()
        strong_tags: set[str] = set()
        for q in questions:
            tag = q.get("concept_tag", "general")
            if q.get("is_correct", False):
                strong_tags.add(tag)
            else:
                weak_tags.add(tag)

        # Tags that appear in both are neutral — remove from weak
        weak_tags -= strong_tags

        # 3. Generate LLM feedback (optional — service works without it)
        feedback = ""
        try:
            provider = self._get_provider()
            eval_prompt = _build_evaluation_prompt(topic_name, questions)
            response = await provider.generate(
                eval_prompt,
                system_prompt=EVALUATION_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=300,
            )
            feedback = response.content.strip()
        except ProviderError:
            feedback = self._build_fallback_feedback(score, correct_count, total)

        return EvaluationResult(
            score=round(score, 4),
            total_questions=total,
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            submissions=submissions,
            weak_concept_tags=sorted(weak_tags),
            strong_concept_tags=sorted(strong_tags),
            feedback=feedback,
        )

    def produce_routing_instruction(
        self,
        result: EvaluationResult,
        current_topic_id: str,
        adaptive_router_result: Any,
    ) -> RoutingInstruction:
        """Convert an AdaptiveRouter routing result into a RoutingInstruction.

        This bridges the deterministic AdaptiveRouter with the orchestration
        layer. No curriculum decisions are made here — they belong to the
        AdaptiveRouter.

        Args:
            result: The evaluation result.
            current_topic_id: The current topic's ID.
            adaptive_router_result: The result from AdaptiveRouter.route()
                containing decision, next_topic_id, reason, etc.

        Returns:
            A ``RoutingInstruction`` for the orchestrator.
        """
        next_id = None
        if hasattr(adaptive_router_result, "next_topic_id"):
            next_id = str(adaptive_router_result.next_topic_id) if adaptive_router_result.next_topic_id else None

        decision_str = adaptive_router_result.decision.value if hasattr(adaptive_router_result.decision, "value") else str(adaptive_router_result.decision)
        reason_str = adaptive_router_result.reason if hasattr(adaptive_router_result, "reason") else ""

        return RoutingInstruction(
            decision=decision_str,
            current_topic_id=current_topic_id,
            next_topic_id=next_id,
            reason=reason_str,
            weak_concepts=result.weak_concept_tags,
        )

    def _build_fallback_feedback(
        self,
        score: float,
        correct: int,
        total: int,
    ) -> str:
        """Build deterministic feedback when LLM feedback fails."""
        if score >= 0.8:
            return f"Great work! You answered {correct}/{total} correctly. You have a strong grasp of this topic."
        elif score >= 0.6:
            return (
                f"Good effort! You answered {correct}/{total} correctly. "
                f"Review the concepts you missed and try again when ready."
            )
        elif score >= 0.4:
            return (
                f"You answered {correct}/{total} correctly. "
                f"Focus on the areas you missed — consider reviewing the topic again."
            )
        else:
            return (
                f"You answered {correct}/{total} correctly. "
                f"This topic needs more work. Consider reviewing the prerequisites first."
            )
