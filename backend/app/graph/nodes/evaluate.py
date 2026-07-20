"""Graph node: evaluation.

Wraps the existing EvaluationService + AdaptiveRouter as a LangGraph node.

Input: state.quiz (with correct answers), state.answers (student's answers)
Output: state.evaluation, state.routing_decision, state.routing_reason,
        state.next_topic_id

When no answers are provided (lesson flow), the node checkpoints
without evaluating — the quiz is ready and waiting for student input.
"""

from __future__ import annotations

import logging
import uuid

from app.graph.state import AAAState
from app.llm.evaluation_service import EvaluationService
from app.services.adaptive_routing import AdaptiveRouter
from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    TopicEdgeData,
    TopicNode,
)

logger = logging.getLogger(__name__)


def _log_state(node: str, event: str, state: AAAState) -> None:
    """Log key state fields for tracing state flow through the graph."""
    logger.info(
        "STATE %s/%s: learning_goal=%r syllabus_id=%r topics=%d phase=%r error=%r",
        node, event,
        state.get("learning_goal", "")[:80],
        state.get("syllabus_id", "")[:36],
        len(state.get("topics", [])),
        state.get("phase"),
        state.get("error"),
    )


async def evaluate_quiz_node(state: AAAState) -> AAAState:
    """Evaluate quiz answers and compute routing decision.

    If no answers are present in the state, this node passes through
    — the quiz has been generated but the student hasn't submitted
    answers yet. The graph checkpoints here, and the evaluate endpoint
    resumes from this point with answers.
    """
    _log_state("evaluate", "enter", state)

    topic_name = state.get("current_topic_name", "")
    topic_id = state.get("current_topic_id", "")

    # Gather answers from state
    answers = state.get("answers", [])

    # ── Pass through: no answers yet (lesson generation flow) ───────────
    if not answers:
        state["phase"] = "quiz"  # stay at quiz — waiting for student input
        state["phase_completed"] = "quiz"
        logger.info("Evaluate: no answers yet — checkpointing at quiz phase")
        _log_state("evaluate", "exit(no_answers)", state)
        return state

    # ── Enrich answers with correct_answer from the stored quiz ──────────
    # The frontend sends only {question_id, selected_answer} because
    # /quiz/generate deliberately hides correct_answer from the student.
    # We must look up the correct answers from the quiz checkpoint and
    # compute is_correct before passing to EvaluationService.
    quiz_questions = state.get("quiz", {}).get("questions", [])
    logger.info(
        "EVAL-DIAG: answers_count=%d quiz_questions_count=%d state_keys=%s quiz_keys=%s",
        len(answers),
        len(quiz_questions),
        sorted(state.keys()),
        sorted(state.get("quiz", {}).keys()) if isinstance(state.get("quiz"), dict) else "NOT_DICT",
    )
    if quiz_questions:
        first_q = quiz_questions[0]
        logger.info(
            "EVAL-DIAG: first_quiz_q id=%s correct_answer=%r options=%d",
            first_q.get("id"), first_q.get("correct_answer"),
            len(first_q.get("options", [])),
        )
    if answers:
        first_a = answers[0]
        logger.info(
            "EVAL-DIAG: first_answer id=%s selected=%r",
            first_a.get("question_id", first_a.get("questionId")),
            first_a.get("selected_answer", first_a.get("selectedAnswer")),
        )
    correct_map: dict[str, dict[str, str]] = {}
    for q in quiz_questions:
        qid = q.get("id", "")
        if qid:
            correct_map[qid] = {
                "correct_answer": q.get("correct_answer", ""),
                "concept_tag": q.get("concept_tag", "general"),
                "question": q.get("question", ""),
            }

    enriched_answers: list[dict] = []
    for a in answers:
        qid = a.get("question_id", a.get("questionId", ""))
        stored = correct_map.get(qid, {})
        selected = a.get("selected_answer", a.get("selectedAnswer", ""))
        correct = stored.get("correct_answer", "")
        is_correct = selected.strip().lower() == correct.strip().lower()
        enriched_answers.append({
            "question_id": qid,
            "question": stored.get("question", a.get("question", "")),
            "selected_answer": selected,
            "correct_answer": correct,
            "is_correct": is_correct,
            "concept_tag": stored.get("concept_tag", "general"),
            "time_taken_seconds": a.get("time_taken_seconds", 30),
        })

    # ── Normal path: evaluate answers ────────────────────────────────────
    try:
        evaluator = EvaluationService()
        evaluation = await evaluator.evaluate(
            topic_name=topic_name,
            questions=enriched_answers,
        )

        state["evaluation"] = {
            "score": evaluation.score,
            "total_questions": evaluation.total_questions,
            "correct_count": evaluation.correct_count,
            "incorrect_count": evaluation.incorrect_count,
            "weak_concept_tags": evaluation.weak_concept_tags,
            "strong_concept_tags": evaluation.strong_concept_tags,
            "feedback": evaluation.feedback,
        }

        # Update mastery score
        mastery = state.get("mastery_scores", {})
        mastery[topic_id] = evaluation.score
        state["mastery_scores"] = mastery

        # Build minimal KG for routing
        kg = _build_graph_from_state(state)
        router = AdaptiveRouter()
        syllabus_topic_ids = [t["id"] for t in state.get("topics", [])]
        topic_uuid = _to_uuid(topic_id)
        syllabus_uuids = [_to_uuid(t) for t in syllabus_topic_ids]

        result = router.route(
            graph=kg,
            mastery_scores={_to_uuid(k): v for k, v in mastery.items()},
            current_topic_id=topic_uuid,
            syllabus_topic_ids=syllabus_uuids,
            quiz_score=evaluation.score,
            attempts_on_current=state.get("attempts_on_current", 0),
        )

        state["routing_decision"] = result.decision.value
        state["routing_reason"] = result.reason
        state["next_topic_id"] = str(result.next_topic_id) if result.next_topic_id else None
        state["phase"] = "route"
        state["phase_completed"] = "route"

        logger.info(
            "Evaluation for '%s': score=%.2f decision=%s",
            topic_name,
            evaluation.score,
            result.decision.value,
        )
        _log_state("evaluate", "exit(evaluated)", state)

    except Exception as exc:
        state["error"] = f"Evaluation failed: {exc}"
        state["phase"] = "complete"
        logger.error("Evaluation error for '%s': %s", topic_name, exc)
        _log_state("evaluate", "exit(error)", state)

    return state


def _to_uuid(value: str | uuid.UUID | None) -> uuid.UUID:
    if value is None:
        return uuid.uuid4()
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return uuid.uuid4()


def _build_graph_from_state(state: AAAState) -> KnowledgeGraph:
    """Build a minimal KnowledgeGraph from state topics for routing."""
    kg = KnowledgeGraph()
    topics = state.get("topics", [])

    for t in topics:
        tid = _to_uuid(t["id"])
        kg.add_node(TopicNode(
            id=tid,
            name=t["name"],
            slug=t.get("slug", t["name"].lower().replace(" ", "-")),
            difficulty=t.get("difficulty", "beginner"),
            learning_depth=15,
        ))

    for t in topics:
        parent_id = _to_uuid(t["id"])
        for prereq_slug in t.get("prerequisites", []):
            for p in topics:
                if p.get("slug") == prereq_slug:
                    child_id = _to_uuid(p["id"])
                    edge = TopicEdgeData(
                        id=uuid.uuid4(),
                        parent_id=parent_id,
                        child_id=child_id,
                        relationship_type="direct_prerequisite",
                        weight=1.0,
                    )
                    kg.add_edge(edge)
                    break

    return kg
