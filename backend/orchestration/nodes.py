"""LangGraph nodes wrapping the three AAA agents."""

from __future__ import annotations

from agents.search_agent import search_and_store_topic
from agents.syllabus_parser import parse_syllabus as parse_syllabus_agent
from agents.tutor_quiz_agent import (
    evaluate_answers as evaluate_answers_agent,
    generate_quiz,
    retrieve_context,
    teach_topic as teach_topic_agent,
)
from orchestration.state import AAAState, TopicState


def _current_topic(state: AAAState) -> TopicState:
    index = state["current_topic_index"]
    if index < 0 or index >= len(state["syllabus"]):
        raise IndexError("current_topic_index is outside the syllabus")
    return state["syllabus"][index]


def parse_syllabus(state: AAAState) -> dict:
    """Parse the request and initialize the ordered topic queue."""
    parsed_topics = parse_syllabus_agent(raw_input=state["raw_input"])
    syllabus: list[TopicState] = [
        {
            "topic_id": f"topic_{index}",
            "topic_name": topic["topic_name"],
            "subtopics": topic["subtopics"],
            "difficulty": topic["difficulty"],
            "prerequisite": topic["prerequisite"],
            "status": "pending",
            "quiz_score": 0.0,
            "attempts": 0,
            "inferred_gap": None,
        }
        for index, topic in enumerate(parsed_topics)
    ]
    if not syllabus:
        raise ValueError("syllabus parser returned no topics")
    return {"syllabus": syllabus, "current_topic_index": 0}


def search_topic(state: AAAState) -> dict:
    """Search and persist sources for the current topic."""
    topic = _current_topic(state)
    context = search_and_store_topic(state["student_id"], topic["topic_name"])
    return {"retrieved_context": context}


def teach_topic(state: AAAState) -> dict:
    """Retrieve stored context and generate the current lesson."""
    topic = _current_topic(state)
    context_docs = retrieve_context(state["student_id"], topic["topic_name"])
    if not context_docs:
        context_docs = [
            item["summary"]
            for item in state["retrieved_context"]
            if item.get("summary")
        ]
    lesson = teach_topic_agent(
        topic["topic_name"], context_docs, topic["difficulty"]
    )
    syllabus = list(state["syllabus"])
    syllabus[state["current_topic_index"]] = {**topic, "status": "in_progress"}
    return {"lesson_content": lesson, "syllabus": syllabus}


def quiz_topic(state: AAAState) -> dict:
    """Generate comprehension questions for the current lesson."""
    if state["lesson_content"] is None:
        raise ValueError("lesson_content is required before quiz generation")
    return {"quiz_questions": generate_quiz(state["lesson_content"])}


def evaluate_answers(state: AAAState) -> dict:
    """Evaluate submitted answers and update topic mastery state."""
    evaluation = evaluate_answers_agent(
        state["quiz_questions"], state["quiz_answers"]
    )
    index = state["current_topic_index"]
    topic = _current_topic(state)
    score = float(evaluation["score"])
    status = "strong" if score >= 70 else "weak"
    syllabus = list(state["syllabus"])
    syllabus[index] = {
        **topic,
        "quiz_score": score,
        "attempts": topic["attempts"] + 1,
        "status": status,
    }
    return {"evaluation_result": evaluation, "syllabus": syllabus}


def advance_topic(state: AAAState) -> dict:
    """Mark a mastered topic taught and move to the next topic if present."""
    index = state["current_topic_index"]
    topic = _current_topic(state)
    syllabus = list(state["syllabus"])
    syllabus[index] = {**topic, "status": "taught"}
    next_index = index + 1
    complete = next_index >= len(syllabus)
    return {
        "syllabus": syllabus,
        "current_topic_index": index if complete else next_index,
        "retrieved_context": [],
        "lesson_content": None,
        "quiz_questions": [],
        "quiz_answers": [],
        "evaluation_result": None,
        "next_action": "complete" if complete else "advance",
    }


def reteach_topic(state: AAAState) -> dict:
    """Clear generated teaching state so Gemini produces a new explanation."""
    return {
        "lesson_content": None,
        "quiz_questions": [],
        "quiz_answers": [],
        "evaluation_result": None,
        "next_action": "reteach",
    }


def infer_prerequisite(state: AAAState) -> dict:
    """Insert a prerequisite topic before a persistently critical topic."""
    index = state["current_topic_index"]
    topic = _current_topic(state)
    inferred_gap = topic["prerequisite"] or f"Foundations of {topic['topic_name']}"
    prerequisite: TopicState = {
        "topic_id": f"{topic['topic_id']}_prerequisite_{topic['attempts']}",
        "topic_name": inferred_gap,
        "subtopics": [],
        "difficulty": "beginner",
        "prerequisite": None,
        "status": "pending",
        "quiz_score": 0.0,
        "attempts": 0,
        "inferred_gap": None,
    }
    critical_topic: TopicState = {
        **topic,
        "status": "critical",
        "inferred_gap": inferred_gap,
    }
    syllabus = list(state["syllabus"])
    syllabus[index] = critical_topic
    syllabus.insert(index, prerequisite)
    return {
        "syllabus": syllabus,
        "retrieved_context": [],
        "lesson_content": None,
        "quiz_questions": [],
        "quiz_answers": [],
        "evaluation_result": None,
        "next_action": "insert_prerequisite",
    }
