"""Pure Beta mastery calculations, review transitions and status rules."""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from packages.domain.adaptation import SelfReportPriorContribution
from packages.domain.events import ConceptLearningEventInput
from packages.domain.mastery import (
    ConceptMastery,
    EvidenceContribution,
    EvidenceInput,
    MasteryMetrics,
    MasteryState,
    MasteryStatus,
    ReplayResult,
)
from packages.mastery.weights import calculate_weight_snapshot

PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
REVIEW_LADDER_DAYS = (1, 3, 7, 14, 30, 60)
REVIEW_DELAY = timedelta(hours=24)


def initial_state() -> MasteryState:
    return MasteryState(alpha=PRIOR_ALPHA, beta=PRIOR_BETA)


def effective_sample_size(state: MasteryState) -> float:
    return max(0.0, state.alpha + state.beta - 2.0)


def mastery_value(state: MasteryState) -> float:
    denominator = state.alpha + state.beta
    if denominator <= 0:
        raise ValueError("Beta posterior denominator must be positive")
    return state.alpha / denominator


def confidence_value(state: MasteryState) -> float:
    n_eff = effective_sample_size(state)
    return n_eff / (n_eff + 4.0)


def classify_status(
    state: MasteryState, has_qualifying_review: bool | None = None,
) -> MasteryStatus:
    if has_qualifying_review is None:
        has_qualifying_review = state.has_qualifying_review
    n_eff = effective_sample_size(state)
    mastery = mastery_value(state)
    confidence = confidence_value(state)
    if n_eff < 1.0:
        return "UNASSESSED"
    if mastery < 0.5 and confidence >= 0.3:
        return "WEAK"
    proficient = (
        mastery >= 0.75
        and state.n_direct >= 3
        and len(state.distinct_direct_question_ids) >= 2
        and confidence >= 0.5
    )
    if proficient and has_qualifying_review:
        return "MASTERED"
    if proficient:
        return "PROFICIENT"
    return "DEVELOPING"


def metrics_for(
    state: MasteryState, has_qualifying_review: bool | None = None,
) -> MasteryMetrics:
    return MasteryMetrics(
        n_eff=effective_sample_size(state),
        mastery=mastery_value(state),
        confidence=confidence_value(state),
        status=classify_status(state, has_qualifying_review),
    )


def forgetting_half_life(review_successes: int) -> float:
    if review_successes < 0:
        raise ValueError("Review successes cannot be negative")
    return min(180.0, 21.0 * math.pow(1.6, review_successes))


def decay_state(state: MasteryState, at: datetime) -> MasteryState:
    """Decay a state to an explicit UTC time without reading a clock."""

    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Decay time must be timezone-aware")
    at_utc = at.astimezone(UTC)
    if state.last_occurred_at is None:
        return state
    if at_utc < state.last_occurred_at:
        raise ValueError("Mastery state cannot be decayed backwards")
    dt_days = (at_utc - state.last_occurred_at).total_seconds() / 86400.0
    if dt_days == 0:
        return state
    half_life = forgetting_half_life(state.review_successes)
    factor = math.pow(2.0, -dt_days / half_life)
    return state.model_copy(
        update={
            "alpha": PRIOR_ALPHA + (state.alpha - PRIOR_ALPHA) * factor,
            "beta": PRIOR_BETA + (state.beta - PRIOR_BETA) * factor,
            "last_occurred_at": at_utc,
        }
    )


def _role_weight(role: str) -> float:
    if role == "PRIMARY":
        return 1.0
    if role == "PREREQUISITE":
        return 0.5
    raise ValueError(f"Unsupported concept role: {role}")


@dataclass(frozen=True)
class EvidenceApplication:
    states: dict[UUID, MasteryState]
    contributions: tuple[EvidenceContribution, ...]
    qualifying_review_concepts: frozenset[UUID]


def apply_evidence(
    states: Mapping[UUID, MasteryState],
    evidence: EvidenceInput,
    previous_learning_at: Mapping[UUID, datetime | None] | None = None,
    review_event_ids: Mapping[UUID, UUID | None] | None = None,
) -> EvidenceApplication:
    """Apply one immutable evidence item to all of its co-tagged concepts."""

    previous_learning_at = previous_learning_at or {}
    review_event_ids = review_event_ids or {}
    weight = calculate_weight_snapshot(evidence)
    concept_ids = [snapshot.stable_concept_id for snapshot in evidence.concept_roles]
    decayed = {
        concept_id: decay_state(states.get(concept_id, initial_state()), evidence.occurred_at)
        for concept_id in concept_ids
    }

    if evidence.kind == "INFERRED" and evidence.correct < 1.0:
        return EvidenceApplication(
            states=dict(states),
            contributions=tuple(
                EvidenceContribution(
                    evidence_id=evidence.evidence_id,
                    stable_concept_id=concept_id,
                    alpha_delta=0.0,
                    beta_delta=0.0,
                    applied=False,
                    reason="INFERRED_PARTIAL_OR_INCORRECT_AUDIT_ONLY",
                )
                for concept_id in concept_ids
            ),
            qualifying_review_concepts=frozenset(),
        )

    positive_mass = (
        0.3 * weight.w_correct
        if evidence.kind == "INFERRED"
        else evidence.correct * weight.w_correct
    )
    negative_mass = (
        0.0
        if evidence.kind == "INFERRED"
        else (1.0 - evidence.correct) * weight.w_incorrect
    )
    mastery_by_concept = {concept_id: mastery_value(state) for concept_id, state in decayed.items()}
    role_by_concept = {
        snapshot.stable_concept_id: _role_weight(snapshot.role)
        for snapshot in evidence.concept_roles
    }
    denominator = sum(
        role_by_concept[concept_id] * (1.0 - mastery_by_concept[concept_id])
        for concept_id in concept_ids
    )
    role_denominator = sum(role_by_concept.values())
    if role_denominator <= 0:
        raise ValueError("Evidence must contain a positive concept-role denominator")
    if negative_mass > 0 and denominator <= 0:
        shares = {
            concept_id: negative_mass * role_by_concept[concept_id] / role_denominator
            for concept_id in concept_ids
        }
    else:
        shares = {
            concept_id: (
                negative_mass
                * role_by_concept[concept_id]
                * (1.0 - mastery_by_concept[concept_id])
                / denominator
                if negative_mass > 0
                else 0.0
            )
            for concept_id in concept_ids
        }

    qualifying: set[UUID] = set()
    updated: dict[UUID, MasteryState] = dict(states)
    contributions: list[EvidenceContribution] = []
    for concept_id in concept_ids:
        state = decayed[concept_id]
        review_success = False
        review_failure = False
        previous = previous_learning_at.get(concept_id)
        if evidence.kind == "DIRECT" and evidence.is_review:
            if evidence.correct == 1.0 and previous is not None:
                review_success = evidence.occurred_at - previous >= REVIEW_DELAY
            elif evidence.correct < 1.0:
                review_failure = True
        alpha_delta = positive_mass * role_by_concept[concept_id]
        beta_delta = shares[concept_id]
        direct_count = state.n_direct + (1 if evidence.kind == "DIRECT" else 0)
        question_ids = state.distinct_direct_question_ids
        if evidence.kind == "DIRECT" and evidence.question_id not in question_ids:
            question_ids = tuple(
                sorted((*question_ids, evidence.question_id), key=lambda value: value.bytes)
            )
        review_successes = state.review_successes + (1 if review_success else 0)
        review_rung = state.review_rung
        if review_success:
            review_rung = min(review_rung + 1, 5)
            qualifying.add(concept_id)
        elif review_failure:
            review_rung = 0
        updated[concept_id] = MasteryState(
            alpha=state.alpha + alpha_delta,
            beta=state.beta + beta_delta,
            n_direct=direct_count,
            distinct_direct_question_ids=question_ids,
            review_successes=review_successes,
            review_rung=review_rung,
            has_qualifying_review=state.has_qualifying_review or review_success,
            self_report_prior_applied=state.self_report_prior_applied,
            last_occurred_at=evidence.occurred_at,
            last_successful_review_at=(
                evidence.occurred_at if review_success else state.last_successful_review_at
            ),
            last_successful_review_evidence_id=(
                evidence.evidence_id
                if review_success else state.last_successful_review_evidence_id
            ),
            last_successful_review_event_id=(
                review_event_ids.get(concept_id)
                if review_success else state.last_successful_review_event_id
            ),
        )
        contributions.append(
            EvidenceContribution(
                evidence_id=evidence.evidence_id,
                stable_concept_id=concept_id,
                alpha_delta=alpha_delta,
                beta_delta=beta_delta,
                applied=True,
            )
        )
    return EvidenceApplication(updated, tuple(contributions), frozenset(qualifying))


def apply_self_report_priors(
    states: Mapping[UUID, MasteryState],
    priors: Sequence[SelfReportPriorContribution],
) -> dict[UUID, MasteryState]:
    """Apply each immutable self-report prior once from the Beta prior."""

    updated = dict(states)
    seen_concepts: set[UUID] = set()
    for prior in sorted(priors, key=lambda item: item.assertion_id.bytes):
        if prior.stable_concept_id in seen_concepts:
            raise ValueError("A learner/course/concept may have only one self-report prior")
        seen_concepts.add(prior.stable_concept_id)
        state = updated.get(prior.stable_concept_id, initial_state())
        if state.self_report_prior_applied:
            continue
        updated[prior.stable_concept_id] = state.model_copy(update={
            "alpha": state.alpha + prior.alpha_delta,
            "beta": state.beta + prior.beta_delta,
            "self_report_prior_applied": True,
        })
    return updated


def _event_matches_evidence(
    event: ConceptLearningEventInput, evidence: EvidenceInput,
) -> bool:
    return (
        event.source_evidence_id == evidence.evidence_id
        or event.source_attempt_id == evidence.attempt_id
    )


def _previous_event_time(
    events: Sequence[ConceptLearningEventInput],
    concept_id: UUID,
    at: datetime,
    evidence: EvidenceInput,
) -> datetime | None:
    previous = sorted(
        (
            event.occurred_at
            for event in events
            if concept_id in event.stable_concept_ids
            and event.occurred_at < at
            and not _event_matches_evidence(event, evidence)
        ),
    )
    return previous[-1] if previous else None


def _event_for_evidence(
    events: Sequence[ConceptLearningEventInput], evidence: EvidenceInput,
) -> UUID | None:
    matches = sorted(
        (
            event.event_id for event in events
            if _event_matches_evidence(event, evidence)
        ),
        key=lambda value: value.bytes,
    )
    return matches[0] if matches else None


def _digest(
    evidence: Sequence[EvidenceInput],
    priors: Sequence[SelfReportPriorContribution],
) -> str:
    immutable_fields = set(EvidenceInput.model_fields)
    ordered = sorted(evidence, key=lambda item: item.evidence_id.bytes)
    payload = {
        "evidence": [
            item.model_dump(mode="json", include=immutable_fields)
            for item in ordered
        ],
        "self_report_priors": [
            item.model_dump(mode="json")
            for item in sorted(priors, key=lambda value: value.assertion_id.bytes)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def replay(
    evidence: Sequence[EvidenceInput],
    as_of: datetime,
    events: Sequence[ConceptLearningEventInput] = (),
    self_report_priors: Sequence[SelfReportPriorContribution] = (),
) -> ReplayResult:
    """Replay a learner history deterministically at one explicit projection time."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Replay projection time must be timezone-aware")
    unique: dict[UUID, EvidenceInput] = {}
    for item in evidence:
        existing_evidence = unique.get(item.evidence_id)
        if existing_evidence is not None and existing_evidence != item:
            raise ValueError("Conflicting duplicate evidence ID")
        unique[item.evidence_id] = item
    unique_priors: dict[UUID, SelfReportPriorContribution] = {}
    for prior in self_report_priors:
        previous_prior = unique_priors.get(prior.assertion_id)
        if previous_prior is not None and previous_prior != prior:
            raise ValueError("Conflicting duplicate self-report assertion ID")
        unique_priors[prior.assertion_id] = prior
    prior_values = tuple(unique_priors.values())
    ordered = sorted(unique.values(), key=lambda item: (item.occurred_at, item.evidence_id.bytes))
    states = apply_self_report_priors({}, prior_values)
    contributions: list[EvidenceContribution] = []
    for item in ordered:
        previous = {
            concept_id: _previous_event_time(events, concept_id, item.occurred_at, item)
            for concept_id in (snapshot.stable_concept_id for snapshot in item.concept_roles)
        }
        current_event_id = _event_for_evidence(events, item)
        application = apply_evidence(
            states,
            item,
            previous,
            {
                snapshot.stable_concept_id: current_event_id
                for snapshot in item.concept_roles
            },
        )
        states = application.states
        contributions.extend(application.contributions)
    as_of_utc = as_of.astimezone(UTC)
    projected: list[ConceptMastery] = []
    for concept_id in sorted(states, key=lambda value: value.bytes):
        state = decay_state(states[concept_id], as_of_utc)
        projected.append(
            ConceptMastery(
                stable_concept_id=concept_id,
                state=state,
                metrics=metrics_for(state, state.review_successes > 0),
            )
        )
    max_item = ordered[-1] if ordered else None
    return ReplayResult(
        projections=tuple(projected),
        contributions=tuple(contributions),
        evidence_set_digest=_digest(ordered, prior_values),
        evidence_count=len(ordered),
        max_occurred_at=None if max_item is None else max_item.occurred_at,
        max_evidence_id=None if max_item is None else max_item.evidence_id,
        as_of=as_of_utc,
        self_report_prior_count=len(prior_values),
    )
