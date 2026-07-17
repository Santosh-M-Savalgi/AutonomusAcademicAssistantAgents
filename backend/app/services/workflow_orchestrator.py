"""Workflow Orchestrator — lightweight orchestration layer (Sprint 3 Phase E, Sprint 4 Phase G).

This module provides the study workflow that connects:
  AdaptiveRouter → RetrievalService → ContextBuilder → TutorService →
  QuizService → EvaluationService → AdaptiveRouter

RetrievalService and ContextBuilder (Sprint 4) sit between AdaptiveRouter
and TutorService/QuizService to provide high-quality context to the LLM.

The orchestrator is stateless and modular. Each step is independently
testable. No business logic lives in API routes — this is where the flow
lives.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.llm.evaluation_service import EvaluationResult, EvaluationService, RoutingInstruction
from app.llm.providers.base import BaseProvider, ProviderError
from app.llm.quiz_service import Quiz, QuizService
from app.llm.tutor_service import Lesson, TutorService
from app.services.adaptive_routing import AdaptiveRouter, RoutingResult
from app.services.context_builder import ContextBuilder, TutorContext, QuizContext
from app.services.retrieval_service import RetrievalResult, RetrievalService
from app.services.knowledge_graph_service import KnowledgeGraph
from app.services.mastery_service import MasteryEngine


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class StudyContext:
    """Context for a study session.

    This carries the state needed for the orchestrator to execute
    a complete study workflow.
    """

    topic_id: str
    topic_name: str
    topic_description: str
    topic_difficulty: str = "beginner"
    learning_mode: str = "journey"
    mastery_score: float = 0.0
    # Sprint 4: retrieval enrichment
    retrieval_enabled: bool = False
    retrieval_result: RetrievalResult | None = None
    tutor_context: TutorContext | None = None
    quiz_context: QuizContext | None = None
    learning_objectives: list[str] | None = None
    attempts_on_current: int = 0
    student_preferences: dict | None = None
    prerequisite_topics: list[dict] | None = None
    prerequisite_context: str = ""
    user_id: str = ""
    session_id: str = ""


@dataclass
class StudySessionResult:
    """Complete result of one study session execution."""

    lesson: Lesson | None = None
    quiz: Quiz | None = None
    evaluation: EvaluationResult | None = None
    routing: RoutingInstruction | None = None
    phase_completed: str = ""  # lesson | quiz | evaluation | complete
    error: str | None = None


# ── Workflow Orchestrator ───────────────────────────────────────────────────


class WorkflowOrchestrator:
    """Lightweight orchestrator for the study workflow.

    The orchestrator connects the services in the right order but
    contains no business logic of its own. Each service is independently
    testable.

    Flow:
        1. TutorService generates a lesson
        2. QuizService generates a quiz
        3. EvaluationService evaluates answers and invokes AdaptiveRouter
        4. Returns routing instruction

    Callers can stop after any phase (e.g., just get a lesson, or get
    a lesson + quiz without evaluating).
    """

    def __init__(
        self,
        tutor_service: TutorService | None = None,
        quiz_service: QuizService | None = None,
        evaluation_service: EvaluationService | None = None,
        retrieval_service: RetrievalService | None = None,
        context_builder: ContextBuilder | None = None,
        adaptive_router: AdaptiveRouter | None = None,
        mastery_engine: MasteryEngine | None = None,
    ):
        self.tutor = tutor_service or TutorService()
        self.quiz_service = quiz_service or QuizService()
        self.evaluator = evaluation_service or EvaluationService()
        self.retrieval = retrieval_service
        self.context_builder = context_builder or ContextBuilder()
        self.adaptive_router = adaptive_router or AdaptiveRouter()
        self.mastery_engine = mastery_engine or MasteryEngine()

    async def _enrich_with_retrieval(self, ctx: StudyContext) -> StudyContext:
        """If retrieval is enabled, perform retrieval and context building."""
        if not ctx.retrieval_enabled or self.retrieval is None:
            return ctx

        retrieval_result = await self.retrieval.search_with_prerequisites(
            topic_name=ctx.topic_name,
            topic_description=ctx.topic_description,
            prerequisite_topics=ctx.prerequisite_topics or [],
        )
        ctx.retrieval_result = retrieval_result

        # Build tutor context
        ctx.tutor_context = self.context_builder.build_tutor_context(
            topic_name=ctx.topic_name,
            topic_description=ctx.topic_description,
            retrieval_result=retrieval_result,
            mastery_score=ctx.mastery_score,
            learning_objectives=ctx.learning_objectives,
        )

        # Build quiz context
        ctx.quiz_context = self.context_builder.build_quiz_context(
            topic_name=ctx.topic_name,
            topic_description=ctx.topic_description,
            retrieval_result=retrieval_result,
            prerequisite_topics=ctx.prerequisite_topics,
            mastery_score=ctx.mastery_score,
        )
        return ctx

    async def generate_lesson(self, ctx: StudyContext) -> StudySessionResult:
        """Phase 1: Generate a lesson for the current topic.

        Returns the lesson result. Does NOT proceed to quiz generation.
        """
        try:
            # Enrich with retrieval if enabled
            if ctx.retrieval_enabled:
                ctx = await self._enrich_with_retrieval(ctx)

            # Pass retrieval-enriched context to tutor
            context_from_retrieval = ""
            if ctx.tutor_context:
                context_from_retrieval = self.context_builder.format_tutor_context_for_prompt(
                    ctx.tutor_context
                )

            # Use retrieval-enriched context as prerequisite context if available
            prereq_ctx = ctx.prerequisite_context
            if context_from_retrieval:
                prereq_ctx = context_from_retrieval

            lesson = await self.tutor.generate_lesson(
                topic_name=ctx.topic_name,
                topic_description=ctx.topic_description,
                topic_difficulty=ctx.topic_difficulty,
                learning_mode=ctx.learning_mode,
                prerequisite_context=prereq_ctx,
                mastery_score=ctx.mastery_score,
                student_preferences=ctx.student_preferences,
            )
            lesson.topic_id = ctx.topic_id
            return StudySessionResult(lesson=lesson, phase_completed="lesson")
        except ProviderError as exc:
            error_msg = f"Lesson generation failed: {exc}"
            return StudySessionResult(error=error_msg, phase_completed="error")

    async def generate_quiz(self, ctx: StudyContext) -> StudySessionResult:
        """Phase 2: Generate a quiz for the current topic.

        Returns lesson + quiz. Does NOT proceed to evaluation.
        """
        try:
            # Generate lesson first (needed for quiz context)
            lesson_result = await self.generate_lesson(ctx)
            if lesson_result.error:
                return lesson_result

            quiz = await self.quiz_service.generate_quiz(
                topic_name=ctx.topic_name,
                topic_description=ctx.topic_description,
                topic_difficulty=ctx.topic_difficulty,
                mastery_score=ctx.mastery_score,
                num_questions=5,
                prerequisite_topics=ctx.prerequisite_topics,
            )
            quiz.topic_id = ctx.topic_id

            return StudySessionResult(
                lesson=lesson_result.lesson,
                quiz=quiz,
                phase_completed="quiz",
            )
        except ProviderError as exc:
            error_msg = f"Quiz generation failed: {exc}"
            return StudySessionResult(error=error_msg, phase_completed="error")

    async def run_full_study(
        self,
        ctx: StudyContext,
        quiz_answers: list[dict] | None = None,
    ) -> StudySessionResult:
        """Run the complete study workflow.

        Flow:
            1. Generate lesson
            2. Generate quiz
            3. If quiz_answers provided, evaluate them and route

        Args:
            ctx: The study context with topic info.
            quiz_answers: Optional list of answer dicts for evaluation.
                If None, returns lesson + quiz without evaluation.

        Returns:
            A ``StudySessionResult`` with whichever phases completed.
        """
        # 1. Generate lesson
        lesson_result = await self.generate_lesson(ctx)
        if lesson_result.error:
            return lesson_result

        # 2. Generate quiz
        quiz = await self.quiz_service.generate_quiz(
            topic_name=ctx.topic_name,
            topic_description=ctx.topic_description,
            topic_difficulty=ctx.topic_difficulty,
            mastery_score=ctx.mastery_score,
            num_questions=5,
            prerequisite_topics=ctx.prerequisite_topics,
        )
        quiz.topic_id = ctx.topic_id

        # 3. If no answers provided, return lesson + quiz
        if not quiz_answers:
            return StudySessionResult(
                lesson=lesson_result.lesson,
                quiz=quiz,
                phase_completed="quiz",
            )

        # 4. Evaluate answers
        try:
            evaluation = await self.evaluator.evaluate(
                topic_name=ctx.topic_name,
                questions=quiz_answers,
            )
        except ProviderError as exc:
            return StudySessionResult(
                lesson=lesson_result.lesson,
                quiz=quiz,
                error=f"Evaluation failed: {exc}",
                phase_completed="error",
            )

        # 5. Produce routing instruction
        routing = self._compute_routing(ctx, evaluation)

        return StudySessionResult(
            lesson=lesson_result.lesson,
            quiz=quiz,
            evaluation=evaluation,
            routing=routing,
            phase_completed="complete",
        )

    def _compute_routing(
        self,
        ctx: StudyContext,
        evaluation: EvaluationResult,
    ) -> RoutingInstruction:
        """Invoke AdaptiveRouter and produce a routing instruction.

        This bridges the EvaluationService with the deterministic
        AdaptiveRouter from Sprint 2.
        """
        # Build minimal KnowledgeGraph and mastery scores for the AdaptiveRouter
        # In a full integration, these would come from the Sprint 1/2 persistence layer
        kg = self._build_minimal_graph(ctx)
        mastery_scores = {_to_uuid(ctx.topic_id): evaluation.score}
        if ctx.prerequisite_topics:
            for p in ctx.prerequisite_topics:
                pid = p.get("id", "")
                if pid:
                    mastery_scores[_to_uuid(pid)] = p.get("mastery", 0.5)

        syllabus_ids = [_to_uuid(ctx.topic_id)]

        try:
            adapter_result: RoutingResult = self.adaptive_router.route(
                graph=kg,
                mastery_scores=mastery_scores,
                current_topic_id=_to_uuid(ctx.topic_id),
                syllabus_topic_ids=syllabus_ids,
                quiz_score=evaluation.score,
                attempts_on_current=ctx.attempts_on_current,
            )
        except Exception as exc:
            return RoutingInstruction(
                decision="REVIEW_TOPIC",
                current_topic_id=ctx.topic_id,
                reason=f"Routing failed: {exc}",
            )

        # Convert to RoutingInstruction
        next_id = str(adapter_result.next_topic_id) if adapter_result.next_topic_id else None

        return RoutingInstruction(
            decision=adapter_result.decision.value,
            current_topic_id=ctx.topic_id,
            next_topic_id=next_id,
            reason=adapter_result.reason,
            weak_concepts=evaluation.weak_concept_tags,
        )

    def _build_minimal_graph(self, ctx: StudyContext) -> KnowledgeGraph:
        """Build a minimal KnowledgeGraph for the AdaptiveRouter.

        In production, this would be built from the Sprint 1/2 persistence layer
        via ``build_graph_from_models()``.
        """
        from app.services.knowledge_graph_service import (
            KnowledgeGraph,
            TopicEdgeData,
            TopicNode,
        )

        kg = KnowledgeGraph()
        current_uuid = _to_uuid(ctx.topic_id)

        # Add current topic
        kg.nodes[current_uuid] = TopicNode(
            id=current_uuid,
            name=ctx.topic_name,
            slug=ctx.topic_name.lower().replace(" ", "-"),
            difficulty=ctx.topic_difficulty,
            learning_depth=15,
        )

        # Add prerequisite topics
        if ctx.prerequisite_topics:
            for p in ctx.prerequisite_topics:
                p_id = _to_uuid(p.get("id", ""))
                if p_id and p_id not in kg.nodes:
                    kg.nodes[p_id] = TopicNode(
                        id=p_id,
                        name=p.get("name", "Prerequisite"),
                        slug=p.get("name", "prerequisite").lower().replace(" ", "-"),
                        difficulty=p.get("difficulty", "beginner"),
                        learning_depth=15,
                    )
                if p_id:
                    # Edge: current depends on prereq
                    edge_id = uuid.uuid4()
                    edge = TopicEdgeData(
                        id=edge_id,
                        parent_id=current_uuid,
                        child_id=p_id,
                        relationship_type="direct_prerequisite",
                        weight=1.0,
                    )
                    kg.edges.append(edge)
                    if current_uuid not in kg.outgoing:
                        kg.outgoing[current_uuid] = []
                    kg.outgoing[current_uuid].append(edge)
                    if p_id not in kg.incoming:
                        kg.incoming[p_id] = []
                    kg.incoming[p_id].append(edge)
                    kg._adj.setdefault(current_uuid, []).append(p_id)
                    kg._radj.setdefault(p_id, []).append(current_uuid)

        return kg


def _to_uuid(value: str | uuid.UUID | None) -> uuid.UUID:
    """Convert a string to UUID, or return as-is if already UUID."""
    if value is None:
        return uuid.uuid4()
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return uuid.uuid4()
