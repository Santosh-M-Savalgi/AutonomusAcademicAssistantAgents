"""Stage 9 deterministic review execution around existing schedule contracts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.adaptation import ReviewCandidate
from packages.domain.enums import LearningEventType
from packages.domain.events import ConceptLearningEventInput
from packages.domain.mastery import EvidenceInput, MasteryUpdateResult
from packages.persistence.mastery import apply_evidence
from packages.persistence.models import LearningEventRecord
from packages.persistence.review_schedule import (
    ReviewScheduleConflictError,
    emit_review_due,
    get_review_schedule,
)


async def execute_review_due(
    session: AsyncSession,
    candidate: ReviewCandidate,
    *,
    evidence: EvidenceInput,
    concept_event: ConceptLearningEventInput,
    actor_id: UUID,
    actor_subject: str,
    occurred_at: datetime,
) -> tuple[LearningEventRecord, MasteryUpdateResult]:
    """Emit/replay REVIEW_DUE, then apply the review-marked evidence once."""

    schedule = await get_review_schedule(
        session, candidate.learner_id, candidate.course_id, candidate.stable_concept_id,
    )
    if schedule is None:
        raise ValueError("Review schedule is missing")
    cycle = candidate.schedule_cycle or schedule.schedule_cycle
    due_key = ":".join((
        "review-due:v1", candidate.learner_id.hex, candidate.course_id.hex,
        candidate.stable_concept_id.hex, cycle, candidate.review_policy_version,
    ))
    due_row = await session.scalar(select(LearningEventRecord).where(
        LearningEventRecord.idempotency_key == due_key,
    ).execution_options(populate_existing=True))
    if due_row is None:
        due_row = await emit_review_due(
            session, schedule, candidate,
            actor_id=actor_id, actor_subject=actor_subject, occurred_at=occurred_at,
        )
    else:
        data = due_row.payload.get("data")
        if not isinstance(data, dict) or (
            data.get("stable_concept_id") != str(candidate.stable_concept_id)
            or data.get("schedule_cycle") != cycle
            or data.get("reasons") != [reason.value for reason in candidate.reasons]
            or data.get("due_at") != (
                None if candidate.due_at is None else candidate.due_at.isoformat()
            )
            or data.get("supporting_evidence_ids") != [
                str(value) for value in candidate.supporting_evidence_ids
            ]
            or data.get("supporting_event_ids") != [
                str(value) for value in candidate.supporting_event_ids
            ]
        ):
            raise ReviewScheduleConflictError(
                "Review retry changed the immutable due-cycle candidate",
            )
    if evidence.is_review is not True or evidence.learner_id != candidate.learner_id:
        raise ValueError("Review execution requires review-marked evidence for the candidate")
    if concept_event.type != LearningEventType.ANSWER_GRADED or (
        concept_event.source_evidence_id != evidence.evidence_id
        or concept_event.source_attempt_id != evidence.attempt_id
    ):
        raise ValueError("Review outcome event must link the original review evidence")
    result = await apply_evidence(session, evidence, concept_event=concept_event)
    return due_row, result
