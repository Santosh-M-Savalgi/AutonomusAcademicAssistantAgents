"""Deterministic diagnostic execution adapter contracts."""

import json
from uuid import UUID

from pydantic import Field

from packages.domain.runtime import DiagnosticReservation, RuntimeValue


class DiagnosticExecutionResult(RuntimeValue):
    reservation_id: UUID
    question_version_id: UUID
    target_concept_id: UUID
    correct: float = Field(ge=0, le=1)
    result_bytes: bytes


def deterministic_diagnostic_result(
    reservation: DiagnosticReservation, *, correct: float,
) -> DiagnosticExecutionResult:
    """Return stable test-adapter output; no question or answer is generated."""

    result = json.dumps({
        "adapter": "deterministic-diagnostic-v1",
        "reservation_id": str(reservation.reservation_id),
        "question_version_id": str(reservation.question_version_id),
        "target_concept_id": str(reservation.target_concept_id),
        "correct": correct,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return DiagnosticExecutionResult(
        reservation_id=reservation.reservation_id,
        question_version_id=reservation.question_version_id,
        target_concept_id=reservation.target_concept_id,
        correct=correct, result_bytes=result,
    )
