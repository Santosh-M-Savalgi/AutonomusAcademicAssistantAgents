"""Identifier-only structured runtime observations."""

from uuid import UUID

from packages.domain.models import DomainModel


class RuntimeObservation(DomainModel):
    operation: str
    outcome: str
    learner_id: UUID | None = None
    course_id: UUID | None = None
    session_id: UUID | None = None
    source_id: UUID | None = None
    execution_id: UUID | None = None
    worker_id: str | None = None
    attempt: int | None = None
    error_code: str | None = None

    def identifiers(self) -> dict[str, str | int | None]:
        return {
            "operation": self.operation,
            "outcome": self.outcome,
            "learner_id": None if self.learner_id is None else str(self.learner_id),
            "course_id": None if self.course_id is None else str(self.course_id),
            "session_id": None if self.session_id is None else str(self.session_id),
            "source_id": None if self.source_id is None else str(self.source_id),
            "execution_id": None if self.execution_id is None else str(self.execution_id),
            "worker_id": self.worker_id,
            "attempt": self.attempt,
            "error_code": self.error_code,
        }
