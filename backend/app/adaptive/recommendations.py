"""Adaptive Recommendation Engine — explainable, prioritized recommendations.

Extends Sprint 7 recommendations with adaptive context including
mastery state, diagnosis results, and learning progress.

Every recommendation includes a structured explanation of WHY it was selected.

Reference: Sprint 8 Part 8.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.adaptive.models import (
    DiagnosisReport,
    Explanation,
    MasteryEvaluation,
    MasteryState,
    Recommendation,
    RecommendationType,
)
from app.db.models import ConceptMastery
from app.services.knowledge_graph_service import KnowledgeGraph


class AdaptiveRecommender:
    """Generate prioritized, explainable adaptive recommendations.

    Recommendations are ordered by priority (lowest number = highest priority)
    and always include a structured explanation.

    Usage::

        recommender = AdaptiveRecommender()
        recs = recommender.recommend(
            user_id=user_id,
            graph=kg,
            current_topic_id=topic_id,
            mastery_map={...},
        )
    """

    # Priority constants
    PRIORITY_CRITICAL: int = 0      # Must do immediately
    PRIORITY_HIGH: int = 10         # Should do soon
    PRIORITY_MEDIUM: int = 20       # Recommended
    PRIORITY_LOW: int = 30          # Optional / future

    def recommend(
        self,
        user_id: uuid.UUID,
        graph: KnowledgeGraph,
        current_topic_id: uuid.UUID | None,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
        diagnosis: DiagnosisReport | None = None,
        syllabus_topic_ids: list[uuid.UUID] | None = None,
    ) -> list[Recommendation]:
        """Generate a list of personalized recommendations.

        Args:
            user_id: The learner's user ID.
            graph: The KnowledgeGraph.
            current_topic_id: The learner's current topic.
            mastery_map: Mastery evaluations keyed by topic_id.
            diagnosis: Optional diagnosis report for context.
            syllabus_topic_ids: Optional syllabus topic IDs for context.

        Returns:
            A list of ``Recommendation`` objects sorted by priority.
        """
        recommendations: list[Recommendation] = []

        if current_topic_id is not None:
            current_eval = mastery_map.get(current_topic_id)
            if current_eval is not None:
                recommendations.extend(
                    self._recommend_for_current_topic(
                        current_topic_id=current_topic_id,
                        evaluation=current_eval,
                        diagnosis=diagnosis,
                        graph=graph,
                        mastery_map=mastery_map,
                    )
                )

        # Add prerequisite-related recommendations
        if current_topic_id is not None:
            recommendations.extend(
                self._recommend_prerequisites(
                    topic_id=current_topic_id,
                    graph=graph,
                    mastery_map=mastery_map,
                )
            )

        # Add review/revision schedule recommendations
        recommendations.extend(
            self._recommend_revisions(
                graph=graph,
                mastery_map=mastery_map,
            )
        )

        # Sort by priority
        recommendations.sort(key=lambda r: r.priority)
        return recommendations

    def get_next_lesson(
        self,
        graph: KnowledgeGraph,
        syllabus_topic_ids: list[uuid.UUID],
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
    ) -> Recommendation | None:
        """Recommend the immediate next lesson to take.

        Args:
            graph: KnowledgeGraph.
            syllabus_topic_ids: All topic IDs in the syllabus.
            mastery_map: Mastery evaluations.

        Returns:
            A recommendation for the next lesson, or None if all complete.
        """
        topo = graph.topological_sort()
        for tid in topo:
            if tid not in syllabus_topic_ids:
                continue

            meval = mastery_map.get(tid)
            if meval is None or meval.mastery_state != MasteryState.MASTERED:
                node = graph.nodes.get(tid)
                name = node.name if node else f"topic-{tid}"
                return Recommendation(
                    type=RecommendationType.NEXT_LESSON,
                    topic_id=tid,
                    topic_name=name,
                    priority=self.PRIORITY_HIGH,
                    reason=f"'{name}' is the next unmastered topic in your learning path.",
                    explanation=Explanation(
                        decision="next_lesson",
                        reason=f"'{name}' is the next unmastered topic.",
                        evidence=[
                            f"Topic '{name}' state: {meval.mastery_state.value if meval else 'not_started'}",
                            f"Topic is in topological order.",
                        ],
                        confidence=0.95,
                        rules_triggered=["next_lesson_recommender"],
                    ),
                )
        return None

    # ── private helpers ─────────────────────────────────────────────────────

    def _recommend_for_current_topic(
        self,
        current_topic_id: uuid.UUID,
        evaluation: MasteryEvaluation,
        diagnosis: DiagnosisReport | None,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
    ) -> list[Recommendation]:
        """Generate recommendations specific to the current topic."""
        recs: list[Recommendation] = []
        node = graph.nodes.get(current_topic_id)
        topic_name = node.name if node else f"topic-{current_topic_id}"

        state = evaluation.mastery_state

        if state == MasteryState.NOT_STARTED:
            recs.append(Recommendation(
                type=RecommendationType.NEXT_LESSON,
                topic_id=current_topic_id,
                topic_name=topic_name,
                priority=self.PRIORITY_HIGH,
                reason=f"Start learning '{topic_name}' — you haven't begun this topic yet.",
                explanation=Explanation(
                    decision="start_topic",
                    reason="Topic not started.",
                    evidence=[f"State: {state.value}"],
                    confidence=1.0,
                    rules_triggered=["not_started_recommendation"],
                ),
            ))

        elif state == MasteryState.PRACTICING:
            recs.append(Recommendation(
                type=RecommendationType.PRACTICE_SESSION,
                topic_id=current_topic_id,
                topic_name=topic_name,
                priority=self.PRIORITY_HIGH,
                reason=f"Continue practicing '{topic_name}' — your score is {evaluation.score:.0%}.",
                explanation=Explanation(
                    decision="practice_session",
                    reason=f"Score {evaluation.score:.0%} below threshold.",
                    evidence=[
                        f"Score: {evaluation.score:.2f}",
                        f"Attempts: {evaluation.attempt_count}",
                        f"Repeated failures: {evaluation.repeated_failures}",
                    ],
                    metrics_used={"score": evaluation.score, "attempts": float(evaluation.attempt_count)},
                    confidence=evaluation.confidence,
                    rules_triggered=["practicing_recommendation"],
                ),
            ))
            if evaluation.repeated_failures >= 2:
                recs.append(Recommendation(
                    type=RecommendationType.QUIZ_RETRY,
                    topic_id=current_topic_id,
                    topic_name=topic_name,
                    priority=self.PRIORITY_CRITICAL,
                    reason=f"Retry the quiz for '{topic_name}' — you've had {evaluation.repeated_failures} consecutive low scores.",
                    explanation=Explanation(
                        decision="quiz_retry",
                        reason=f"Consecutive failures: {evaluation.repeated_failures}",
                        evidence=[
                            f"Repeated failures: {evaluation.repeated_failures}",
                            f"Score: {evaluation.score:.2f}",
                        ],
                        metrics_used={"repeated_failures": float(evaluation.repeated_failures)},
                        confidence=0.9,
                        rules_triggered=["repeated_failures_recommendation"],
                    ),
                ))

        elif state == MasteryState.REVIEW_REQUIRED:
            recs.append(Recommendation(
                type=RecommendationType.REVIEW_LESSON,
                topic_id=current_topic_id,
                topic_name=topic_name,
                priority=self.PRIORITY_MEDIUM,
                reason=f"Review '{topic_name}' — your mastery may have decayed.",
                explanation=Explanation(
                    decision="review_lesson",
                    reason="Review recommended due to time decay or score drop.",
                    evidence=[f"State: {state.value}", f"Score: {evaluation.score:.2f}"],
                    confidence=0.8,
                    rules_triggered=["review_required_recommendation"],
                ),
            ))

        elif state == MasteryState.REGRESSED:
            recs.append(Recommendation(
                type=RecommendationType.REMEDIATION,
                topic_id=current_topic_id,
                topic_name=topic_name,
                priority=self.PRIORITY_CRITICAL,
                reason=f"Remediation needed for '{topic_name}' — your mastery has regressed.",
                explanation=Explanation(
                    decision="remediation_recommendation",
                    reason="Topic has regressed — remediation required.",
                    evidence=[
                        f"State: {state.value}",
                        f"Score: {evaluation.score:.2f}",
                        f"Repeated failures: {evaluation.repeated_failures}",
                    ],
                    confidence=0.85,
                    rules_triggered=["regressed_recommendation"],
                ),
            ))

        elif state == MasteryState.MASTERED:
            # Recommend next topic
            if diagnosis is None:
                recs.append(Recommendation(
                    type=RecommendationType.NEXT_LESSON,
                    topic_id=current_topic_id,
                    topic_name=topic_name,
                    priority=self.PRIORITY_LOW,
                    reason=f"'{topic_name}' is mastered — move to the next topic.",
                    explanation=Explanation(
                        decision="advance",
                        reason="Topic mastered.",
                        evidence=[f"Score: {evaluation.score:.2f}"],
                        confidence=evaluation.confidence,
                        rules_triggered=["mastered_recommendation"],
                    ),
                ))

        return recs

    def _recommend_prerequisites(
        self,
        topic_id: uuid.UUID,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
    ) -> list[Recommendation]:
        """Recommend prerequisite topics that need attention."""
        recs: list[Recommendation] = []
        prereqs = graph.get_prerequisites(topic_id)

        for pid in prereqs:
            pnode = graph.nodes.get(pid)
            pname = pnode.name if pnode else f"topic-{pid}"
            peval = mastery_map.get(pid)

            if peval is None or peval.mastery_state != MasteryState.MASTERED:
                recs.append(Recommendation(
                    type=RecommendationType.PREREQUISITE_LESSON,
                    topic_id=pid,
                    topic_name=pname,
                    priority=self.PRIORITY_HIGH,
                    reason=f"Strengthen prerequisite '{pname}' before continuing.",
                    explanation=Explanation(
                        decision="prerequisite_lesson",
                        reason=f"Prerequisite '{pname}' is not mastered.",
                        evidence=[
                            f"Prerequisite state: {peval.mastery_state.value if peval else 'not_evaluated'}",
                            f"Prerequisite score: {peval.score:.2f}" if peval else "N/A",
                        ],
                        confidence=0.85,
                        rules_triggered=["prerequisite_gap_recommendation"],
                    ),
                ))

        return recs

    def _recommend_revisions(
        self,
        graph: KnowledgeGraph,
        mastery_map: dict[uuid.UUID, MasteryEvaluation],
    ) -> list[Recommendation]:
        """Recommend topics that should be reviewed (mastered but stale or at risk)."""
        recs: list[Recommendation] = []

        for tid, meval in mastery_map.items():
            node = graph.nodes.get(tid)
            tname = node.name if node else f"topic-{tid}"

            # Mastered topics that haven't been practiced recently
            if meval.mastery_state == MasteryState.MASTERED:
                if meval.time_since_last_study_hours > 336:  # 14 days
                    recs.append(Recommendation(
                        type=RecommendationType.REVISION_SCHEDULE,
                        topic_id=tid,
                        topic_name=tname,
                        priority=self.PRIORITY_LOW,
                        reason=f"Schedule a revision for '{tname}' — last practiced {meval.time_since_last_study_hours:.0f} hours ago.",
                        explanation=Explanation(
                            decision="revision_schedule",
                            reason=f"Last practiced {meval.time_since_last_study_hours:.0f} hours ago.",
                            evidence=[
                                f"Time since last study: {meval.time_since_last_study_hours:.0f} hours",
                                f"Score: {meval.score:.2f}",
                            ],
                            metrics_used={
                                "time_since_study": meval.time_since_last_study_hours,
                                "score": meval.score,
                            },
                            confidence=0.7,
                            rules_triggered=["revision_schedule_recommendation"],
                        ),
                    ))

        return recs
