"""Deterministic educational execution adapter for the Stage 7 runtime seam."""

import json
from uuid import UUID

from pydantic import Field

from packages.domain.enums import PlannerAction
from packages.domain.runtime import DurablePlanVersion, ExecutionIdentity, RuntimeValue


class EducationalExecutionResult(RuntimeValue):
    """A typed result containing no generated lesson, question or retrieval data."""

    execution_id: UUID
    plan_version_id: UUID
    action: PlannerAction
    target_id: str
    request_bytes: bytes
    result_bytes: bytes
    succeeded: bool = True
    adapter_version: str = Field(default="deterministic-test-v1", min_length=1, max_length=64)


class DeterministicEducationalExecutor:
    """Return stable action/result bytes without performing learner-facing work."""

    def execute(self, plan: DurablePlanVersion) -> EducationalExecutionResult:
        request = json.dumps({
            "plan_version_id": str(plan.identity.plan_version_id),
            "plan_id": str(plan.plan.plan_id),
            "session_id": str(plan.plan.session_id),
            "session_version": plan.session_version,
            "action": plan.decision.action,
            "target_id": plan.decision.target_id,
            "snapshot_digest": plan.snapshot_digest,
            "decision_digest": plan.decision_digest,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        result = json.dumps({
            "adapter": "deterministic-test-v1",
            "action": plan.decision.action,
            "target_id": plan.decision.target_id,
            "plan_version_id": str(plan.identity.plan_version_id),
            "status": "SUCCEEDED",
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return EducationalExecutionResult(
            execution_id=ExecutionIdentity(
                plan_version_id=plan.identity.plan_version_id,
            ).execution_id,
            plan_version_id=plan.identity.plan_version_id,
            action=plan.decision.action,
            target_id=plan.decision.target_id,
            request_bytes=request,
            result_bytes=result,
        )
