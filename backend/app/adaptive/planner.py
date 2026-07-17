"""Adaptive Learning Path Planner & Remediation Planner.

Generates personalized learning plans, determines next topics,
recovery plans after failures, and remediation sequences.

All planning is deterministic. No LLM calls.

Reference: Sprint 8 Parts 5 & 7.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.adaptive.models import (
    DecisionType,
    Explanation,
    LearningPlan,
    MasteryEvaluation,
    MasteryState,
    PlanStep,
    Recommendation,
    RecommendationType,
    RemediationPlan,
)
from app.services.knowledge_graph_service import KnowledgeGraph
from app.services.learning_path_service import (
    LearningMode,
    LearningPathService,
    LearningPathStep,
)


# ── Adaptive Planner ───────────────────────────────────────────────────────


class AdaptivePlanner:
    """Generate personalized adaptive learning plans.

    Combines mastery evaluation results, Knowledge Graph structure,
    and learning mode to produce ordered, prioritized learning plans.

    Usage::

        planner = AdaptivePlanner()
        plan = planner.plan(
            user_id=user_id,
            graph=kg,
            syllabus_topic_ids=[...],
            mastery_map={topic_id: MasteryEvaluation, ...},
            current_topic_id=topic_id,
        )
    """

    # Estimated time per activity in minutes
    ESTIMATED_LESSON_MINUTES: int = 15
    ESTIMATED_QUIZ_MINUTES: int = 10
    ESTIMATED_REVIEW_MINUTES: int = 10
    ESTIMATED_DIAGNOSIS_MINUTES: int = 20

    def __init__(self) -> None:
        self._path_service = LearningPathService()

    def plan(
        self,
        user_id: uuid.UUID,
        graph: KnowledgeGraph,
        syllabus_topic_ids: list[uuid.UUID],
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        current_topic_id: uuid.UUID | None = None,
        mode: str = "standard",
    ) -> LearningPlan:
        """Generate a personalized adaptive learning plan.

        Args:
            user_id: The learner's user ID.
            graph: The KnowledgeGraph.
            syllabus_topic_ids: All topic IDs in the learner's syllabus.
            mastery_map: Mastery evaluations keyed by topic_id.
            current_topic_id: The learner's current topic (if any).
            mode: Learning mode (beginner | standard | fast_track).

        Returns:
            A ``LearningPlan`` with ordered, prioritized steps.
        """
        # Build raw mastery scores for the existing LearningPathService
        raw_scores: dict[uuid.UUID, float] = {}
        for tid, meval in mastery_map.items():
            raw_scores[tid] = meval.score

        # Map mode string to enum
        lm = LearningMode.STANDARD
        if mode == "beginner":
            lm = LearningMode.BEGINNER
        elif mode == "fast_track":
            lm = LearningMode.FAST_TRACK

        # Generate base path using existing service
        base_path = self._path_service.generate(
            graph=graph,
            syllabus_topic_ids=syllabus_topic_ids,
            mastery_scores=raw_scores,
            mode=lm,
        )

        # Convert base path steps to adaptive plan steps
        steps: list[PlanStep] = []
        completion_path: list[uuid.UUID] = []

        for i, path_step in enumerate(base_path.steps):
            mastery = mastery_map.get(path_step.topic_id)
            state = mastery.mastery_state if mastery else MasteryState.NOT_STARTED
            score = mastery.score if mastery else 0.0

            action, reason, est_minutes = self._determine_action(
                path_step=path_step,
                state=state,
                score=score,
                is_current=(path_step.topic_id == current_topic_id),
            )

            step = PlanStep(
                topic_id=path_step.topic_id,
                topic_name=path_step.topic_name,
                action=action,
                priority=i,
                estimated_minutes=est_minutes,
                reason=reason,
            )
            steps.append(step)

            if action != DecisionType.COMPLETE:
                completion_path.append(path_step.topic_id)

        total_minutes = sum(s.estimated_minutes for s in steps)

        return LearningPlan(
            user_id=user_id,
            steps=steps,
            total_estimated_minutes=total_minutes,
            completion_path=completion_path,
            explanation=Explanation(
                decision="plan",
                reason=f"Generated {len(steps)}-step plan in '{mode}' mode.",
                evidence=[
                    f"Total topics: {len(syllabus_topic_ids)}",
                    f"Completed: {base_path.completed_topics}",
                    f"Remaining: {base_path.remaining_topics}",
                    f"Estimated total: {total_minutes} minutes",
                ],
                metrics_used={
                    "total_topics": float(len(syllabus_topic_ids)),
                    "completed_topics": float(base_path.completed_topics),
                    "remaining_topics": float(base_path.remaining_topics),
                    "total_minutes": float(total_minutes),
                },
                confidence=0.9,
                rules_triggered=["adaptive_planner"],
            ),
        )

    def get_next_topic(
        self,
        graph: KnowledgeGraph,
        syllabus_topic_ids: list[uuid.UUID],
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        current_topic_id: uuid.UUID | None = None,
    ) -> uuid.UUID | None:
        """Determine the next topic a learner should study.

        Prioritizes:
        1. The first unmastered topic whose prerequisites are all mastered.
        2. If all are mastered, returns None (complete).

        Args:
            graph: KnowledgeGraph.
            syllabus_topic_ids: All syllabus topic IDs.
            mastery_map: Mastery evaluations keyed by topic_id.
            current_topic_id: Current topic (optional).

        Returns:
            The next topic ID, or None if complete.
        """
        if current_topic_id is not None:
            current_eval = mastery_map.get(current_topic_id)
            if current_eval and not self._is_complete(current_eval):
                # Check prerequisites of current topic
                prereqs = graph.get_prerequisites(current_topic_id)
                for pid in prereqs:
                    peval = mastery_map.get(pid)
                    if peval and not self._is_complete(peval):
                        return pid
                return current_topic_id

        # Find first incomplete topic with all prerequisites met
        topo_order = graph.topological_sort()
        for tid in topo_order:
            if tid not in syllabus_topic_ids:
                if tid not in graph.nodes:
                    continue
            meval = mastery_map.get(tid)
            if meval and self._is_complete(meval):
                continue

            # Check prerequisites
            prereqs = graph.get_prerequisites(tid)
            all_prereqs_met = all(
                mastery_map.get(pid) is not None and self._is_complete(mastery_map[pid])
                for pid in prereqs
                if pid in syllabus_topic_ids
            )
            if all_prereqs_met:
                return tid

        return None  # All complete

    def recovery_plan(
        self,
        user_id: uuid.UUID,
        failed_topic_id: uuid.UUID,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        diagnosis_report: Any | None = None,
    ) -> LearningPlan:
        """Generate a recovery plan after failures on a topic.

        Args:
            user_id: The learner's user ID.
            failed_topic_id: The topic the learner is failing.
            graph: KnowledgeGraph.
            mastery_map: Mastery evaluations.
            diagnosis_report: Optional diagnosis report from DiagnosisEngine.

        Returns:
            A ``LearningPlan`` for recovery.
        """
        steps: list[PlanStep] = []
        node = graph.nodes.get(failed_topic_id)
        topic_name = node.name if node else f"topic-{failed_topic_id}"

        # Step 1: Revisit any missing prerequisites (from diagnosis)
        if diagnosis_report is not None and diagnosis_report.missing_prerequisites:
            for pid in diagnosis_report.missing_prerequisites:
                pnode = graph.nodes.get(pid)
                pname = pnode.name if pnode else f"topic-{pid}"
                steps.append(PlanStep(
                    topic_id=pid,
                    topic_name=pname,
                    action=DecisionType.PREREQUISITE,
                    priority=len(steps),
                    estimated_minutes=self.ESTIMATED_LESSON_MINUTES,
                    reason="Missing prerequisite identified during diagnosis.",
                ))

        # Step 2: Re-teach the failed topic
        steps.append(PlanStep(
            topic_id=failed_topic_id,
            topic_name=topic_name,
            action=DecisionType.RETEACH,
            priority=len(steps),
            estimated_minutes=self.ESTIMATED_LESSON_MINUTES,
            reason="Topic requires re-teaching after repeated failures.",
        ))

        # Step 3: Practice/quiz on the topic
        steps.append(PlanStep(
            topic_id=failed_topic_id,
            topic_name=topic_name,
            action=DecisionType.PRACTICE,
            priority=len(steps),
            estimated_minutes=self.ESTIMATED_QUIZ_MINUTES,
            reason="Practice session to reinforce learning.",
        ))

        return LearningPlan(
            user_id=user_id,
            steps=steps,
            total_estimated_minutes=sum(s.estimated_minutes for s in steps),
            completion_path=[failed_topic_id],
            explanation=Explanation(
                decision="recovery",
                reason=f"Recovery plan for '{topic_name}' after repeated failures.",
                evidence=[
                    f"Failed topic: {topic_name}",
                    f"Missing prerequisites from diagnosis: "
                    f"{len(diagnosis_report.missing_prerequisites) if diagnosis_report else 0}",
                ],
                confidence=0.8,
                rules_triggered=["recovery_planner"],
            ),
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def _is_complete(self, meval: MasteryEvaluation) -> bool:
        """Check if a topic's mastery is complete."""
        return meval.mastery_state == MasteryState.MASTERED

    def _determine_action(
        self,
        path_step: LearningPathStep,
        state: MasteryState,
        score: float,
        is_current: bool,
    ) -> tuple[DecisionType, str, int]:
        """Determine the action for a specific path step.

        Args:
            path_step: The learning path step from the base service.
            state: Current mastery state.
            score: Current mastery score.
            is_current: Whether this is the current topic.

        Returns:
            Tuple of (DecisionType, reason, estimated_minutes).
        """
        if path_step.is_completed:
            return (
                DecisionType.COMPLETE,
                f"Topic '{path_step.topic_name}' is already mastered (score={score:.2f}).",
                0,
            )

        if state == MasteryState.NOT_STARTED:
            return (
                DecisionType.ADVANCE,
                f"Topic '{path_step.topic_name}' not yet started.",
                self.ESTIMATED_LESSON_MINUTES,
            )

        if state == MasteryState.LEARNING:
            return (
                DecisionType.ADVANCE,
                f"Topic '{path_step.topic_name}' in learning phase.",
                self.ESTIMATED_LESSON_MINUTES,
            )

        if state == MasteryState.PRACTICING:
            return (
                DecisionType.PRACTICE,
                f"Topic '{path_step.topic_name}' needs practice (score={score:.2f}).",
                self.ESTIMATED_QUIZ_MINUTES,
            )

        if state == MasteryState.REVIEW_REQUIRED:
            return (
                DecisionType.REVIEW,
                f"Topic '{path_step.topic_name}' requires review.",
                self.ESTIMATED_REVIEW_MINUTES,
            )

        if state == MasteryState.REGRESSED:
            return (
                DecisionType.REMEDIATE,
                f"Topic '{path_step.topic_name}' has regressed — remediation needed.",
                self.ESTIMATED_DIAGNOSIS_MINUTES,
            )

        # Default — practice
        return (
            DecisionType.PRACTICE,
            f"Topic '{path_step.topic_name}' — default practice.",
            self.ESTIMATED_QUIZ_MINUTES,
        )


# ── Remediation Planner ────────────────────────────────────────────────────


class RemediationPlanner:
    """Generate focused remediation plans for struggling learners.

    Produces plans that include weak concepts, practice recommendations,
    suggested review sequences, and target mastery goals.

    Reference: Sprint 8 Part 7.
    """

    DEFAULT_TARGET_MASTERY: float = 0.80
    DEFAULT_QUIZ_COUNT: int = 2
    ESTIMATED_MINUTES_PER_TOPIC: int = 15

    def plan(
        self,
        topic_id: uuid.UUID,
        topic_name: str,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        target_mastery: float | None = None,
    ) -> RemediationPlan:
        """Generate a remediation plan for a struggling learner.

        Args:
            topic_id: The topic the learner is struggling with.
            topic_name: Human-readable topic name.
            graph: KnowledgeGraph.
            mastery_map: Current mastery evaluations.
            target_mastery: Target mastery score (default: 0.80).

        Returns:
            A ``RemediationPlan`` with review sequence and recommendations.
        """
        if target_mastery is None:
            target_mastery = self.DEFAULT_TARGET_MASTERY

        current_eval = mastery_map.get(topic_id)
        current_score = current_eval.score if current_eval else 0.0

        # Identify weak concepts within this topic
        weak_concepts: list[str] = []
        if current_eval and current_eval.score < target_mastery:
            weak_concepts.append(
                f"Overall mastery for '{topic_name}' is {current_score:.0%} "
                f"(target: {target_mastery:.0%})"
            )

        # Check prerequisites
        prereqs = graph.get_prerequisites(topic_id)
        prereq_names: list[str] = []
        review_sequence: list[uuid.UUID] = []

        for pid in prereqs:
            pnode = graph.nodes.get(pid)
            pname = pnode.name if pnode else f"topic-{pid}"
            peval = mastery_map.get(pid)

            if peval is None or peval.score < target_mastery:
                pscore = peval.score if peval else 0.0
                weak_concepts.append(
                    f"Prerequisite '{pname}' is weak (score={pscore:.0%})"
                )
                prereq_names.append(pname)
                review_sequence.append(pid)

        # Build practice recommendations
        practice_recs: list[str] = []

        if review_sequence:
            practice_recs.append(
                f"Review the following prerequisites before retrying '{topic_name}': "
                f"{', '.join(prereq_names)}."
            )

        if current_score < 0.3:
            practice_recs.append(
                "Start with foundational concept videos or readings for this topic."
            )
        elif current_score < 0.6:
            practice_recs.append(
                "Focus on worked examples and practice problems for this topic."
            )
        else:
            practice_recs.append(
                "Take additional quizzes to reinforce weak areas."
            )

        practice_recs.append(
            "Use spaced repetition: review again after 1 day and 7 days."
        )

        # Estimate remediation time
        num_review_topics = len(review_sequence) + 1  # +1 for the failing topic itself
        est_minutes = num_review_topics * self.ESTIMATED_MINUTES_PER_TOPIC * self.DEFAULT_QUIZ_COUNT

        return RemediationPlan(
            topic_id=topic_id,
            topic_name=topic_name,
            weak_concepts=weak_concepts,
            practice_recommendations=practice_recs,
            suggested_review_sequence=review_sequence,
            estimated_remediation_minutes=est_minutes,
            required_quizzes=self.DEFAULT_QUIZ_COUNT,
            target_mastery=target_mastery,
            explanation=Explanation(
                decision="remediate",
                reason=f"Remediation plan for '{topic_name}' targeting {target_mastery:.0%} mastery.",
                evidence=[
                    f"Current score: {current_score:.0%}",
                    f"Target score: {target_mastery:.0%}",
                    f"Weak prerequisite topics: {len(review_sequence)}",
                ],
                metrics_used={
                    "current_score": current_score,
                    "target_mastery": target_mastery,
                    "weak_prerequisites": float(len(review_sequence)),
                    "estimated_minutes": float(est_minutes),
                },
                confidence=0.85,
                rules_triggered=["remediation_planner"],
            ),
        )
