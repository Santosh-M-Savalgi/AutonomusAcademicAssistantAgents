"""Pure Block B contracts and deterministic execution adapter coverage."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain import (
    DeterministicEducationalExecutor,
    ExecutionIdentity,
    ExecutionReceipt,
    ExecutionState,
    SessionState,
    SessionTransition,
)
from tests.unit.test_runtime_contracts import AT, plan_contract


def test_deterministic_executor_replays_identical_request_and_result() -> None:
    plan = plan_contract()
    executor = DeterministicEducationalExecutor()
    first = executor.execute(plan)
    second = executor.execute(plan)
    assert first == second
    assert first.execution_id == ExecutionIdentity(
        plan_version_id=plan.identity.plan_version_id,
    ).execution_id
    assert b"lesson" not in first.result_bytes
    assert b"question" not in first.result_bytes


def test_receipt_retains_request_result_and_fingerprint_material() -> None:
    plan = plan_contract()
    result = DeterministicEducationalExecutor().execute(plan)
    receipt = ExecutionReceipt(
        identity=ExecutionIdentity(plan_version_id=plan.identity.plan_version_id),
        plan=plan, state=ExecutionState.COMPLETED, version=1,
        request_bytes=result.request_bytes, result_bytes=result.result_bytes,
        created_at=AT, completed_at=AT,
    )
    assert receipt.request_digest is not None
    assert receipt.result_digest is not None
    assert receipt.receipt_fingerprint
    with pytest.raises(ValidationError, match="request digest"):
        ExecutionReceipt.model_validate({
            **receipt.model_dump(), "request_digest": "0" * 64,
        })


def test_execution_transition_requires_both_plan_and_execution_identity() -> None:
    with pytest.raises(ValidationError, match="execution-linked"):
        SessionTransition(
            session_id=uuid4(), event_id=uuid4(), from_state=SessionState.PLANNING,
            to_state=SessionState.TEACHING, from_version=1, to_version=2, occurred_at=AT,
            execution_id=uuid4(),
        )
