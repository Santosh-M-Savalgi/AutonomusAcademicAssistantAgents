"""Operational policy configuration for the in-process gateway."""

from __future__ import annotations

from dataclasses import dataclass

from packages.model_client.policies import Lane


@dataclass(frozen=True)
class GatewayConfig:
    lane_capacities: dict[Lane, int] | None = None
    interactive_capacity: int = 4
    prefetch_capacity: int = 2
    batch_capacity: int = 1
    default_timeout_seconds: float = 30.0
    retry_max_attempts: int = 2
    retry_base_delay_seconds: float = 0.05
    retry_max_delay_seconds: float = 1.0
    retry_jitter_seconds: float = 0.05
    circuit_failure_threshold: int = 3
    circuit_open_duration_seconds: float = 30.0
    circuit_half_open_probe_capacity: int = 1
    cache_enabled: bool = False
    cache_ttl_seconds: float = 60.0
    telemetry_enabled: bool = True

    def capacities(self) -> dict[Lane, int]:
        return self.lane_capacities or {
            Lane.INTERACTIVE: self.interactive_capacity,
            Lane.PREFETCH: self.prefetch_capacity,
            Lane.BATCH: self.batch_capacity,
        }
