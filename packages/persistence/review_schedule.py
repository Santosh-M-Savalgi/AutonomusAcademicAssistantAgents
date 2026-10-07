"""Caller-owned persistence for Sprint 3.5 review schedules and due events."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.adaptation import (
    ProjectionFreshness,
    ProjectionFreshnessResult,
    ReviewCandidate,
    ReviewDueReason,
    ReviewScheduleState,
    ReviewSelectionResult,
)
from packages.domain.enums import LearningEventType
from packages.domain.events import (
    ConceptLearningEventInput,
    LearningEventInput,
    LearningEventPayload,
)
from packages.domain.mastery import ConceptMastery, ReplayResult
from packages.mastery.scheduling import (
    recompute_after_success,
    refresh_projection_metadata,
    review_due_idempotency_key,
    schedule_cycle,
    schedule_cycle_material,
    seed_initial_schedule,
    seed_low_mastery_schedule,
    select_review_candidates,
)
from packages.persistence.learning_events import event_from_record, insert_learning_event
from packages.persistence.models import (
    CurriculumGraphConcept,
    CurriculumGraphVersion,
    LearningEventRecord,
    MasteryProjectionHead,
    MasteryProjectionRevision,
    ReviewSchedule,
    StudentIdentity,
)


class ReviewScheduleConflictError(ValueError):
    """A schedule or due event was reused with conflicting immutable content."""


async def _lock_review_learner(session: AsyncSession, learner_id: UUID) -> None:
    learner = await session.scalar(select(StudentIdentity).where(
        StudentIdentity.id == learner_id,
    ).with_for_update())
    if learner is None:
        raise ReviewScheduleConflictError("Review learner identity does not exist")


def _state_from_row(row: ReviewSchedule) -> ReviewScheduleState:
    return ReviewScheduleState(
        learner_id=row.learner_identity_id,
        course_id=row.course_id,
        stable_concept_id=row.stable_concept_id,
        graph_version_id=row.graph_version_id,
        review_policy_version=row.review_policy_version,
        review_rung=row.review_rung,
        review_successes=row.review_successes,
        first_concept_event_id=row.first_concept_event_id,
        first_concept_event_at=row.first_concept_event_at,
        last_successful_review_at=row.last_successful_review_at,
        last_successful_review_evidence_id=row.last_successful_review_evidence_id,
        last_successful_review_event_id=row.last_successful_review_event_id,
        due_at=row.due_at,
        projection_revision_id=row.projection_revision_id,
        evidence_set_digest=row.evidence_set_digest,
        evidence_count=row.evidence_count,
        schedule_cycle=row.schedule_cycle,
        supporting_evidence_ids=tuple(UUID(value) for value in row.supporting_evidence_ids),
        supporting_event_ids=tuple(UUID(value) for value in row.supporting_event_ids),
    )


def _candidate_matches_schedule(
    state: ReviewScheduleState,
    candidate: ReviewCandidate,
) -> bool:
    """Validate candidate provenance before preserving or creating an event."""

    return (
        candidate.learner_id == state.learner_id
        and candidate.course_id == state.course_id
        and candidate.stable_concept_id == state.stable_concept_id
        and candidate.due_at == state.due_at
        and candidate.projection_revision_id == state.projection_revision_id
        and candidate.evidence_set_digest == state.evidence_set_digest
        and candidate.graph_version_id == state.graph_version_id
        and candidate.review_policy_version == state.review_policy_version
        and (
            candidate.schedule_cycle is None
            or candidate.schedule_cycle == state.schedule_cycle
        )
        and candidate.review_rung == state.review_rung
        and candidate.review_successes == state.review_successes
        and candidate.supporting_evidence_ids == state.supporting_evidence_ids
        and candidate.supporting_event_ids == state.supporting_event_ids
    )


def _event_payload_matches_schedule(
    payload: dict[str, Any],
    state: ReviewScheduleState,
) -> bool:
    """Check only immutable cycle/source fields; retry metadata is preserved."""

    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    anchor = state.last_successful_review_event_id or state.first_concept_event_id
    return (
        payload.get("kind") == "review_due"
        and data.get("stable_concept_id") == str(state.stable_concept_id)
        and data.get("schedule_cycle") == state.schedule_cycle
        and data.get("graph_version_id") == (
            None if state.graph_version_id is None else str(state.graph_version_id)
        )
        and data.get("evidence_set_digest") == state.evidence_set_digest
        and data.get("due_at") == (None if state.due_at is None else state.due_at.isoformat())
        and data.get("supporting_evidence_ids") == [
            str(value) for value in state.supporting_evidence_ids
        ]
        and data.get("supporting_event_ids") == [
            str(value) for value in state.supporting_event_ids
        ]
        and (
            "cycle_material" not in data
            or data["cycle_material"] == schedule_cycle_material(state)
        )
        and (
            "anchor_event_id" not in data
            or data["anchor_event_id"] == (None if anchor is None else str(anchor))
        )
    )


def _row_from_state(
    row: ReviewSchedule | None,
    state: ReviewScheduleState,
    *,
    reasons: Sequence[ReviewDueReason] = (),
) -> ReviewSchedule:
    if row is None:
        row = ReviewSchedule(
            id=uuid4(),
            learner_identity_id=state.learner_id,
            course_id=state.course_id,
            stable_concept_id=state.stable_concept_id,
        )
    row.graph_version_id = state.graph_version_id
    row.review_policy_version = state.review_policy_version
    row.review_rung = state.review_rung
    row.review_successes = state.review_successes
    row.first_concept_event_id = state.first_concept_event_id
    row.first_concept_event_at = state.first_concept_event_at
    row.last_successful_review_at = state.last_successful_review_at
    row.last_successful_review_evidence_id = state.last_successful_review_evidence_id
    row.last_successful_review_event_id = state.last_successful_review_event_id
    row.due_at = state.due_at
    row.projection_revision_id = state.projection_revision_id
    row.evidence_set_digest = state.evidence_set_digest
    row.evidence_count = state.evidence_count
    row.schedule_cycle = state.schedule_cycle
    row.reasons = [reason.value for reason in reasons]
    row.supporting_evidence_ids = [str(value) for value in state.supporting_evidence_ids]
    row.supporting_event_ids = [str(value) for value in state.supporting_event_ids]
    row.status = "ACTIVE"
    return row


async def upsert_review_schedule(
    session: AsyncSession,
    state: ReviewScheduleState,
    *,
    reasons: Sequence[ReviewDueReason] = (),
) -> ReviewSchedule:
    """Lock and update one current schedule without committing."""

    row = await session.scalar(select(ReviewSchedule).where(
        ReviewSchedule.learner_identity_id == state.learner_id,
        ReviewSchedule.course_id == state.course_id,
        ReviewSchedule.stable_concept_id == state.stable_concept_id,
    ).with_for_update())
    row = _row_from_state(row, state, reasons=reasons)
    session.add(row)
    await session.flush()
    return row


async def get_review_schedule(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    stable_concept_id: UUID,
) -> ReviewScheduleState | None:
    row = await session.scalar(select(ReviewSchedule).where(
        ReviewSchedule.learner_identity_id == learner_id,
        ReviewSchedule.course_id == course_id,
        ReviewSchedule.stable_concept_id == stable_concept_id,
    ))
    return None if row is None else _state_from_row(row)


async def list_review_schedules(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
) -> list[ReviewScheduleState]:
    rows = (await session.scalars(select(ReviewSchedule).where(
        ReviewSchedule.learner_identity_id == learner_id,
        ReviewSchedule.course_id == course_id,
        ReviewSchedule.status == "ACTIVE",
    ).order_by(ReviewSchedule.stable_concept_id))).all()
    return [_state_from_row(row) for row in rows]


async def emit_review_due(
    session: AsyncSession,
    state: ReviewScheduleState,
    candidate: ReviewCandidate,
    *,
    actor_id: UUID,
    actor_subject: str,
    occurred_at: datetime,
    correlation_id: UUID | None = None,
) -> LearningEventRecord:
    """Create or reuse the first immutable non-impact notification for a cycle.

    Calculation time/reasons/projection revision are observations, not new cycle
    identities. Explicit correlation requests and immutable source conflicts are
    rejected; generic event equality is unchanged.
    """

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("Review notification timestamps must be timezone-aware")
    # Match mastery lock order: learner before schedule, then event insertion.
    await _lock_review_learner(session, state.learner_id)

    row = await session.scalar(select(ReviewSchedule).where(
        ReviewSchedule.learner_identity_id == state.learner_id,
        ReviewSchedule.course_id == state.course_id,
        ReviewSchedule.stable_concept_id == state.stable_concept_id,
    ).with_for_update().execution_options(populate_existing=True))
    if (
        row is None or row.status != "ACTIVE"
        or row.schedule_cycle != state.schedule_cycle
        or schedule_cycle(state) != state.schedule_cycle
    ):
        raise ReviewScheduleConflictError("Review schedule cycle is missing or stale")
    locked_state = _state_from_row(row)
    if locked_state != state or not _candidate_matches_schedule(locked_state, candidate):
        raise ReviewScheduleConflictError("Review candidate provenance is stale or conflicting")
    occurred_at = occurred_at.astimezone(UTC)
    idempotency_key = review_due_idempotency_key(state)
    event_id = uuid5(NAMESPACE_URL, idempotency_key)
    existing = await session.scalar(select(LearningEventRecord).where(
        LearningEventRecord.idempotency_key == idempotency_key,
    ).with_for_update())
    if existing is not None:
        if (
            existing.event_id != event_id
            or existing.event_type != LearningEventType.REVIEW_DUE.value
            or existing.actor_identity_id != actor_id
            or existing.actor_subject != actor_subject
            or existing.learner_identity_id != state.learner_id
            or existing.course_id != state.course_id
            or existing.event_schema_version != "learning-event-v1"
            or existing.causation_id is not None
            or existing.versions is not None
            or not _event_payload_matches_schedule(existing.payload, state)
            or (correlation_id is not None and correlation_id != existing.correlation_id)
        ):
            raise ReviewScheduleConflictError(
                "Existing REVIEW_DUE event conflicts with the current schedule cycle"
            )
        original = event_from_record(existing)
        return await insert_learning_event(session, LearningEventInput.model_validate(
            original.model_dump(exclude={"recorded_at"}),
        ))
    row.reasons = [reason.value for reason in candidate.reasons]
    session.add(row)
    await session.flush()
    anchor = state.last_successful_review_event_id or state.first_concept_event_id
    payload = LearningEventPayload(
        kind="review_due",
        data={
            "stable_concept_id": str(state.stable_concept_id),
            "schedule_cycle": state.schedule_cycle,
            "cycle_material": schedule_cycle_material(state),
            "anchor_event_id": None if anchor is None else str(anchor),
            "graph_version_id": (
                None if state.graph_version_id is None else str(state.graph_version_id)
            ),
            "projection_revision_id": (
                None
                if state.projection_revision_id is None
                else str(state.projection_revision_id)
            ),
            "evidence_set_digest": state.evidence_set_digest,
            "due_at": None if candidate.due_at is None else candidate.due_at.isoformat(),
            "reasons": [reason.value for reason in candidate.reasons],
            "supporting_evidence_ids": [str(value) for value in candidate.supporting_evidence_ids],
            "supporting_event_ids": [str(value) for value in candidate.supporting_event_ids],
        },
    )
    return await insert_learning_event(session, LearningEventInput(
        event_id=event_id,
        type=LearningEventType.REVIEW_DUE,
        actor_id=actor_id,
        actor_subject=actor_subject,
        learner_id=state.learner_id,
        course_id=state.course_id,
        occurred_at=occurred_at,
        payload=payload,
        correlation_id=correlation_id or uuid5(
            NAMESPACE_URL, f"{idempotency_key}:correlation",
        ),
        idempotency_key=idempotency_key,
    ))


async def process_due_reviews(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    *,
    as_of: datetime,
    actor_id: UUID,
    actor_subject: str,
    active_remediation: bool = False,
) -> tuple[LearningEventRecord, ...]:
    """Emit the final maximum-three due events in the caller transaction."""

    await _lock_review_learner(session, learner_id)
    selection = await select_persisted_review_candidates(
        session,
        learner_id,
        course_id,
        as_of=as_of,
        active_remediation=active_remediation,
    )
    schedules = {
        state.stable_concept_id: state
        for state in await list_review_schedules(session, learner_id, course_id)
    }
    events: list[LearningEventRecord] = []
    # Lock acquisition uses concept UUID order, independently from review rank.
    # The returned event order still follows the selector's approved ranking.
    by_concept: dict[UUID, LearningEventRecord] = {}
    for candidate in sorted(selection.candidates, key=lambda item: item.stable_concept_id.bytes):
        schedule = schedules.get(candidate.stable_concept_id)
        if schedule is None:
            continue
        event = await emit_review_due(
            session,
            schedule,
            candidate,
            actor_id=actor_id,
            actor_subject=actor_subject,
            occurred_at=as_of,
        )
        by_concept[candidate.stable_concept_id] = event
    events.extend(by_concept[candidate.stable_concept_id] for candidate in selection.candidates
                  if candidate.stable_concept_id in by_concept)
    return tuple(events)


async def sync_review_schedules_for_replay(
    session: AsyncSession,
    replay_result: ReplayResult,
    *,
    learner_id: UUID,
    course_id: UUID,
    concept_events: Sequence[ConceptLearningEventInput],
    graph_version_id: UUID | None = None,
) -> tuple[ReviewScheduleState, ...]:
    """Materialize schedule state from one replay while heads are current."""

    events_by_concept: dict[UUID, list[ConceptLearningEventInput]] = {}
    for event in concept_events:
        for concept_id in event.stable_concept_ids:
            events_by_concept.setdefault(concept_id, []).append(event)
    for events in events_by_concept.values():
        events.sort(key=lambda event: (event.occurred_at, event.event_id.bytes))

    states: list[ReviewScheduleState] = []
    for projection in replay_result.projections:
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == learner_id,
            MasteryProjectionHead.course_id == course_id,
            MasteryProjectionHead.stable_concept_id == projection.stable_concept_id,
        ))
        revision_id = None if head is None else head.current_projection_id
        current_schedule = await session.scalar(select(ReviewSchedule).where(
            ReviewSchedule.learner_identity_id == learner_id,
            ReviewSchedule.course_id == course_id,
            ReviewSchedule.stable_concept_id == projection.stable_concept_id,
        ).with_for_update())
        event_values = events_by_concept.get(projection.stable_concept_id, [])
        first_event = event_values[0] if event_values else None
        if current_schedule is None:
            if first_event is not None:
                state = seed_initial_schedule(
                    learner_id=learner_id,
                    course_id=course_id,
                    stable_concept_id=projection.stable_concept_id,
                    graph_version_id=graph_version_id,
                    first_event_id=first_event.event_id,
                    first_event_at=first_event.occurred_at,
                    projection_revision_id=revision_id,
                    evidence_set_digest=replay_result.evidence_set_digest,
                    evidence_count=replay_result.evidence_count,
                )
            elif projection.metrics.mastery < 0.6:
                state = seed_low_mastery_schedule(
                    learner_id=learner_id,
                    course_id=course_id,
                    stable_concept_id=projection.stable_concept_id,
                    graph_version_id=graph_version_id,
                    projection_revision_id=revision_id,
                    evidence_set_digest=replay_result.evidence_set_digest,
                    evidence_count=replay_result.evidence_count,
                )
            else:
                continue
        else:
            state = _state_from_row(current_schedule)
            if (
                state.first_concept_event_id is None
                and state.last_successful_review_evidence_id is None
                and first_event is not None
            ):
                seeded = seed_initial_schedule(
                    learner_id=learner_id,
                    course_id=course_id,
                    stable_concept_id=projection.stable_concept_id,
                    graph_version_id=graph_version_id,
                    first_event_id=first_event.event_id,
                    first_event_at=first_event.occurred_at,
                    projection_revision_id=revision_id,
                    evidence_set_digest=replay_result.evidence_set_digest,
                    evidence_count=replay_result.evidence_count,
                )
                state = seeded.model_copy(update={
                    "review_rung": state.review_rung,
                    "review_successes": state.review_successes,
                })
            review_evidence_id = projection.state.last_successful_review_evidence_id
            review_changed = (
                state.last_successful_review_evidence_id
                != review_evidence_id
                and review_evidence_id is not None
            )
            if review_changed and projection.state.last_successful_review_at is not None:
                assert review_evidence_id is not None
                state = recompute_after_success(
                    state,
                    review_occurred_at=projection.state.last_successful_review_at,
                    review_evidence_id=review_evidence_id,
                    review_event_id=projection.state.last_successful_review_event_id,
                    review_rung=projection.state.review_rung,
                    review_successes=projection.state.review_successes,
                    projection_revision_id=revision_id,
                    evidence_set_digest=replay_result.evidence_set_digest,
                    evidence_count=replay_result.evidence_count,
                )
            else:
                state = refresh_projection_metadata(
                    state,
                    projection_revision_id=revision_id,
                    evidence_set_digest=replay_result.evidence_set_digest,
                    evidence_count=replay_result.evidence_count,
                    graph_version_id=graph_version_id,
                ).model_copy(update={
                    "review_rung": projection.state.review_rung,
                    "review_successes": projection.state.review_successes,
                })
        evidence_ids = tuple(sorted({
            contribution.evidence_id
            for contribution in replay_result.contributions
            if contribution.stable_concept_id == projection.stable_concept_id
        }, key=lambda value: value.bytes))
        event_ids = tuple(sorted({
            event.event_id for event in event_values
        }, key=lambda value: value.bytes))
        state = state.model_copy(update={
            "supporting_evidence_ids": evidence_ids,
            "supporting_event_ids": event_ids,
            "schedule_cycle": "0" * 64,
        })
        from packages.mastery.scheduling import schedule_cycle

        state = state.model_copy(update={"schedule_cycle": schedule_cycle(state)})
        await upsert_review_schedule(session, state)
        states.append(state)
    return tuple(states)


async def select_persisted_review_candidates(
    session: AsyncSession,
    learner_id: UUID,
    course_id: UUID,
    *,
    as_of: datetime,
    active_remediation: bool = False,
) -> ReviewSelectionResult:
    """Read schedules/projections without creating a revision or schedule."""

    schedules = await list_review_schedules(session, learner_id, course_id)
    projections: dict[UUID, ConceptMastery] = {}
    unavailable: list[ProjectionFreshnessResult] = []
    for schedule in schedules:
        current_graph = await session.scalar(select(CurriculumGraphVersion).where(
            CurriculumGraphVersion.course_id == course_id,
            CurriculumGraphVersion.status == "PUBLISHED",
        ).order_by(CurriculumGraphVersion.version_number.desc()).limit(1))
        if (
            current_graph is not None
            and schedule.graph_version_id is not None
            and schedule.graph_version_id != current_graph.id
        ):
            concept_exists = await session.scalar(select(CurriculumGraphConcept.id).where(
                CurriculumGraphConcept.graph_id == current_graph.id,
                CurriculumGraphConcept.stable_concept_id == schedule.stable_concept_id,
            ))
            unavailable.append(ProjectionFreshnessResult(
                learner_id=learner_id,
                course_id=course_id,
                stable_concept_id=schedule.stable_concept_id,
                state=ProjectionFreshness.GRAPH_CONTEXT_STALE,
                expected_graph_version_id=schedule.graph_version_id,
                observed_graph_version_id=current_graph.id,
            ))
            if concept_exists is None:
                continue
            continue
        head = await session.scalar(select(MasteryProjectionHead).where(
            MasteryProjectionHead.learner_identity_id == learner_id,
            MasteryProjectionHead.course_id == course_id,
            MasteryProjectionHead.stable_concept_id == schedule.stable_concept_id,
        ))
        if head is None:
            unavailable.append(ProjectionFreshnessResult(
                learner_id=learner_id,
                course_id=course_id,
                stable_concept_id=schedule.stable_concept_id,
                state=ProjectionFreshness.MISSING_PROJECTION,
                expected_evidence_set_digest=schedule.evidence_set_digest,
            ))
            continue
        revision = await session.get(MasteryProjectionRevision, head.current_projection_id)
        if revision is None:
            unavailable.append(ProjectionFreshnessResult(
                learner_id=learner_id,
                course_id=course_id,
                stable_concept_id=schedule.stable_concept_id,
                state=ProjectionFreshness.MISSING_REVISION,
                projection_head_id=head.id,
                expected_evidence_set_digest=schedule.evidence_set_digest,
            ))
            continue
        if (
            schedule.evidence_set_digest is not None
            and revision.evidence_set_digest != schedule.evidence_set_digest
        ):
            unavailable.append(ProjectionFreshnessResult(
                learner_id=learner_id,
                course_id=course_id,
                stable_concept_id=schedule.stable_concept_id,
                state=ProjectionFreshness.EVIDENCE_SET_STALE,
                projection_head_id=head.id,
                projection_revision_id=revision.id,
                expected_evidence_set_digest=schedule.evidence_set_digest,
                observed_evidence_set_digest=revision.evidence_set_digest,
            ))
            continue
        from packages.persistence.mastery import _projection_domain

        projections[schedule.stable_concept_id] = _projection_domain(revision)
    result = select_review_candidates(
        schedules,
        projections,
        as_of=as_of,
        active_remediation=active_remediation,
    )
    return ReviewSelectionResult(
        candidates=result.candidates,
        unavailable=tuple((*result.unavailable, *unavailable)),
    )
