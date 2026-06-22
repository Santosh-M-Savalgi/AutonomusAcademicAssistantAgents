"""Agent 3: retrieve context, teach a topic, quiz, and evaluate answers."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal, TypedDict, cast

from google import genai
from google.genai import types

from config import settings
from persistence.vector_store import embed_text, get_student_collection


class QuizQuestion(TypedDict):
    question: str
    expected_concept: str


class EvaluationResult(TypedDict):
    score: float
    per_question_feedback: list[str]
    verdict: Literal["pass", "fail"]


QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "expected_concept": {"type": "string"},
                },
                "required": ["question", "expected_concept"],
            },
        }
    },
    "required": ["questions"],
}


EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "per_question_feedback": {
            "type": "array",
            "items": {"type": "string"},
        },
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
    },
    "required": ["score", "per_question_feedback", "verdict"],
}


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    """Create one Gemini client lazily for all tutor and quiz operations."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for tutoring and quizzes")
    return genai.Client(api_key=settings.gemini_api_key)


def retrieve_context(
    student_id: str, topic_name: str, threshold: float = 0.75
) -> list[str]:
    """Retrieve documents whose cosine similarity is above the threshold."""
    if not student_id.strip():
        raise ValueError("student_id must not be empty")
    if not topic_name.strip():
        raise ValueError("topic_name must not be empty")

    collection = get_student_collection(student_id)
    query_vector = embed_text(topic_name)
    results = collection.query(query_embeddings=[query_vector], n_results=5)
    document_groups = results.get("documents") or [[]]
    distance_groups = results.get("distances") or [[]]
    documents = document_groups[0]
    distances = distance_groups[0]
    return [
        document
        for document, distance in zip(documents, distances)
        if document is not None and (1 - float(distance)) > threshold
    ]


def teach_topic(
    topic_name: str, context_docs: list[str], student_level: str
) -> str:
    """Generate a structured lesson grounded in retrieved context."""
    context = "\n\n".join(context_docs)
    response = _get_client().models.generate_content(
        model=settings.tutor_model,
        contents=(
            f'You are tutoring a {student_level} student on "{topic_name}".\n'
            f"Use this retrieved context:\n{context}\n\n"
            "Structure the lesson as: Concept -> Worked Example -> Real-world Analogy.\n"
            f"Be concrete, avoid filler, match the {student_level} depth."
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty lesson")
    return response.text


def generate_quiz(lesson_content: str) -> list[QuizQuestion]:
    """Generate three schema-conformant comprehension questions."""
    if not lesson_content.strip():
        raise ValueError("lesson_content must not be empty")

    response = _get_client().models.generate_content(
        model=settings.tutor_model,
        contents=(
            "Generate 3 quiz questions testing comprehension of this lesson:\n"
            f"{lesson_content}"
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=QUIZ_SCHEMA,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty quiz response")
    payload = json.loads(response.text)
    return cast(list[QuizQuestion], payload["questions"])


def evaluate_answers(
    questions: list[QuizQuestion], answers: list[str]
) -> EvaluationResult:
    """Evaluate student responses for conceptual rather than verbatim accuracy."""
    if not questions:
        raise ValueError("questions must not be empty")
    if len(questions) != len(answers):
        raise ValueError("one answer is required for every question")

    pairs = "\n".join(
        f"Q: {question['question']}\n"
        f"Expected concept: {question['expected_concept']}\n"
        f"Student answer: {answer}"
        for question, answer in zip(questions, answers)
    )
    response = _get_client().models.generate_content(
        model=settings.tutor_model,
        contents=(
            "Evaluate these answers for conceptual correctness (not exact wording).\n"
            f"{pairs}\nScore as a percentage 0-100. Pass threshold is 70."
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EVAL_SCHEMA,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty evaluation response")
    return cast(EvaluationResult, json.loads(response.text))
