"""Best-effort, content-free gateway telemetry."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from packages.model_client.contracts import UsageStats
from packages.model_client.policies import CircuitState, Lane


class GatewayTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str | None = None
    task: str = Field(min_length=1)
    task_version: str | None = None
    lane: Lane
    provider: str
    model_id: str
    success: bool
    error_category: str | None = None
    latency_ms: float = Field(ge=0)
    retry_count: int = Field(ge=0)
    cache_status: str
    circuit_state: CircuitState
    circuit_result: str
    usage: UsageStats | None = None


class TelemetrySink(Protocol):
    def record(self, event: GatewayTelemetryEvent) -> None | Awaitable[None]: ...


class NullTelemetrySink:
    def record(self, event: GatewayTelemetryEvent) -> None:
        del event


class InMemoryTelemetry:
    """Deterministic test sink."""

    def __init__(self) -> None:
        self.events: list[GatewayTelemetryEvent] = []

    def record(self, event: GatewayTelemetryEvent) -> None:
        self.events.append(event)


async def record_best_effort(sink: TelemetrySink, event: GatewayTelemetryEvent) -> None:
    """Telemetry failures never change generation behavior."""

    try:
        result = sink.record(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return
