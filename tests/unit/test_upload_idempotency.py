"""Unit tests for scoped upload idempotency keys."""

from uuid import UUID, uuid4

from apps.api.documents.service import _database_idempotency_key


def test_idempotency_key_is_stable_and_scoped() -> None:
    course_id = uuid4()

    first = _database_idempotency_key(course_id, "student-1", "same-key")
    second = _database_idempotency_key(course_id, "student-1", "same-key")
    other_subject = _database_idempotency_key(course_id, "student-2", "same-key")
    other_course = _database_idempotency_key(UUID(int=0), "student-1", "same-key")

    assert first == second
    assert first != other_subject
    assert first != other_course
    assert first.startswith("syllabus:")
