"""Stage 9 diagnostic reservation, deterministic completion and inference runtime."""

from collections.abc import Sequence
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.curriculum.diagnostics import inferred_evidence_for_prerequisite
from packages.domain.adaptation import DiagnosticCandidate, DiagnosticInferenceProvenance
from packages.domain.events import ConceptLearningEventInput
from packages.domain.mastery import EvidenceInput, MasteryUpdateResult
from packages.domain.runtime import DiagnosticInferenceLink, DiagnosticReservation, ReservationState
from packages.persistence.mastery import apply_evidence
from packages.persistence.runtime import (
    RuntimeConflictError,
    RuntimeStaleError,
    RuntimeValidationError,
    acknowledge_diagnostic_reservation,
    link_diagnostic_inference,
    mark_diagnostic_reservation_attempted,
    reserve_diagnostic_question,
)
from packages.persistence.runtime_models import DiagnosticReservationRecord


async def reserve_diagnostic_candidates(
    session: AsyncSession,
    learner_id: UUID,
    session_id: UUID,
    *,
    run_id: UUID,
    execution_id: UUID,
    candidates: Sequence[DiagnosticCandidate],
    expected_run_version: int,
    reserved_at: datetime,
) -> tuple[DiagnosticReservation, ...]:
    """Reserve the already-selected inventory in deterministic candidate order."""

    reservations: list[DiagnosticReservation] = []
    for candidate in candidates:
        for question_id in candidate.question_version_ids:
            reservation_id = uuid5(
                NAMESPACE_URL,
                f"diagnostic-reservation:v1:{run_id.hex}:{question_id.hex}",
            )
            reservation = await reserve_diagnostic_question(
                session, learner_id, session_id,
                run_id=run_id, reservation_id=reservation_id,
                execution_id=execution_id, question_version_id=question_id,
                target_concept_id=candidate.stable_concept_id,
                expected_run_version=expected_run_version, reserved_at=reserved_at,
            )
            reservations.append(reservation)
    return tuple(reservations)


async def complete_diagnostic_answer(
    session: AsyncSession,
    learner_id: UUID,
    session_id: UUID,
    reservation_id: UUID,
    *,
    evidence: EvidenceInput,
    event_id: UUID,
    attempted_at: datetime,
    assessed_at: datetime,
    diagnostic_inferences: Sequence[DiagnosticInferenceProvenance] = (),
    concept_event: ConceptLearningEventInput | None = None,
) -> tuple[DiagnosticReservation, MasteryUpdateResult]:
    """Commit direct diagnostic evidence, reservation assessment and inferred links."""

    row = await session.scalar(select(DiagnosticReservationRecord).where(
        DiagnosticReservationRecord.id == reservation_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None or row.session_id != session_id:
        raise RuntimeValidationError("Diagnostic reservation is missing")
    before = DiagnosticReservation(
        reservation_id=row.id, diagnostic_run_id=row.diagnostic_run_id,
        graph_version_id=row.graph_version_id, execution_id=row.execution_id,
        question_version_id=row.question_version_id, target_concept_id=row.target_concept_id,
        item_budget=row.item_budget, slot=row.slot, state=ReservationState(row.state),
        version=row.version, source_attempt_id=row.source_attempt_id,
        source_evidence_id=row.source_evidence_id, completion_event_id=row.completion_event_id,
        assessed_concept_ids=tuple(UUID(item) for item in row.assessed_concept_ids),
        reserved_at=row.reserved_at, attempted_at=row.attempted_at, assessed_at=row.assessed_at,
    )
    if before.state == ReservationState.ASSESSED:
        if (
            before.source_evidence_id != evidence.evidence_id
            or before.completion_event_id != event_id
        ):
            raise RuntimeConflictError(
                "Completed diagnostic reservation was reused with changed material",
            )
        result = await apply_evidence(
            session, evidence, concept_event=concept_event,
            diagnostic_inferences=diagnostic_inferences,
        )
        return before, result
    if before.state not in {ReservationState.RESERVED, ReservationState.ATTEMPTED}:
        raise RuntimeStaleError("Diagnostic reservation is already being completed")
    if evidence.question_version_id != before.question_version_id or evidence.attempt_id is None:
        raise RuntimeValidationError("Diagnostic evidence does not match its reservation")
    if before.target_concept_id not in {
        role.stable_concept_id for role in evidence.concept_roles
    }:
        raise RuntimeValidationError("Diagnostic evidence does not assess its reserved concept")
    if evidence.is_review or evidence.kind != "DIRECT":
        raise RuntimeValidationError("Diagnostic completion requires direct non-review evidence")
    if evidence.correct < 1.0 and diagnostic_inferences:
        raise RuntimeValidationError("Only full-credit diagnostic answers can infer prerequisites")
    for provenance in diagnostic_inferences:
        if provenance.diagnostic_run_id != before.diagnostic_run_id or (
            provenance.source_attempt_id != evidence.attempt_id
            or provenance.source_evidence_id != evidence.evidence_id
        ):
            raise RuntimeValidationError(
                "Diagnostic inference provenance conflicts with reservation",
            )
    if before.state == ReservationState.RESERVED:
        attempted = await mark_diagnostic_reservation_attempted(
            session, learner_id, session_id, reservation_id,
            source_attempt_id=evidence.attempt_id, event_id=event_id,
            expected_version=before.version, attempted_at=attempted_at,
        )
    else:
        if before.source_attempt_id != evidence.attempt_id:
            raise RuntimeConflictError("Attempted diagnostic reservation changed source attempt")
        attempted = before
    result = await apply_evidence(
        session, evidence, concept_event=concept_event,
        diagnostic_inferences=diagnostic_inferences,
    )
    assessed_concepts = {
        before.target_concept_id,
        *(item.stable_concept_id for item in evidence.concept_roles),
        *(item.target_prerequisite_concept_id for item in diagnostic_inferences),
    }
    completed = attempted.model_copy(update={
        "state": ReservationState.ASSESSED,
        "version": attempted.version + 1,
        "source_attempt_id": evidence.attempt_id,
        "source_evidence_id": evidence.evidence_id,
        "completion_event_id": event_id,
        "assessed_concept_ids": tuple(sorted(assessed_concepts, key=lambda item: item.bytes)),
        "reserved_at": before.reserved_at,
        "attempted_at": attempted_at,
        "assessed_at": assessed_at,
    })
    completed = await acknowledge_diagnostic_reservation(
        session, learner_id, session_id, completed,
        expected_version=attempted.version, event_id=event_id,
    )
    for provenance in diagnostic_inferences:
        derived = inferred_evidence_for_prerequisite(evidence, provenance)
        await link_diagnostic_inference(
            session, learner_id, session_id,
            DiagnosticInferenceLink(
                evidence_id=derived.evidence_id,
                reservation_id=reservation_id,
                provenance=provenance,
            ),
        )
    return completed, result
