"""LangGraph StateGraph builder for AAA v2.

Wires the full adaptive tutoring workflow:
    parse → retrieve → retrieve_web → tutor → quiz → evaluate → route

The routing node is a conditional edge that decides:
    NEXT_TOPIC → end (graph returns with routing decision)
    REVIEW_TOPIC → back to tutor
    REPEAT_TOPIC → back to quiz
    REVISIT_PREREQUISITE → back to tutor (with new topic)
    READY_FOR_QUIZ → back to quiz

The graph is checkpointed via AAACheckpointSaver (Redis hot + Postgres durable).
Each node is small, async, and independently testable.

Architecture reference: Sections 5, 11, 14 of 01_AAA_Next_Generation_Architecture.md.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.graph.checkpointer import AAACheckpointSaver
from app.graph.nodes.evaluate import evaluate_quiz_node
from app.graph.nodes.parse import parse_syllabus_node
from app.graph.nodes.quiz import generate_quiz_node
from app.graph.nodes.retrieve import retrieve_context_node
from app.graph.nodes.retrieve_web import retrieve_web_node
from app.graph.nodes.teach import generate_lesson_node
from app.graph.state import AAAState

logger = logging.getLogger(__name__)

# ── Singleton graph instance ─────────────────────────────────────────────────

_graph: StateGraph | None = None
_checkpointer: AAACheckpointSaver | None = None


def _route_after_parse(state: AAAState) -> Literal["retrieve", END]:
    """Conditional edge: after parse, stop on error or continue to retrieve.

    Prevents the graph from silently continuing through all nodes when
    parse fails (e.g., no learning_goal provided).
    """
    error = state.get("error")
    if error:
        logger.warning("Parse failed — stopping graph: %s", error)
        return END
    logger.info("Parse succeeded — routing to retrieve")
    return "retrieve"


def _route_after_evaluate(state: AAAState) -> Literal["tutor", "quiz", END]:
    """Conditional edge: decide next node after evaluation.

    Called by LangGraph after the evaluate node completes.
    Returns the name of the next node to execute, or END.
    """
    decision = state.get("routing_decision", "")
    answers = state.get("answers", [])
    error = state.get("error")

    if error:
        logger.warning("Graph stopping due to error: %s", error)
        return END

    # Lesson-only invocation: no answers submitted yet — checkpoint and stop.
    # The evaluate node checkpoints at quiz phase; routing runs after answers exist.
    if not answers:
        return END

    if decision == "NEXT_TOPIC":
        logger.info("Routing: NEXT_TOPIC — graph complete")
        return END
    elif decision in ("REVIEW_TOPIC", "REVISIT_PREREQUISITE"):
        logger.info("Routing: %s — looping back to tutor", decision)
        # Increment attempts if not advancing
        state["attempts_on_current"] = state.get("attempts_on_current", 0) + 1
        return "tutor"
    elif decision in ("REPEAT_TOPIC", "READY_FOR_QUIZ"):
        logger.info("Routing: %s — looping back to quiz", decision)
        state["attempts_on_current"] = state.get("attempts_on_current", 0) + 1
        return "quiz"
    else:
        logger.warning("Unknown routing decision '%s' — ending", decision)
        return END


def build_graph() -> StateGraph:
    """Build (or return cached) the AAA v2 LangGraph StateGraph.

    The graph is a singleton — subsequent calls return the same instance.
    """
    global _graph, _checkpointer

    if _graph is not None:
        return _graph

    # ── Create graph ─────────────────────────────────────────────────────
    workflow = StateGraph(AAAState)

    # ── Add nodes ─────────────────────────────────────────────────────────
    workflow.add_node("parse", parse_syllabus_node)
    workflow.add_node("retrieve", retrieve_context_node)
    workflow.add_node("retrieve_web", retrieve_web_node)
    workflow.add_node("tutor", generate_lesson_node)
    workflow.add_node("quiz", generate_quiz_node)
    workflow.add_node("evaluate", evaluate_quiz_node)

    # ── Set entry point ──────────────────────────────────────────────────
    workflow.set_entry_point("parse")

    # ── Conditional edge: parse routes to retrieve or END on error ──────
    workflow.add_conditional_edges(
        "parse",
        _route_after_parse,
        {
            "retrieve": "retrieve",
            END: END,
        },
    )

    # ── Linear edges ─────────────────────────────────────────────────────
    workflow.add_edge("retrieve", "retrieve_web")
    workflow.add_edge("retrieve_web", "tutor")
    workflow.add_edge("tutor", "quiz")
    workflow.add_edge("quiz", "evaluate")

    # ── Conditional edge: route after evaluate ───────────────────────────
    workflow.add_conditional_edges(
        "evaluate",
        _route_after_evaluate,
        {
            "tutor": "tutor",
            "quiz": "quiz",
            END: END,
        },
    )

    # ── Attach checkpointer ──────────────────────────────────────────────
    _checkpointer = AAACheckpointSaver()

    # Compile with checkpointer
    _graph = workflow.compile(checkpointer=_checkpointer)

    logger.info("AAA v2 LangGraph built: 6 nodes, 2 conditional edges, checkpointer attached")
    return _graph


def get_graph() -> StateGraph:
    """Return the compiled graph singleton, building it if necessary."""
    return build_graph()


def get_checkpointer() -> AAACheckpointSaver:
    """Return the graph's checkpointer for direct access."""
    build_graph()  # ensure built
    return _checkpointer  # type: ignore[return-value]


async def reset_graph() -> None:
    """Reset the graph singleton (useful for testing)."""
    global _graph, _checkpointer
    _graph = None
    _checkpointer = None
