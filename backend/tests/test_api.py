"""Offline contract validation for all FastAPI endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from fastapi.testclient import TestClient

import api.routes as routes
import main
from persistence.db import get_connection, init_db


def _route_methods(app) -> set[tuple[str, str]]:
    route_methods: set[tuple[str, str]] = set()
    pending = list(app.routes)
    while pending:
        route = pending.pop()
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            pending.extend(original_router.routes)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            pending.extend(nested)
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if path is not None:
            route_methods.update((method, path) for method in methods)
    return route_methods


def test_endpoint_contract_and_mocked_full_flow(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "api.db"
        init_db(db_path)

        @contextmanager
        def test_connection() -> Iterator[Any]:
            with get_connection(db_path) as connection:
                yield connection

        monkeypatch.setattr(routes, "get_connection", test_connection)
        monkeypatch.setattr(main, "init_db", lambda: init_db(db_path))
        routes._active_states.clear()
        parsed = [{"topic_name": "Testing", "subtopics": ["Unit tests"],
                   "difficulty": "beginner", "prerequisite": None}]
        monkeypatch.setattr(routes, "parse_syllabus_agent", lambda **_kwargs: parsed)
        monkeypatch.setattr(routes, "search_topic", lambda _state: {
            "retrieved_context": [{"source_url": "https://example.test", "summary": "Notes", "score": 1.0}]})
        monkeypatch.setattr(routes, "teach_topic", lambda state: {
            "lesson_content": "Lesson", "syllabus": state["syllabus"]})
        monkeypatch.setattr(routes, "quiz_topic", lambda _state: {
            "quiz_questions": [{"question": "Why test?", "expected_concept": "quality"}]})
        monkeypatch.setattr(routes, "evaluate_answers", lambda state: {
            "evaluation_result": {"score": 80.0, "per_question_feedback": ["Correct"], "verdict": "pass"},
            "syllabus": [{**state["syllabus"][0], "quiz_score": 80.0, "attempts": 1}]})

        with TestClient(main.app) as client:
            expected = {
                ("POST", "/api/v1/students"),
                ("POST", "/api/v1/students/upload-syllabus"),
                ("GET", "/api/v1/students/{student_id}"),
                ("POST", "/api/v1/students/{student_id}/start"),
                ("GET", "/api/v1/students/{student_id}/lesson"),
                ("GET", "/api/v1/students/{student_id}/quiz"),
                ("POST", "/api/v1/students/{student_id}/answer"),
                ("GET", "/api/v1/students/{student_id}/profile"),
                ("GET", "/api/v1/students/{student_id}/topics"),
                ("GET", "/api/v1/health"),
            }
            actual = _route_methods(main.app)
            assert expected <= actual
            assert client.get("/api/v1/health").json() == {"status": "ok"}
            created = client.post("/api/v1/students", json={"name": "Ada", "raw_input": "Learn testing"})
            assert created.status_code == 200
            student_id = created.json()["student_id"]
            assert client.post(f"/api/v1/students/{student_id}/start").status_code == 200
            assert client.get(f"/api/v1/students/{student_id}/lesson").json()["lesson_content"] == "Lesson"
            quiz = client.get(f"/api/v1/students/{student_id}/quiz").json()
            answered = client.post(f"/api/v1/students/{student_id}/answer", json={
                "answers": [{"question_id": quiz["questions"][0]["question_id"], "answer_text": "Quality"}]})
            assert answered.status_code == 200
            assert answered.json()["next_action"] == "complete"
            assert client.get(f"/api/v1/students/{student_id}").status_code == 200
            assert client.get(f"/api/v1/students/{student_id}/profile").status_code == 200
            assert client.get(f"/api/v1/students/{student_id}/topics").status_code == 200
            error = client.get("/api/v1/students/missing")
            assert error.status_code == 404
            assert set(error.json()) == {"error"}
