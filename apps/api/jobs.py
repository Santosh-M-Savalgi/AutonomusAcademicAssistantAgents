"""Authenticated durable job snapshots and PostgreSQL-backed SSE replay."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from apps.api.auth.dependencies import get_current_identity
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.runtime import RuntimeResources
from packages.domain.enums import JobStatus
from packages.persistence.job_events import events_after, job_course_id, job_snapshot
from packages.persistence.job_wakeups import wait_for_job_events
from packages.persistence.repositories import find_course_member

router = APIRouter(prefix="/api/v3/jobs", tags=["jobs"])
_TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


async def _authorized_snapshot(
    request: Request, job_id: UUID, identity: AuthenticatedIdentity,
):
    resources: RuntimeResources = request.app.state.runtime
    snapshot = await job_snapshot(resources.database, job_id)
    course_id = await job_course_id(resources.database, job_id)
    if snapshot is None or course_id is None:
        raise HTTPException(status_code=404, detail={
            "code": "JOB_NOT_FOUND", "message": "No such job exists.",
        })
    async with resources.database.session() as session:
        member = await find_course_member(session, course_id, identity.subject)
    if member is None:
        raise HTTPException(status_code=403, detail={
            "code": "JOB_FORBIDDEN", "message": "Course membership is required.",
        })
    return snapshot


def _cursor(raw: str | None, latest: int) -> int:
    if raw is None:
        return 0
    try:
        value = int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_EVENT_CURSOR", "message": "Last-Event-ID must be a number.",
        }) from None
    if value < 0:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_EVENT_CURSOR", "message": "Last-Event-ID must not be negative.",
        })
    # A future cursor is safe to clamp: there is no known event to replay yet.
    return min(value, latest)


def _sse_frame(event) -> str:
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.type.value}\ndata: {data}\n\n"


@router.get("/{job_id}")
async def read_job_snapshot(
    job_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
):
    return await _authorized_snapshot(request, job_id, identity)


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: UUID, request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    snapshot = await _authorized_snapshot(request, job_id, identity)
    cursor = _cursor(last_event_id, snapshot.latest_event_sequence)
    resources: RuntimeResources = request.app.state.runtime

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                return
            events = await events_after(resources.database, job_id, cursor)
            if events:
                for event in events:
                    if await request.is_disconnected():
                        return
                    cursor = event.sequence
                    yield _sse_frame(event)
                continue
            current = await job_snapshot(resources.database, job_id)
            if current is None:
                return
            if current.latest_event_sequence > cursor:
                continue
            if current.status in _TERMINAL:
                return
            yield ": keepalive\n\n"
            notified = await wait_for_job_events(resources.redis, job_id, timeout=1)
            if not notified:
                # PostgreSQL polling remains authoritative when Redis is unavailable.
                await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })
