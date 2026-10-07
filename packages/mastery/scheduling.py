"""Pure Sprint 3.5 spaced-review scheduling and candidate selection."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from packages.domain.adaptation import (
    ProjectionFreshness,
    ProjectionFreshnessResult,
    ReviewCandidate,
    ReviewDueReason,
    ReviewScheduleState,
    ReviewSelectionResult,
)
from packages.domain.mastery import ConceptMastery
from packages.mastery.engine import REVIEW_LADDER_DAYS, decay_state, metrics_for

REVIEW_THRESHOLD_DEFAULT = 0.6
REVIEW_POLICY_VERSION = "review_diagnostic_v1"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Schedule timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _uuid_hex(value: UUID | None) -> str:
    return "0" * 32 if value is None else value.hex


def schedule_cycle_material(state: ReviewScheduleState) -> str:
    """Return the exact canonical schedule-cycle material from policy F."""

    due_at = "-" if state.due_at is None else _utc(state.due_at).isoformat(
        timespec="microseconds",
    )
    return "|".join((
        "review-schedule-cycle:v1",
        f"learner={state.learner_id.hex}",
        f"course={state.course_id.hex}",
        f"concept={state.stable_concept_id.hex}",
        f"graph={_uuid_hex(state.graph_version_id)}",
        f"policy={state.review_policy_version}",
        f"anchor_evidence={_uuid_hex(state.last_successful_review_evidence_id)}",
        f"anchor_event={_uuid_hex(
            state.last_successful_review_event_id or state.first_concept_event_id
        )}",
        f"rung={state.review_rung}",
        f"due_at={due_at}",
        f"evidence_set={state.evidence_set_digest or ''}",
    ))


def schedule_cycle(state: ReviewScheduleState) -> str:
    """Hash canonical immutable schedule inputs."""

    return sha256(schedule_cycle_material(state).encode("utf-8")).hexdigest()


def review_due_idempotency_key(state: ReviewScheduleState) -> str:
    """Return the stable durable REVIEW_DUE idempotency key."""

    return ":".join((
        "review-due:v1",
        state.learner_id.hex,
        state.course_id.hex,
        state.stable_concept_id.hex,
        schedule_cycle(state),
        state.review_policy_version,
    ))


def seed_initial_schedule(
    *,
    learner_id: UUID,
    course_id: UUID,
    stable_concept_id: UUID,
    graph_version_id: UUID | None,
    first_event_id: UUID,
    first_event_at: datetime,
    review_policy_version: str = REVIEW_POLICY_VERSION,
    projection_revision_id: UUID | None = None,
    evidence_set_digest: str | None = None,
    evidence_count: int = 0,
) -> ReviewScheduleState:
    """Seed rung zero from the first qualifying concept-impact event."""

    first_at = _utc(first_event_at)
    due_at = first_at + timedelta(days=REVIEW_LADDER_DAYS[0])
    state = ReviewScheduleState(
        learner_id=learner_id,
        course_id=course_id,
        stable_concept_id=stable_concept_id,
        graph_version_id=graph_version_id,
        review_policy_version=review_policy_version,
        review_rung=0,
        review_successes=0,
        first_concept_event_id=first_event_id,
        first_concept_event_at=first_at,
        due_at=due_at,
        projection_revision_id=projection_revision_id,
        evidence_set_digest=evidence_set_digest,
        evidence_count=evidence_count,
        schedule_cycle="0" * 64,
    )
    return state.model_copy(update={"schedule_cycle": schedule_cycle(state)})


def seed_low_mastery_schedule(
    *,
    learner_id: UUID,
    course_id: UUID,
    stable_concept_id: UUID,
    graph_version_id: UUID | None,
    review_policy_version: str = REVIEW_POLICY_VERSION,
    projection_revision_id: UUID | None = None,
    evidence_set_digest: str | None = None,
    evidence_count: int = 0,
) -> ReviewScheduleState:
    """Create a low-mastery schedule when no qualifying event exists."""

    state = ReviewScheduleState(
        learner_id=learner_id,
        course_id=course_id,
        stable_concept_id=stable_concept_id,
        graph_version_id=graph_version_id,
        review_policy_version=review_policy_version,
        review_rung=0,
        review_successes=0,
        projection_revision_id=projection_revision_id,
        evidence_set_digest=evidence_set_digest,
        evidence_count=evidence_count,
        schedule_cycle="0" * 64,
    )
    return state.model_copy(update={"schedule_cycle": schedule_cycle(state)})


def recompute_after_success(
    state: ReviewScheduleState,
    *,
    review_occurred_at: datetime,
    review_evidence_id: UUID,
    review_event_id: UUID | None,
    review_rung: int,
    review_successes: int,
    projection_revision_id: UUID | None,
    evidence_set_digest: str | None,
    evidence_count: int,
) -> ReviewScheduleState:
    """Recompute a schedule using the mastery engine's post-transition rung."""

    occurred_at = _utc(review_occurred_at)
    next_due = occurred_at + timedelta(days=REVIEW_LADDER_DAYS[review_rung])
    updated = state.model_copy(update={
        "review_rung": review_rung,
        "review_successes": review_successes,
        "last_successful_review_at": occurred_at,
        "last_successful_review_evidence_id": review_evidence_id,
        "last_successful_review_event_id": review_event_id,
        "due_at": next_due,
        "projection_revision_id": projection_revision_id,
        "evidence_set_digest": evidence_set_digest,
        "evidence_count": evidence_count,
        "schedule_cycle": "0" * 64,
    })
    return updated.model_copy(update={"schedule_cycle": schedule_cycle(updated)})


def refresh_projection_metadata(
    state: ReviewScheduleState,
    *,
    projection_revision_id: UUID | None,
    evidence_set_digest: str | None,
    evidence_count: int,
    graph_version_id: UUID | None = None,
) -> ReviewScheduleState:
    """Refresh materialized projection provenance without changing rung state."""

    updated = state.model_copy(update={
        "projection_revision_id": projection_revision_id,
        "evidence_set_digest": evidence_set_digest,
        "evidence_count": evidence_count,
        "graph_version_id": graph_version_id or state.graph_version_id,
        "schedule_cycle": "0" * 64,
    })
    return updated.model_copy(update={"schedule_cycle": schedule_cycle(updated)})


def select_review_candidates(
    schedules: Sequence[ReviewScheduleState],
    projections: Mapping[UUID, ConceptMastery],
    *,
    as_of: datetime,
    active_remediation: bool = False,
    review_threshold: float = REVIEW_THRESHOLD_DEFAULT,
    maximum: int = 3,
) -> ReviewSelectionResult:
    """Select a deterministic, duplicate-free review warm-up."""

    if maximum < 0:
        raise ValueError("Maximum review candidates cannot be negative")
    as_of_utc = _utc(as_of)
    if active_remediation or maximum == 0:
        return ReviewSelectionResult()

    unique_schedules: dict[UUID, ReviewScheduleState] = {}
    unavailable: list[ProjectionFreshnessResult] = []
    candidates: list[ReviewCandidate] = []
    for schedule in schedules:
        if schedule.stable_concept_id in unique_schedules:
            continue
        unique_schedules[schedule.stable_concept_id] = schedule
        projection = projections.get(schedule.stable_concept_id)
        if projection is None:
            unavailable.append(ProjectionFreshnessResult(
                learner_id=schedule.learner_id,
                course_id=schedule.course_id,
                stable_concept_id=schedule.stable_concept_id,
                state=ProjectionFreshness.MISSING_PROJECTION,
                projection_revision_id=schedule.projection_revision_id,
                expected_evidence_set_digest=schedule.evidence_set_digest,
            ))
            continue
        projected_state = decay_state(projection.state, as_of_utc)
        metrics = metrics_for(projected_state, projected_state.review_successes > 0)
        low = metrics.mastery < review_threshold
        overdue = schedule.due_at is not None and schedule.due_at <= as_of_utc
        if not low and not overdue:
            continue
        reasons = tuple(
            reason for reason, condition in (
                (ReviewDueReason.MASTERY_BELOW_THRESHOLD, low),
                (ReviewDueReason.REVIEW_OVERDUE, overdue),
            ) if condition
        )
        candidates.append(ReviewCandidate(
            learner_id=schedule.learner_id,
            course_id=schedule.course_id,
            stable_concept_id=schedule.stable_concept_id,
            reasons=reasons,
            due_at=schedule.due_at,
            decayed_mastery=metrics.mastery,
            confidence=metrics.confidence,
            mastery_status=metrics.status,
            review_successes=projected_state.review_successes,
            review_rung=projected_state.review_rung,
            projection_revision_id=schedule.projection_revision_id,
            evidence_set_digest=schedule.evidence_set_digest,
            graph_version_id=schedule.graph_version_id,
            review_policy_version=schedule.review_policy_version,
            schedule_cycle=schedule.schedule_cycle,
            supporting_evidence_ids=schedule.supporting_evidence_ids,
            supporting_event_ids=schedule.supporting_event_ids,
        ))

    def sort_key(candidate: ReviewCandidate) -> tuple[object, ...]:
        overdue = ReviewDueReason.REVIEW_OVERDUE in candidate.reasons
        due = candidate.due_at or datetime.max.replace(tzinfo=UTC)
        return (
            0 if overdue else 1,
            due if overdue else datetime.max.replace(tzinfo=UTC),
            candidate.decayed_mastery,
            candidate.stable_concept_id.bytes,
        )

    candidates.sort(key=sort_key)
    return ReviewSelectionResult(
        candidates=tuple(candidates[:maximum]),
        unavailable=tuple(unavailable),
    )
