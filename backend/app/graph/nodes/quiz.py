"""Graph node: quiz generation.

Wraps the existing QuizService as a LangGraph node.

Input: state.current_topic_name, etc.
Output: state.quiz (dict-serialized Quiz)
"""

from __future__ import annotations

import logging

from app.graph.state import AAAState
from app.llm.quiz_service import QuizService

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


async def generate_quiz_node(state: AAAState) -> AAAState:
    """Generate a multiple-choice quiz for the current topic."""
    _log_state("quiz", "enter", state)

    topic_name = state.get("current_topic_name", "")
    topic_description = state.get("current_topic_description", "")
    topic_difficulty = state.get("current_topic_difficulty", "beginner")
    mastery_score = state.get("mastery_scores", {}).get(
        state.get("current_topic_id", ""), 0.0
    )

    if not topic_name:
        state["error"] = "No topic name for quiz generation"
        state["phase"] = "complete"
        _log_state("quiz", "exit(no_topic)", state)
        return state

    try:
        quiz_service = QuizService()
        quiz = await quiz_service.generate_quiz(
            topic_name=topic_name,
            topic_description=topic_description,
            topic_difficulty=topic_difficulty,
            mastery_score=mastery_score,
        )
        quiz.topic_id = state.get("current_topic_id", "")

        state["quiz"] = {
            "topic_id": quiz.topic_id,
            "topic_name": quiz.topic_name,
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "options": q.options,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "difficulty": q.difficulty,
                    "concept_tag": q.concept_tag,
                    "bloom_level": q.bloom_level,
                    "estimated_time_seconds": q.estimated_time_seconds,
                }
                for q in quiz.questions
            ],
            "total_questions": quiz.total_questions,
            "difficulty_breakdown": quiz.difficulty_breakdown,
        }
        state["phase"] = "evaluate"
        logger.info(
            "Quiz generated for '%s': %d questions",
            topic_name,
            quiz.total_questions,
        )
        _log_state("quiz", "exit(success)", state)

    except Exception as exc:
        state["error"] = f"Quiz generation failed: {exc}"
        state["phase"] = "complete"
        logger.error("Quiz generation error for '%s': %s", topic_name, exc)
        _log_state("quiz", "exit(error)", state)

    return state
