"""LangGraph construction and conditional routing for AAA."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestration.nodes import (
    advance_topic,
    evaluate_answers,
    infer_prerequisite,
    parse_syllabus,
    quiz_topic,
    reteach_topic,
    search_topic,
    teach_topic,
)
from orchestration.state import AAAState


def route_after_evaluation(state: AAAState) -> str:
    current = state["syllabus"][state["current_topic_index"]]
    if current["quiz_score"] >= 70:
        return "advance_topic"
    if current["attempts"] >= 3 and current["quiz_score"] < 50:
        return "infer_prerequisite"
    return "reteach_topic"


def route_after_advance(state: AAAState) -> str:
    """Finish after the last topic; otherwise search for the new current topic."""
    return "complete" if state["next_action"] == "complete" else "continue"


def build_graph() -> CompiledStateGraph:
    """Build and compile the complete adaptive tutoring workflow."""
    builder = StateGraph(AAAState)
    builder.add_node("parse_syllabus", parse_syllabus)
    builder.add_node("search_topic", search_topic)
    builder.add_node("teach_topic", teach_topic)
    builder.add_node("quiz_topic", quiz_topic)
    builder.add_node("evaluate_answers", evaluate_answers)
    builder.add_node("advance_topic", advance_topic)
    builder.add_node("reteach_topic", reteach_topic)
    builder.add_node("infer_prerequisite", infer_prerequisite)

    builder.add_edge(START, "parse_syllabus")
    builder.add_edge("parse_syllabus", "search_topic")
    builder.add_edge("search_topic", "teach_topic")
    builder.add_edge("teach_topic", "quiz_topic")
    builder.add_edge("quiz_topic", "evaluate_answers")
    builder.add_conditional_edges(
        "evaluate_answers",
        route_after_evaluation,
        {
            "advance_topic": "advance_topic",
            "reteach_topic": "reteach_topic",
            "infer_prerequisite": "infer_prerequisite",
        },
    )
    builder.add_conditional_edges(
        "advance_topic",
        route_after_advance,
        {"continue": "search_topic", "complete": END},
    )
    builder.add_edge("reteach_topic", "teach_topic")
    builder.add_edge("infer_prerequisite", "search_topic")
    return builder.compile()


graph = build_graph()
