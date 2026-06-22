"""State-contract, graph-structure, and routing tests without live agents."""

from __future__ import annotations

from orchestration.graph import build_graph, route_after_evaluation
from orchestration.state import AAAState, TopicState


TOPIC_KEYS = {
    "topic_id",
    "topic_name",
    "subtopics",
    "difficulty",
    "prerequisite",
    "status",
    "quiz_score",
    "attempts",
    "inferred_gap",
}

STATE_KEYS = {
    "student_id",
    "raw_input",
    "syllabus",
    "current_topic_index",
    "retrieved_context",
    "lesson_content",
    "quiz_questions",
    "quiz_answers",
    "evaluation_result",
    "next_action",
    "error_log",
}


def make_state(score: float, attempts: int) -> AAAState:
    topic: TopicState = {
        "topic_id": "topic_0",
        "topic_name": "Testing",
        "subtopics": ["Unit tests"],
        "difficulty": "beginner",
        "prerequisite": None,
        "status": "in_progress",
        "quiz_score": score,
        "attempts": attempts,
        "inferred_gap": None,
    }
    return {
        "student_id": "student-1",
        "raw_input": "Learn testing",
        "syllabus": [topic],
        "current_topic_index": 0,
        "retrieved_context": [],
        "lesson_content": None,
        "quiz_questions": [],
        "quiz_answers": [],
        "evaluation_result": None,
        "next_action": "advance",
        "error_log": [],
    }


def test_state_keys_match_contract_exactly() -> None:
    assert set(TopicState.__annotations__) == TOPIC_KEYS
    assert set(AAAState.__annotations__) == STATE_KEYS


def test_route_advances_at_mastery_threshold() -> None:
    assert route_after_evaluation(make_state(score=70, attempts=1)) == "advance_topic"


def test_route_infers_prerequisite_after_repeated_critical_scores() -> None:
    assert (
        route_after_evaluation(make_state(score=49, attempts=3))
        == "infer_prerequisite"
    )


def test_route_reteaches_other_failed_attempts() -> None:
    assert route_after_evaluation(make_state(score=69, attempts=3)) == "reteach_topic"
    assert route_after_evaluation(make_state(score=49, attempts=2)) == "reteach_topic"


def test_graph_contains_required_nodes_and_edges() -> None:
    drawable = build_graph().get_graph()
    node_names = set(drawable.nodes)
    edges = {(edge.source, edge.target) for edge in drawable.edges}

    assert {
        "parse_syllabus",
        "search_topic",
        "teach_topic",
        "quiz_topic",
        "evaluate_answers",
        "advance_topic",
        "reteach_topic",
        "infer_prerequisite",
    } <= node_names
    assert {
        ("parse_syllabus", "search_topic"),
        ("search_topic", "teach_topic"),
        ("teach_topic", "quiz_topic"),
        ("quiz_topic", "evaluate_answers"),
        ("evaluate_answers", "advance_topic"),
        ("evaluate_answers", "reteach_topic"),
        ("evaluate_answers", "infer_prerequisite"),
    } <= edges
