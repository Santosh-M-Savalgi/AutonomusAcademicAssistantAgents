"""Pure Stage 8 remediation guard decisions; persistence owns all mutation."""

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from packages.domain.runtime import FrameAttempt, FrameState, RemediationFrameSnapshot, RuntimeValue


class RemediationOutcome(StrEnum):
    RETURN = "RETURN"
    CONTINUE = "CONTINUE"
    RUNG_EXHAUSTED = "RUNG_EXHAUSTED"
    BLOCKED = "BLOCKED"


REMEDIATION_ESCALATION_LADDER: tuple[str, ...] = (
    "RETEACH_WITH_NEW_STRATEGY",
    "TEACH_PREREQUISITE",
    "ASK_USER",
    "ESCALATE_MODEL",
    "BLOCKED_NEEDS_HUMAN",
)


class RemediationProgressEvaluation(RuntimeValue):
    frame_id: UUID
    source_attempt_id: UUID
    observed_mastery: float = Field(ge=0, le=1)
    baseline_mastery: float = Field(ge=0, le=1)
    progress_delta: float
    threshold: float = Field(ge=0, le=1)
    next_attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    outcome: RemediationOutcome
    next_state: FrameState
    next_rung: int = Field(ge=0)
    next_strategy: str = Field(min_length=1, max_length=64)
    next_baseline_mastery: float = Field(ge=0, le=1)
    rung_advanced: bool = False
    replayed: bool = False


class RemediationRuntimeResult(RuntimeValue):
    attempt: FrameAttempt
    frame: RemediationFrameSnapshot
    evaluation: RemediationProgressEvaluation


def evaluate_remediation_progress(
    frame: RemediationFrameSnapshot,
    attempt: FrameAttempt,
    *,
    allow_model_escalation: bool = False,
) -> RemediationProgressEvaluation:
    """Evaluate one attempt using the approved per-rung three-attempt guard."""

    if attempt.frame_id != frame.frame_id or attempt.rung != frame.rung:
        raise ValueError("Remediation attempt does not belong to the current frame rung")
    progress_delta = attempt.observed_mastery - frame.baseline_mastery
    next_count = frame.attempt_count + 1
    if progress_delta >= frame.min_progress_delta:
        return RemediationProgressEvaluation(
            frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
            observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
            progress_delta=progress_delta, threshold=frame.min_progress_delta,
            next_attempt_count=next_count, max_attempts=frame.max_attempts,
            outcome=RemediationOutcome.RETURN, next_state=FrameState.COMPLETE,
            next_rung=frame.rung, next_strategy=frame.strategy,
            next_baseline_mastery=frame.baseline_mastery,
        )
    if next_count < frame.max_attempts:
        return RemediationProgressEvaluation(
            frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
            observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
            progress_delta=progress_delta, threshold=frame.min_progress_delta,
            next_attempt_count=next_count, max_attempts=frame.max_attempts,
            outcome=RemediationOutcome.CONTINUE, next_state=FrameState.ACTIVE,
            next_rung=frame.rung, next_strategy=frame.strategy,
            next_baseline_mastery=frame.baseline_mastery,
        )

    try:
        current_index = REMEDIATION_ESCALATION_LADDER.index(frame.strategy)
    except ValueError as error:
        raise ValueError("Unknown remediation escalation strategy") from error
    if current_index >= len(REMEDIATION_ESCALATION_LADDER) - 1:
        return RemediationProgressEvaluation(
            frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
            observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
            progress_delta=progress_delta, threshold=frame.min_progress_delta,
            next_attempt_count=next_count, max_attempts=frame.max_attempts,
            outcome=RemediationOutcome.BLOCKED, next_state=FrameState.BLOCKED_NEEDS_HUMAN,
            next_rung=frame.rung, next_strategy=frame.strategy,
            next_baseline_mastery=frame.baseline_mastery,
        )
    next_index = current_index + 1
    if REMEDIATION_ESCALATION_LADDER[next_index] == "ESCALATE_MODEL" and not allow_model_escalation:
        next_index += 1
    next_strategy = REMEDIATION_ESCALATION_LADDER[next_index]
    if next_strategy == "BLOCKED_NEEDS_HUMAN":
        return RemediationProgressEvaluation(
            frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
            observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
            progress_delta=progress_delta, threshold=frame.min_progress_delta,
            next_attempt_count=next_count, max_attempts=frame.max_attempts,
            outcome=RemediationOutcome.BLOCKED, next_state=FrameState.BLOCKED_NEEDS_HUMAN,
            next_rung=frame.rung + 1, next_strategy=next_strategy,
            next_baseline_mastery=attempt.observed_mastery,
        )
    return RemediationProgressEvaluation(
        frame_id=frame.frame_id, source_attempt_id=attempt.source_attempt_id,
        observed_mastery=attempt.observed_mastery, baseline_mastery=frame.baseline_mastery,
        progress_delta=progress_delta, threshold=frame.min_progress_delta,
        next_attempt_count=0, max_attempts=frame.max_attempts,
        outcome=RemediationOutcome.RUNG_EXHAUSTED, next_state=FrameState.ACTIVE,
        next_rung=frame.rung + 1, next_strategy=next_strategy,
        next_baseline_mastery=attempt.observed_mastery, rung_advanced=True,
    )
