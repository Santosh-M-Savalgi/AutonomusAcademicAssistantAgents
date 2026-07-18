"""Graph node: tutor / lesson generation.

Wraps the existing TutorService as a LangGraph node.

Input: state.current_topic_name, state.current_topic_description,
       state.current_topic_difficulty, state.mastery_scores,
       state.retrieval_context, state.learning_mode
Output: state.lesson (dict-serialized Lesson)
"""

from __future__ import annotations

import logging

from app.graph.state import AAAState
from app.llm.tutor_service import TutorService

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


async def generate_lesson_node(state: AAAState) -> AAAState:
    """Generate a structured lesson for the current topic.

    Uses retrieval context when available (turned on for the first time
    in the system — this has never been wired before).
    """
    _log_state("tutor", "enter", state)

    topic_name = state.get("current_topic_name", "")
    topic_description = state.get("current_topic_description", "")
    topic_difficulty = state.get("current_topic_difficulty", "beginner")
    learning_mode = state.get("learning_mode", "journey")
    mastery_score = state.get("mastery_scores", {}).get(
        state.get("current_topic_id", ""), 0.0
    )

    if not topic_name:
        state["error"] = "No topic name for lesson generation"
        state["phase"] = "complete"
        _log_state("tutor", "exit(no_topic)", state)
        return state

    # Build prerequisite context from local + web retrieval
    prereq_context = ""

    # Local retrieval (ChromaDB)
    retrieval_ctx = state.get("retrieval_context")
    if retrieval_ctx and isinstance(retrieval_ctx, dict):
        prereq_context += retrieval_ctx.get("formatted_prompt", "")

    # Web retrieval (Tavily)
    web_ctx = state.get("retrieval_web")
    if web_ctx and isinstance(web_ctx, dict):
        web_results = web_ctx.get("web_results", [])
        if web_results:
            prereq_context += "\n\n## Web Search Results\n"
            for r in web_results[:3]:
                prereq_context += f"\n- [{r.get('title', '')}]({r.get('url', '')}): {r.get('content', '')}"
        yt_results = web_ctx.get("youtube_results", [])
        if yt_results:
            prereq_context += "\n\n## Suggested Videos\n"
            for y in yt_results:
                prereq_context += f"\n- {y.get('title', '')}: {y.get('url', '')}"

    try:
        tutor = TutorService()
        lesson = await tutor.generate_lesson(
            topic_name=topic_name,
            topic_description=topic_description,
            topic_difficulty=topic_difficulty,
            learning_mode=learning_mode,
            prerequisite_context=prereq_context,
            mastery_score=mastery_score,
        )
        lesson.topic_id = state.get("current_topic_id", "")

        state["lesson"] = {
            "topic_id": lesson.topic_id,
            "topic_name": lesson.topic_name,
            "title": lesson.title,
            "cards": [
                {"title": c.title, "body": c.body, "card_type": c.card_type}
                for c in lesson.cards
            ],
            "estimated_minutes": lesson.estimated_minutes,
            "learning_mode": lesson.learning_mode,
        }
        state["phase"] = "quiz"
        logger.info(
            "Lesson generated for '%s': %d cards, %d min",
            topic_name,
            len(lesson.cards),
            lesson.estimated_minutes,
        )
        _log_state("tutor", "exit(success)", state)

    except Exception as exc:
        state["error"] = f"Lesson generation failed: {exc}"
        state["phase"] = "complete"
        logger.error("Lesson generation error for '%s': %s", topic_name, exc)
        _log_state("tutor", "exit(error)", state)

    return state
