"""Versioned build-spec §6.4/6.5 runtime configuration, detached from I/O."""

from pydantic import Field

from packages.domain.runtime import RuntimeValue


class RuntimePolicy(RuntimeValue):
    policy_version: str = "runtime_v1"
    cooldown_seconds: int = Field(default=60, ge=1)
    repeated_failure_items: int = Field(default=2, ge=2)
    failure_min_weight: float = Field(default=0.5, ge=0, le=1)
    weak_entry_confidence: float = Field(default=0.3, ge=0, le=1)
    strong_quiz_score: float = Field(default=0.9, ge=0, le=1)
    strong_quiz_items: int = Field(default=3, ge=1)
    gate_min_mastery: float = Field(default=0.70, ge=0, le=1)
    gate_min_direct: int = Field(default=3, ge=1)
    gate_min_quiz: float = Field(default=0.6, ge=0, le=1)
