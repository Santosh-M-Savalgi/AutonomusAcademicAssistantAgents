"""AAAState — LangGraph state schema for AAA v2.

TypedDict with real type annotations for LangGraph 1.x compatibility.
LangGraph uses these annotations to create state channels; without them,
StateGraph(AAAState) produces zero channels and ainvoke() returns None.

Fields:
    messages: Accumulated chat/event messages (standard LangGraph convention).
    session_id: UUID of the active learning session.
    syllabus_id: UUID of the syllabus being studied.
    learning_goal: Original free-text learning goal.
    topics: Parsed topic list [{id, name, slug, description, difficulty, prerequisites}].
    current_topic_id: UUID of the topic currently being studied.
    current_topic_name: Human-readable name.
    current_topic_description: Topic description text.
    current_topic_difficulty: beginner | intermediate | advanced.
    mastery_scores: {topic_id: float 0.0-1.0} mastery snapshot.
    retrieval_context: Dict-serialized RetrievalResult (set by retrieve node).
    retrieval_web: Dict-serialized web search results (set by retrieve_web node).
    lesson: Dict-serialized Lesson (set by tutor node).
    quiz: Dict-serialized Quiz (set by quiz node).
    evaluation: Dict-serialized EvaluationResult (set by evaluate node).
    answers: Student's submitted answers (set by quiz evaluate endpoint).
    routing_decision: String from RoutingDecision enum.
    routing_reason: Human-readable explanation of routing decision.
    next_topic_id: UUID of the next topic (set when advancing).
    phase: Current graph phase (parse|retrieve|tutor|quiz|evaluate|route|complete).
    phase_completed: Last successfully completed phase.
    error: Error message if a node failed.
    attempts_on_current: Number of quiz attempts on the current topic.
    learning_mode: sprint | journey | mastery.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from typing_extensions import TypedDict  # compatible with Python 3.11+

from langgraph.graph.message import add_messages


class AAAState(TypedDict, total=False):
    """LangGraph state schema — TypedDict with real type annotations.

    ``total=False`` means all keys are optional, matching the existing
    dict-based access pattern throughout the codebase.
    """

    # ── Core identity ──────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]
    session_id: str
    syllabus_id: str
    learning_goal: str

    # ── Syllabus / topics ──────────────────────────────────────────────────
    topics: list[dict[str, Any]]  # [{id, name, slug, description, difficulty, prerequisites}]

    # ── Current topic ──────────────────────────────────────────────────────
    current_topic_id: str
    current_topic_name: str
    current_topic_description: str
    current_topic_difficulty: str

    # ── Mastery ────────────────────────────────────────────────────────────
    mastery_scores: dict[str, float]

    # ── Retrieval ──────────────────────────────────────────────────────────
    retrieval_context: Optional[dict[str, Any]]
    retrieval_web: Optional[dict[str, Any]]

    # ── Generated artifacts ────────────────────────────────────────────────
    lesson: Optional[dict[str, Any]]
    quiz: Optional[dict[str, Any]]
    evaluation: Optional[dict[str, Any]]

    # ── Student input ──────────────────────────────────────────────────────
    answers: list[dict[str, Any]]

    # ── Routing ────────────────────────────────────────────────────────────
    routing_decision: str
    routing_reason: str
    next_topic_id: Optional[str]

    # ── Phase tracking ─────────────────────────────────────────────────────
    phase: str
    phase_completed: str

    # ── Error handling ─────────────────────────────────────────────────────
    error: Optional[str]

    # ── Adaptive counters ──────────────────────────────────────────────────
    attempts_on_current: int
    learning_mode: str


def initial_state(
    session_id: str = "",
    syllabus_id: str = "",
    learning_goal: str = "",
    topics: Optional[list[dict[str, Any]]] = None,
    current_topic_id: str = "",
    current_topic_name: str = "",
    current_topic_description: str = "",
    current_topic_difficulty: str = "beginner",
    learning_mode: str = "journey",
) -> AAAState:
    """Build the initial state dictionary for a new graph invocation.

    Returns a plain dict conforming to the AAAState TypedDict schema.
    LangGraph accepts plain dicts that satisfy the TypedDict shape.
    """
    return {  # type: ignore[return-value]
        "messages": [],
        "session_id": session_id,
        "syllabus_id": syllabus_id,
        "learning_goal": learning_goal,
        "topics": topics or [],
        "current_topic_id": current_topic_id,
        "current_topic_name": current_topic_name,
        "current_topic_description": current_topic_description,
        "current_topic_difficulty": current_topic_difficulty,
        "mastery_scores": {},
        "retrieval_context": None,
        "retrieval_web": None,
        "lesson": None,
        "quiz": None,
        "evaluation": None,
        "answers": [],
        "routing_decision": "",
        "routing_reason": "",
        "next_topic_id": None,
        "phase": "parse",
        "phase_completed": "",
        "error": None,
        "attempts_on_current": 0,
        "learning_mode": learning_mode,
    }
