"""Provider-neutral gateway policy contracts."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from packages.model_client.errors import ModelClientError

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]
RandomSource = Callable[[], float]


class Lane(StrEnum):
    """Explicit gateway priority lanes."""

    INTERACTIVE = "interactive"
    PREFETCH = "prefetch"
    BATCH = "batch"


LANE_PRIORITY: Final[Mapping[Lane, int]] = {
    Lane.INTERACTIVE: 0,
    Lane.PREFETCH: 1,
    Lane.BATCH: 2,
}


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential retry with bounded additive jitter."""

    max_attempts: int = 2
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    jitter_seconds: float = 0.05
    sleeper: Sleeper = asyncio.sleep
    random_source: RandomSource = random.random

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must be non-negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be at least base_delay_seconds")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be non-negative")

    def delay_for_retry(self, retry_number: int) -> float:
        """Return a bounded delay for retry number one or greater."""

        if retry_number < 1:
            raise ValueError("retry_number must be at least one")
        exponential = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (retry_number - 1)),
        )
        sample = float(self.random_source())
        jitter = min(1.0, max(0.0, sample)) * self.jitter_seconds
        return float(min(self.max_delay_seconds, exponential + jitter))


class CircuitState(StrEnum):
    """Process-local circuit states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(ModelClientError):
    """The provider circuit is open and the provider was not contacted."""

    def __init__(self, *, provider: str | None = None) -> None:
        super().__init__(
            "Model provider circuit is open",
            code="MODEL_CIRCUIT_OPEN",
            retryable=False,
            provider=provider,
        )


class AdmissionRejectedError(ModelClientError):
    """Reserved typed category for future admission deadlines/rejections."""

    def __init__(self, *, lane: Lane) -> None:
        self.lane = lane
        super().__init__(
            f"Model request admission rejected for lane {lane.value}",
            code="MODEL_ADMISSION_REJECTED",
            retryable=False,
        )


@dataclass
class _Waiter:
    lane: Lane
    sequence: int


class AdmissionPermit:
    """Cancellation-safe permit returned by PriorityAdmission.slot()."""

    def __init__(self, admission: PriorityAdmission, lane: Lane) -> None:
        self._admission = admission
        self._lane = lane
        self._acquired = False

    async def __aenter__(self) -> AdmissionPermit:
        await self._admission._acquire(self._lane, self)
        self._acquired = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._acquired:
            await self._admission._release(self._lane)
            self._acquired = False


class PriorityAdmission:
    """A local priority-aware admission controller with per-lane caps."""

    def __init__(self, capacities: Mapping[Lane, int] | None = None) -> None:
        configured = capacities or {
            Lane.INTERACTIVE: 4,
            Lane.PREFETCH: 2,
            Lane.BATCH: 1,
        }
        self._capacities = {lane: int(configured.get(lane, 0)) for lane in Lane}
        if any(capacity < 1 for capacity in self._capacities.values()):
            raise ValueError("every gateway lane must have a positive capacity")
        self._active = dict.fromkeys(Lane, 0)
        self._waiters: list[_Waiter] = []
        self._sequence = 0
        self._condition = asyncio.Condition()

    @property
    def capacities(self) -> dict[Lane, int]:
        return dict(self._capacities)

    @property
    def active(self) -> dict[Lane, int]:
        return dict(self._active)

    def slot(self, lane: Lane) -> AdmissionPermit:
        return AdmissionPermit(self, lane)

    def _can_start(self, waiter: _Waiter) -> bool:
        if self._active[waiter.lane] >= self._capacities[waiter.lane]:
            return False
        for other in self._waiters:
            if other.sequence == waiter.sequence:
                continue
            if LANE_PRIORITY[other.lane] < LANE_PRIORITY[waiter.lane]:
                return False
            if other.lane == waiter.lane and other.sequence < waiter.sequence:
                return False
        return True

    async def _acquire(self, lane: Lane, permit: AdmissionPermit) -> None:
        del permit
        async with self._condition:
            waiter = _Waiter(lane=lane, sequence=self._sequence)
            self._sequence += 1
            self._waiters.append(waiter)
            try:
                await self._condition.wait_for(lambda: self._can_start(waiter))
                self._waiters.remove(waiter)
                self._active[lane] += 1
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                self._condition.notify_all()
                raise

    async def _release(self, lane: Lane) -> None:
        async with self._condition:
            if self._active[lane] < 1:
                raise RuntimeError("gateway admission permit released twice")
            self._active[lane] -= 1
            self._condition.notify_all()


@dataclass
class CircuitPermit:
    """One circuit call lease, including whether it was a half-open probe."""

    probe: bool
    completed: bool = False


class CircuitBreaker:
    """Deterministic process-local circuit breaker."""

    def __init__(
        self,
        *,
        provider: str,
        failure_threshold: int = 3,
        open_duration_seconds: float = 30.0,
        half_open_probe_capacity: int = 1,
        clock: Clock | None = None,
    ) -> None:
        if failure_threshold < 1 or half_open_probe_capacity < 1:
            raise ValueError("circuit thresholds and probe capacity must be positive")
        if open_duration_seconds < 0:
            raise ValueError("open_duration_seconds must be non-negative")
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.open_duration_seconds = open_duration_seconds
        self.half_open_probe_capacity = half_open_probe_capacity
        self.clock = clock or __import__("time").monotonic
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._opened_at = 0.0
        self._probes = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> CircuitPermit:
        async with self._lock:
            now = self.clock()
            if self.state == CircuitState.OPEN:
                if now - self._opened_at < self.open_duration_seconds:
                    raise CircuitOpenError(provider=self.provider)
                self.state = CircuitState.HALF_OPEN
                self._probes = 0
            if self.state == CircuitState.HALF_OPEN:
                if self._probes >= self.half_open_probe_capacity:
                    raise CircuitOpenError(provider=self.provider)
                self._probes += 1
                return CircuitPermit(probe=True)
            return CircuitPermit(probe=False)

    async def success(self, permit: CircuitPermit) -> None:
        async with self._lock:
            if permit.completed:
                return
            permit.completed = True
            if permit.probe or self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._probes = 0
            else:
                self.failure_count = 0

    async def failure(self, permit: CircuitPermit) -> None:
        async with self._lock:
            if permit.completed:
                return
            permit.completed = True
            if permit.probe or self.state == CircuitState.HALF_OPEN:
                self._open()
                return
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self._open()

    async def cancel(self, permit: CircuitPermit) -> None:
        async with self._lock:
            if permit.completed:
                return
            permit.completed = True
            if permit.probe and self._probes > 0:
                self._probes -= 1

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = self.clock()
        self._probes = 0

    async def reset(self) -> None:
        async with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self._probes = 0
            self._opened_at = 0.0
