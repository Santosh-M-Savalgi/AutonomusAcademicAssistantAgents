"""FastAPI routes implementing the frozen `/api/v1` contract."""

from __future__ import annotations

import json
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile

from agents.syllabus_parser import parse_syllabus as parse_syllabus_agent
from api.schemas import (
    AnswerRequest,
    AnswerResponse,
    CreateStudentRequest,
    CreateStudentResponse,
    LessonResponse,
    QuizResponse,
    StartResponse,
    StudentProfile,
    TopicResponse,
)
from orchestration.graph import route_after_evaluation
from orchestration.nodes import (
    advance_topic,
    evaluate_answers,
    infer_prerequisite,
    quiz_topic,
    reteach_topic,
    search_topic,
    teach_topic,
)
from orchestration.state import AAAState, TopicState
from persistence.db import get_connection


router = APIRouter(prefix="/api/v1")
_active_states: dict[str, AAAState] = {}


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _topic_from_row(row: Any) -> TopicState:
    return {
        "topic_id": row["topic_id"],
        "topic_name": row["topic_name"],
        "subtopics": json.loads(row["subtopics_json"]),
        "difficulty": row["difficulty"],
        "prerequisite": row["prerequisite"],
        "status": row["status"],
        "quiz_score": float(row["quiz_score"]),
        "attempts": int(row["attempts"]),
        "inferred_gap": row["inferred_gap"],
    }


def _load_student(student_id: str) -> Any:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM student_profile WHERE student_id = ?", (student_id,)
        ).fetchone()
    if row is None:
        raise APIError(404, "student_not_found", "Student not found")
    return row


def _load_topics(student_id: str) -> list[TopicState]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM topic_record WHERE student_id = ? ORDER BY position",
            (student_id,),
        ).fetchall()
    return [_topic_from_row(row) for row in rows]


def _replace_topics(student_id: str, topics: list[TopicState]) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM topic_record WHERE student_id = ?", (student_id,))
        connection.executemany(
            """INSERT INTO topic_record
               (topic_id, student_id, position, topic_name, subtopics_json,
                difficulty, prerequisite, status, quiz_score, attempts, inferred_gap)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    topic["topic_id"], student_id, position, topic["topic_name"],
                    json.dumps(topic["subtopics"]), topic["difficulty"],
                    topic["prerequisite"], topic["status"], topic["quiz_score"],
                    topic["attempts"], topic["inferred_gap"],
                )
                for position, topic in enumerate(topics)
            ],
        )


def _initial_topics(parsed: list[dict[str, Any]]) -> list[TopicState]:
    return [
        {
            "topic_id": f"topic_{uuid4().hex}",
            "topic_name": topic["topic_name"],
            "subtopics": topic["subtopics"],
            "difficulty": topic["difficulty"],
            "prerequisite": topic["prerequisite"],
            "status": "pending", "quiz_score": 0.0, "attempts": 0,
            "inferred_gap": None,
        }
        for topic in parsed
    ]


def _create_student(name: str, raw_input: str, parsed: list[dict[str, Any]]) -> dict[str, Any]:
    if not parsed:
        raise APIError(502, "upstream_failure", "Syllabus parser returned no topics")
    student_id = str(uuid4())
    topics = _initial_topics(parsed)
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO student_profile (student_id, name, raw_input) VALUES (?, ?, ?)",
            (student_id, name, raw_input),
        )
    _replace_topics(student_id, topics)
    return {"student_id": student_id, "syllabus": topics}


def _profile(student_id: str) -> StudentProfile:
    student = _load_student(student_id)
    topics = _load_topics(student_id)
    index = int(student["current_topic_index"])
    complete = bool(topics) and all(topic["status"] == "taught" for topic in topics)
    last_active = str(student["last_active"]).replace(" ", "T")
    if not last_active.endswith("Z"):
        last_active += "Z"
    return StudentProfile(
        student_id=student_id,
        name=student["name"],
        wants_to_read=[topic["topic_name"] for topic in topics],
        was_taught=[topic["topic_name"] for topic in topics if topic["status"] == "taught"],
        currently_on="" if complete or not topics else topics[min(index, len(topics) - 1)]["topic_name"],
        pending=[topic["topic_name"] for topic in topics if topic["status"] == "pending"],
        weak_topics=[topic["topic_name"] for topic in topics if topic["status"] in {"weak", "critical"}],
        session_count=int(student["session_count"]),
        last_active=last_active,
    )


def _state_for_student(student_id: str) -> AAAState:
    student = _load_student(student_id)
    topics = _load_topics(student_id)
    return {
        "student_id": student_id, "raw_input": student["raw_input"],
        "syllabus": topics, "current_topic_index": int(student["current_topic_index"]),
        "retrieved_context": [], "lesson_content": None, "quiz_questions": [],
        "quiz_answers": [], "evaluation_result": None, "next_action": "advance",
        "error_log": [],
    }


def _merge(state: AAAState, update: dict[str, Any]) -> AAAState:
    return cast(AAAState, {**state, **update})


@router.post("/students", response_model=CreateStudentResponse)
def create_student(request: CreateStudentRequest) -> dict[str, Any]:
    try:
        parsed = parse_syllabus_agent(raw_input=request.raw_input)
    except Exception as exc:
        raise APIError(502, "upstream_failure", str(exc)) from exc
    return _create_student(request.name, request.raw_input, cast(list[dict[str, Any]], parsed))


@router.post("/students/upload-syllabus", response_model=CreateStudentResponse)
async def upload_syllabus(name: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise APIError(422, "validation_error", "file must be a PDF")
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary.write(await file.read())
            path = Path(temporary.name)
        parsed = parse_syllabus_agent(pdf_path=str(path))
    except APIError:
        raise
    except Exception as exc:
        raise APIError(502, "upstream_failure", str(exc)) from exc
    finally:
        if path is not None:
            with suppress(OSError):
                path.unlink()
        await file.close()
    return _create_student(name, "", cast(list[dict[str, Any]], parsed))


@router.get("/students/{student_id}", response_model=StudentProfile)
def get_student(student_id: str) -> StudentProfile:
    return _profile(student_id)


@router.post("/students/{student_id}/start", response_model=StartResponse)
def start_student(student_id: str) -> dict[str, str]:
    state = _state_for_student(student_id)
    if not state["syllabus"] or all(
        topic["status"] == "taught" for topic in state["syllabus"]
    ):
        return {"status": "complete", "current_topic": ""}
    try:
        for node in (search_topic, teach_topic, quiz_topic):
            state = _merge(state, node(state))
    except Exception as exc:
        raise APIError(502, "upstream_failure", str(exc)) from exc
    _active_states[student_id] = state
    _replace_topics(student_id, state["syllabus"])
    with get_connection() as connection:
        connection.execute(
            """UPDATE student_profile SET session_count = session_count + 1,
               last_active = CURRENT_TIMESTAMP WHERE student_id = ?""", (student_id,)
        )
    topic = state["syllabus"][state["current_topic_index"]]
    return {"status": "ready", "current_topic": topic["topic_name"]}


def _active_state(student_id: str) -> AAAState:
    _load_student(student_id)
    state = _active_states.get(student_id)
    if state is None:
        raise APIError(404, "session_not_started", "Start the student session first")
    return state


@router.get("/students/{student_id}/lesson", response_model=LessonResponse)
def get_lesson(student_id: str) -> dict[str, Any]:
    state = _active_state(student_id)
    topic = state["syllabus"][state["current_topic_index"]]
    if state["lesson_content"] is None:
        raise APIError(404, "lesson_not_ready", "Lesson is not ready")
    return {"topic_name": topic["topic_name"], "lesson_content": state["lesson_content"],
            "sources": [{"source_url": item["source_url"], "summary": item["summary"]}
                        for item in state["retrieved_context"]]}


@router.get("/students/{student_id}/quiz", response_model=QuizResponse)
def get_quiz(student_id: str) -> dict[str, Any]:
    state = _active_state(student_id)
    topic = state["syllabus"][state["current_topic_index"]]
    return {"topic_name": topic["topic_name"],
            "questions": [{"question_id": str(index), "question": question["question"]}
                          for index, question in enumerate(state["quiz_questions"])]}


@router.post("/students/{student_id}/answer", response_model=AnswerResponse)
def submit_answers(student_id: str, request: AnswerRequest) -> dict[str, Any]:
    state = _active_state(student_id)
    supplied = {answer.question_id: answer.answer_text for answer in request.answers}
    expected_ids = [str(index) for index in range(len(state["quiz_questions"]))]
    if set(supplied) != set(expected_ids):
        raise APIError(422, "validation_error", "Provide exactly one answer for every question_id")
    state = _merge(state, {"quiz_answers": [supplied[key] for key in expected_ids]})
    try:
        state = _merge(state, evaluate_answers(state))
        route = route_after_evaluation(state)
        branch = {"advance_topic": advance_topic, "reteach_topic": reteach_topic,
                  "infer_prerequisite": infer_prerequisite}[route]
        evaluation = state["evaluation_result"]
        state = _merge(state, branch(state))
    except Exception as exc:
        raise APIError(502, "upstream_failure", str(exc)) from exc
    assert evaluation is not None
    _replace_topics(student_id, state["syllabus"])
    with get_connection() as connection:
        connection.execute(
            """UPDATE student_profile SET current_topic_index = ?, last_active = CURRENT_TIMESTAMP
               WHERE student_id = ?""", (state["current_topic_index"], student_id)
        )
    _active_states[student_id] = state
    return {"score": evaluation["score"], "verdict": evaluation["verdict"],
            "feedback": evaluation["per_question_feedback"],
            "next_action": state["next_action"]}


@router.get("/students/{student_id}/profile", response_model=StudentProfile)
def get_profile(student_id: str) -> StudentProfile:
    return _profile(student_id)


@router.get("/students/{student_id}/topics", response_model=list[TopicResponse])
def get_topics(student_id: str) -> list[TopicState]:
    _load_student(student_id)
    return _load_topics(student_id)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
