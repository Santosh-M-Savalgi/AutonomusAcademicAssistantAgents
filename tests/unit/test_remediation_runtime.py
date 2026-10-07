"""Pure Stage 8 one-rung-per-exhaustion regression coverage."""

from uuid import uuid4

import pytest

from packages.domain import (
    FrameAttempt,
    FrameState,
    RemediationFrameSnapshot,
    RemediationOutcome,
    evaluate_remediation_progress,
)
from tests.unit.test_runtime_contracts import AT


def frame(**updates: object) -> RemediationFrameSnapshot:
    return RemediationFrameSnapshot.model_validate({
        "frame_id": uuid4(), "session_id": uuid4(), "graph_version_id": uuid4(),
        "target_concept_id": uuid4(), "return_to_topic_id": uuid4(),
        "created_by_execution_id": uuid4(), "depth": 1, "state": FrameState.ACTIVE,
        "version": 1, "rung": 0, "strategy": "RETEACH_WITH_NEW_STRATEGY",
        "guard_policy_version": "guard_v1", "attempt_count": 2, "max_attempts": 3,
        "min_progress_delta": 0.05, "baseline_mastery": 0.2, "latest_mastery": 0.2,
        "last_event_id": uuid4(), **updates,
    })


def attempt(value: float, *, frame_id, rung: int = 0) -> FrameAttempt:
    return FrameAttempt(
        frame_id=frame_id, source_attempt_id=uuid4(), event_id=uuid4(), rung=rung,
        observed_mastery=value, occurred_at=AT,
    )


def test_third_failed_attempt_exhausts_only_current_rung_with_fresh_next_budget() -> None:
    original = frame()
    result = evaluate_remediation_progress(original, attempt(0.21, frame_id=original.frame_id))
    assert result.outcome == RemediationOutcome.RUNG_EXHAUSTED
    assert result.next_rung == 1
    assert result.next_strategy == "TEACH_PREREQUISITE"
    assert result.next_attempt_count == 0
    assert result.next_baseline_mastery == pytest.approx(0.21)
    assert result.next_state == FrameState.ACTIVE


def test_nonterminal_rung_does_not_emit_blocked_state() -> None:
    original = frame()
    result = evaluate_remediation_progress(original, attempt(0.21, frame_id=original.frame_id))
    assert result.outcome != RemediationOutcome.BLOCKED
    assert result.next_state != FrameState.BLOCKED_NEEDS_HUMAN
    assert not result.rung_advanced or result.outcome == RemediationOutcome.RUNG_EXHAUSTED


def test_retry_of_third_failed_attempt_does_not_advance_rung_twice() -> None:
    original = frame()
    failed = attempt(0.21, frame_id=original.frame_id)
    first = evaluate_remediation_progress(original, failed)
    advanced = original.model_copy(update={
        "rung": first.next_rung, "strategy": first.next_strategy,
        "attempt_count": first.next_attempt_count,
        "baseline_mastery": first.next_baseline_mastery,
        "latest_mastery": failed.observed_mastery,
    })
    assert first.next_rung == 1
    assert advanced.attempt_count == 0
    assert advanced.rung == 1
    replay = evaluate_remediation_progress(original, failed)
    assert replay == first
    assert replay.rung_advanced is True


def test_each_prior_attempt_remains_an_immutable_distinct_source_record() -> None:
    original = frame(attempt_count=0)
    first_attempt = attempt(0.2, frame_id=original.frame_id)
    first = evaluate_remediation_progress(original, first_attempt)
    second_frame = original.model_copy(update={
        "attempt_count": first.next_attempt_count,
        "latest_mastery": first_attempt.observed_mastery,
    })
    second_attempt = attempt(0.21, frame_id=original.frame_id)
    second = evaluate_remediation_progress(second_frame, second_attempt)
    assert first_attempt.source_attempt_id != second_attempt.source_attempt_id
    assert first_attempt.observed_mastery == 0.2
    assert second_attempt.observed_mastery == 0.21
    assert second.next_rung == original.rung


def test_successful_progress_is_not_rung_exhaustion() -> None:
    original = frame()
    result = evaluate_remediation_progress(original, attempt(0.26, frame_id=original.frame_id))
    assert result.outcome == RemediationOutcome.RETURN
    assert result.rung_advanced is False
    assert result.next_rung == original.rung


def test_terminal_ladder_exhaustion_blocks_only_at_terminal_strategy() -> None:
    terminal = frame(
        rung=4, strategy="BLOCKED_NEEDS_HUMAN", attempt_count=2,
    )
    result = evaluate_remediation_progress(
        terminal, attempt(0.21, frame_id=terminal.frame_id, rung=4),
    )
    assert result.outcome == RemediationOutcome.BLOCKED
    assert result.next_state == FrameState.BLOCKED_NEEDS_HUMAN
    assert result.next_rung == 4
    assert result.rung_advanced is False


def test_escalation_ladder_advances_exactly_one_applicable_step() -> None:
    original = frame(strategy="TEACH_PREREQUISITE", rung=1)
    result = evaluate_remediation_progress(
        original, attempt(0.21, frame_id=original.frame_id, rung=1),
    )
    assert result.rung_advanced is True
    assert result.next_rung == original.rung + 1
    assert result.next_strategy == "ASK_USER"


def test_model_escalation_is_skipped_without_authorization() -> None:
    original = frame(strategy="ASK_USER", rung=2)
    result = evaluate_remediation_progress(
        original, attempt(0.21, frame_id=original.frame_id, rung=2),
    )
    assert result.next_rung == 3
    assert result.next_strategy == "BLOCKED_NEEDS_HUMAN"
    assert result.outcome == RemediationOutcome.BLOCKED
