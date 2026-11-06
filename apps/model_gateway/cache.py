"""Explicitly opted-in deterministic gateway cache interfaces."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from packages.model_client.contracts import GenerationRequest


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: float) -> None: ...

    async def delete(self, key: str) -> None: ...


class CacheBackendError(RuntimeError):
    """A cache backend failure; callers should fail open to provider generation."""


@dataclass(frozen=True)
class CachePolicy:
    enabled: bool = False
    ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("cache ttl must be positive")


class InMemoryCache:
    """Test-safe cache backend with injectable time and no external service."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._values: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            self._values.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, *, ttl_seconds: float) -> None:
        self._values[key] = (self._clock() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)


def cache_key(
    request: GenerationRequest,
    *,
    provider: str,
    model_id: str,
    task_version: str | None = None,
    schema: Mapping[str, Any] | None = None,
) -> str:
    """Return a digest-only key; raw prompt/content never appears in the key."""

    material: dict[str, Any] = request.model_dump(
        mode="json",
        exclude={"correlation_id", "lane", "cacheable", "timeout_seconds"},
    )
    material["provider"] = provider
    material["model_id"] = model_id
    material["task_version"] = task_version
    if schema is not None:
        material["schema"] = schema
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"aaa:model:v1:{digest}"
