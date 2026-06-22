"""Pydantic models for the frozen AAA frontend contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TopicResponse(BaseModel):
    topic_id: str
    topic_name: str
    subtopics: list[str]
    difficulty: Literal["beginner", "intermediate", "advanced"]
    prerequisite: str | None
    status: Literal["pending", "in_progress", "taught", "weak", "strong", "critical"]
    quiz_score: float
    attempts: int
    inferred_gap: str | None


class CreateStudentRequest(BaseModel):
    name: str = Field(min_length=1)
    raw_input: str = Field(min_length=1)


class CreateStudentResponse(BaseModel):
    student_id: str
    syllabus: list[TopicResponse]


class StartResponse(BaseModel):
    status: str
    current_topic: str


class SourceResponse(BaseModel):
    source_url: str
    summary: str


class LessonResponse(BaseModel):
    topic_name: str
    lesson_content: str
    sources: list[SourceResponse]


class QuestionResponse(BaseModel):
    question_id: str
    question: str


class QuizResponse(BaseModel):
    topic_name: str
    questions: list[QuestionResponse]


class AnswerItem(BaseModel):
    question_id: str
    answer_text: str


class AnswerRequest(BaseModel):
    answers: list[AnswerItem] = Field(min_length=1)


class AnswerResponse(BaseModel):
    score: float
    verdict: Literal["pass", "fail"]
    feedback: list[str]
    next_action: str


class StudentProfile(BaseModel):
    student_id: str
    name: str
    wants_to_read: list[str]
    was_taught: list[str]
    currently_on: str
    pending: list[str]
    weak_topics: list[str]
    session_count: int
    last_active: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
