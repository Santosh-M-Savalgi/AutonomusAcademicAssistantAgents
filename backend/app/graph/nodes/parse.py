"""Graph node: syllabus parser.

Wraps the existing SyllabusParser agent (app/agents/syllabus_parser.py)
as a LangGraph node function.

Input: state.learning_goal
Output: state.topics populated from parsed syllabus.
"""

from __future__ import annotations

import logging

from app.agents.syllabus_parser import SyllabusParser
from app.graph.state import AAAState

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


async def parse_syllabus_node(state: AAAState) -> AAAState:
    """Parse the user's learning goal into a structured topic list.

    Only runs if ``state.topics`` is empty (first invocation).
    Otherwise passes through unchanged (idempotent).

    Skips parsing when:
    - topics already exist (syllabus was already parsed)
    - current_topic_name is populated without learning_goal (direct lesson flow)
    - phase is already past "parse" (resume from checkpoint)
    """
    _log_state("parse", "enter", state)

    # Already have topics → skip parsing (idempotent guard)
    if state.get("topics"):
        state["phase"] = "retrieve"
        _log_state("parse", "exit(topics_exist)", state)
        return state

    # Resume / direct topic flow: topic data present, no need to re-parse
    if state.get("current_topic_name") and not state.get("learning_goal"):
        state["phase"] = "retrieve"
        _log_state("parse", "exit(topic_data_present)", state)
        return state

    # Phase already past parse → resume from checkpoint
    if state.get("phase", "parse") != "parse":
        _log_state("parse", "exit(phase_advanced)", state)
        return state

    goal = state.get("learning_goal", "")
    if not goal:
        state["error"] = "No learning goal provided"
        state["phase"] = "complete"
        _log_state("parse", "exit(no_goal)", state)
        return state

    try:
        parser = SyllabusParser()
        parsed = await parser.parse(goal)

        topics = []
        for t in parsed.topics:
            topics.append({
                "id": (
                    t.slug.replace("-", "_")
                    if "-" in t.slug
                    else t.slug
                ),
                "name": t.name,
                "slug": t.slug,
                "description": t.description or t.name,
                "difficulty": t.difficulty,
                "prerequisites": t.prerequisites,
            })

        state["topics"] = topics
        state["phase"] = "retrieve"
        logger.info(
            "Syllabus parsed: %d topics for goal '%s'",
            len(topics),
            goal[:60],
        )
        _log_state("parse", "exit(success)", state)

    except Exception as exc:
        state["error"] = f"Syllabus parsing failed: {exc}"
        state["phase"] = "complete"
        logger.error("Syllabus parsing error: %s", exc)
        _log_state("parse", "exit(error)", state)

    return state
