"""Shared LangGraph state definitions for the AAA workflow."""

from typing import Literal, Optional, TypedDict


class TopicState(TypedDict):
    topic_id: str
    topic_name: str
    subtopics: list[str]
    difficulty: Literal["beginner", "intermediate", "advanced"]
    prerequisite: Optional[str]
    status: Literal["pending", "in_progress", "taught", "weak", "strong", "critical"]
    quiz_score: float
    attempts: int
    inferred_gap: Optional[str]


class AAAState(TypedDict):
    student_id: str
    raw_input: str
    syllabus: list[TopicState]
    current_topic_index: int
    retrieved_context: list[dict]
    lesson_content: Optional[str]
    quiz_questions: list[dict]
    quiz_answers: list[str]
    evaluation_result: Optional[dict]
    next_action: Literal["advance", "reteach", "insert_prerequisite", "complete"]
    error_log: list[str]
