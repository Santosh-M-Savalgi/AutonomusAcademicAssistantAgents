"""Typed facts and results for the pure material-trigger evaluator."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from packages.domain.runtime import RuntimeValue, SourceIdentity, TriggerIdentity
from packages.domain.runtime_policy import RuntimePolicy

DEFAULT_RUNTIME_POLICY = RuntimePolicy()


class TriggerKind(StrEnum):
    SINGLE_WRONG_ANSWER = "SINGLE_WRONG_ANSWER"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    BATCH_COMPLETED = "BATCH_COMPLETED"
    STRONG_PERFORMANCE = "STRONG_PERFORMANCE"
    CURRICULUM_EDITED = "CURRICULUM_EDITED"
    NIGHTLY_DECAY = "NIGHTLY_DECAY"
    EXPLICIT_DIRECTIVE = "EXPLICIT_DIRECTIVE"
    DEADLINE_CHANGED = "DEADLINE_CHANGED"


class GuardCode(StrEnum):
    STALE_SESSION = "STALE_SESSION"
    STALE_GRAPH = "STALE_GRAPH"
    MISSING_PROJECTION = "MISSING_PROJECTION"
    MISSING_REVISION = "MISSING_REVISION"
    STALE_EVIDENCE_SET = "STALE_EVIDENCE_SET"
    MISSING_GRAPH_CONTEXT = "MISSING_GRAPH_CONTEXT"
    UNAVAILABLE_REQUIRED_STATE = "UNAVAILABLE_REQUIRED_STATE"
    ACTIVE_REMEDIATION = "ACTIVE_REMEDIATION"
    INVALID_DIRECTIVE = "INVALID_DIRECTIVE"
    EXPIRED_DIRECTIVE = "EXPIRED_DIRECTIVE"
    DUPLICATE_TRIGGER = "DUPLICATE_TRIGGER"
    COOLDOWN = "COOLDOWN"
    TERMINAL_SESSION = "TERMINAL_SESSION"
    NON_MATERIAL = "NON_MATERIAL"


class TriggerStatus(StrEnum):
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    ADMITTED = "ADMITTED"


class TriggerSubmission(RuntimeValue):
    learner_id: UUID
    session_id: UUID
    source: SourceIdentity
    source_event_id: UUID
    kind: TriggerKind
    expected_session_version: int = Field(ge=1)
    window_id: UUID | None = None
    evidence_id: UUID | None = None
    batch_id: UUID | None = None
    directive_id: UUID | None = None

    @property
    def identity(self) -> TriggerIdentity:
        return TriggerIdentity(learner_id=self.learner_id, source=self.source,
                               trigger_kind=self.kind, window_id=self.window_id)


class GradeObservation(RuntimeValue):
    evidence_id: UUID
    attempt_id: UUID
    event_id: UUID
    window_id: UUID
    concept_id: UUID
    correct: float = Field(ge=0, le=1)
    weight: float = Field(ge=0)
    direct: bool
    qualified_impact: bool
    entered_weak: bool = False
    confidence: float = Field(default=0, ge=0, le=1)


class TriggerFacts(RuntimeValue):
    submission: TriggerSubmission
    session_version: int = Field(ge=1)
    guards: tuple[GuardCode, ...] = ()
    duplicate: bool = False
    active_remediation: bool = False
    observations: tuple[GradeObservation, ...] = ()
    batch_completed: bool = False
    batch_is_quiz: bool = False
    batch_score: float | None = Field(default=None, ge=0, le=1)
    batch_item_count: int = Field(default=0, ge=0)
    gate_satisfied: bool | None = None
    review_available: bool = False
    directive_valid: bool = False
    directive_expired: bool = False
    last_plan_trigger_at: datetime | None = None


class TriggerEvaluation(RuntimeValue):
    trigger_id: UUID
    kind: TriggerKind
    status: TriggerStatus
    material: bool
    guards: tuple[GuardCode, ...] = ()
    evaluated_at: datetime
    eligible_after: datetime | None = None
    allow_advance: bool = False
    invalidate_segment: bool = False
    rebuild_graph_diff: bool = False
    recompute_pacing: bool = False


def evaluate_trigger(
    facts: TriggerFacts,
    as_of: datetime,
    policy: RuntimePolicy = DEFAULT_RUNTIME_POLICY,
) -> TriggerEvaluation:
    """Pure §6.5 trigger admission from detached facts and explicit time."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Trigger evaluation time must be timezone-aware")
    request = facts.submission
    kind = request.kind
    valid = [item for item in facts.observations if item.direct and item.qualified_impact
             and item.window_id == request.window_id]
    material = False
    strong = False
    if kind in {TriggerKind.SINGLE_WRONG_ANSWER, TriggerKind.REPEATED_FAILURE}:
        source = [item for item in valid if item.evidence_id == request.evidence_id]
        failed_concepts = {item.concept_id for item in source if item.correct == 0
                           and item.weight >= policy.failure_min_weight}
        repeated = any(len({item.attempt_id for item in valid if item.concept_id == concept
                            and item.correct == 0 and item.weight >= policy.failure_min_weight})
                       >= policy.repeated_failure_items for concept in failed_concepts)
        weak_entry = any(item.entered_weak and item.confidence >= policy.weak_entry_confidence
                         for item in source)
        material = repeated or weak_entry
        kind = TriggerKind.REPEATED_FAILURE if material else TriggerKind.SINGLE_WRONG_ANSWER
    elif kind in {TriggerKind.BATCH_COMPLETED, TriggerKind.STRONG_PERFORMANCE}:
        strong = (facts.batch_completed and facts.batch_is_quiz
                  and facts.batch_score is not None
                  and facts.batch_score >= policy.strong_quiz_score
                  and facts.batch_item_count >= policy.strong_quiz_items
                  and facts.gate_satisfied is True)
        material = facts.batch_completed if kind == TriggerKind.BATCH_COMPLETED else strong
    elif kind == TriggerKind.NIGHTLY_DECAY:
        material = facts.review_available
    elif kind == TriggerKind.EXPLICIT_DIRECTIVE:
        material = facts.directive_valid and not facts.directive_expired
    else:
        material = True

    issues = list(facts.guards)
    if request.expected_session_version != facts.session_version:
        issues.append(GuardCode.STALE_SESSION)
    if facts.duplicate:
        issues.append(GuardCode.DUPLICATE_TRIGGER)
    if request.kind == TriggerKind.EXPLICIT_DIRECTIVE:
        if facts.directive_expired:
            issues.append(GuardCode.EXPIRED_DIRECTIVE)
        elif not facts.directive_valid:
            issues.append(GuardCode.INVALID_DIRECTIVE)
    if kind == TriggerKind.NIGHTLY_DECAY and facts.active_remediation:
        issues.append(GuardCode.ACTIVE_REMEDIATION)
    guards = tuple(sorted(set(issues), key=lambda item: item.value))
    rejected = any(issue in guards for issue in (
        GuardCode.DUPLICATE_TRIGGER, GuardCode.TERMINAL_SESSION,
        GuardCode.INVALID_DIRECTIVE, GuardCode.EXPIRED_DIRECTIVE,
    ))
    status = TriggerStatus.ADMITTED
    eligible_after = None
    if rejected:
        status = TriggerStatus.REJECTED
    elif not material:
        status = TriggerStatus.EVIDENCE_ONLY
        guards = tuple((*guards, GuardCode.NON_MATERIAL))
    elif guards:
        status = TriggerStatus.BLOCKED
    elif kind != TriggerKind.EXPLICIT_DIRECTIVE and facts.last_plan_trigger_at is not None:
        deadline = facts.last_plan_trigger_at + timedelta(seconds=policy.cooldown_seconds)
        if as_of < deadline:
            status, guards, eligible_after = TriggerStatus.DEFERRED, (GuardCode.COOLDOWN,), deadline
    return TriggerEvaluation(
        trigger_id=request.identity.trigger_id, kind=kind, status=status, material=material,
        guards=guards, evaluated_at=as_of, eligible_after=eligible_after,
        allow_advance=strong, invalidate_segment=material and kind == TriggerKind.REPEATED_FAILURE,
        rebuild_graph_diff=material and kind == TriggerKind.CURRICULUM_EDITED,
        recompute_pacing=material and kind == TriggerKind.DEADLINE_CHANGED,
    )
