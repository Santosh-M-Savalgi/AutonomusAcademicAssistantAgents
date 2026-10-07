"""Small async handler contract shared by durable worker jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from packages.domain.jobs import (
    ClaimedJob,
    JobErrorCode,
    JobEventPayload,
    JobEventType,
    JobPartialResultPayload,
    JobStagePayload,
)


@dataclass(frozen=True)
class HandlerResult:
    """Opaque artifact reference only, not document contents."""

    result_ref: str | None = None

    def __post_init__(self) -> None:
        if self.result_ref is not None and len(self.result_ref) > 512:
            raise ValueError("Result reference exceeds storage limit")


@dataclass
class HandlerContext:
    worker_id: str
    shutdown: asyncio.Event
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    progress: ProgressContext = field(default_factory=lambda: ProgressContext())


class JobHandler(Protocol):
    async def __call__(self, job: ClaimedJob, context: HandlerContext) -> HandlerResult: ...


class HandlerFailure(Exception):
    def __init__(self, code: JobErrorCode, *, retryable: bool = False) -> None:
        self.code = JobErrorCode(code)
        self.retryable = retryable
        super().__init__(self.code.value)


ProgressCallback = Callable[[JobEventType, JobEventPayload, str], Awaitable[bool]]


@dataclass
class ProgressContext:
    """Bounded handler-facing progress API; payloads never contain raw job data."""

    job_id: UUID | None = None
    attempt: int = 0
    callback: ProgressCallback | None = None

    async def stage_started(
        self, stage: str, *, progress_percent: int = 0, message: str | None = None,
    ) -> bool:
        return await self._send(
            JobEventType.STAGE_STARTED,
            JobStagePayload(
                stage=stage, progress_percent=progress_percent, message=message,
            ),
            f"attempt:{self.attempt}:stage:{stage}:started",
        )

    async def progress(
        self, stage: str, progress_percent: int, *, message: str | None = None,
    ) -> bool:
        return await self._send(
            JobEventType.PROGRESS_UPDATED,
            JobStagePayload(
                stage=stage, progress_percent=progress_percent, message=message,
            ),
            f"attempt:{self.attempt}:stage:{stage}:progress:{progress_percent}",
        )

    async def partial_result(self, result_kind: str) -> bool:
        return await self._send(
            JobEventType.PARTIAL_RESULT_AVAILABLE,
            JobPartialResultPayload(result_kind=result_kind),
            f"attempt:{self.attempt}:partial:{result_kind}",
        )

    async def _send(
        self, event_type: JobEventType, payload: JobEventPayload, idempotency_key: str,
    ) -> bool:
        if self.callback is None:
            return False
        return await self.callback(event_type, payload, idempotency_key)
