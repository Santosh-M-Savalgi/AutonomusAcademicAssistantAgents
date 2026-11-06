"""Configuration-driven construction of the Phase 4.2 model gateway."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from apps.model_gateway.config import GatewayConfig
from apps.model_gateway.gateway import ModelGateway
from apps.model_gateway.llama_cpp import LlamaCppProvider
from packages.model_client.fake import FakeProvider
from packages.model_client.protocols import ModelProvider
from packages.model_client.runtime import MODEL_ID, load_model_lock


class GatewaySettings(Protocol):
    """Structural subset of the existing API Settings used by this factory."""

    aaa_profile: str
    model_provider: str
    model_base_url: str
    model_id: str
    model_artifact_path: str
    model_lock_path: str
    llama_cpp_version: str
    model_gateway_retry_max_attempts: int
    model_gateway_retry_base_delay_seconds: float
    model_gateway_retry_max_delay_seconds: float
    model_gateway_retry_jitter_seconds: float
    model_gateway_interactive_capacity: int
    model_gateway_prefetch_capacity: int
    model_gateway_batch_capacity: int
    model_gateway_timeout_seconds: float
    model_gateway_circuit_failure_threshold: int
    model_gateway_circuit_open_duration_seconds: float
    model_gateway_circuit_half_open_probe_capacity: int
    model_gateway_cache_enabled: bool
    model_gateway_cache_ttl_seconds: float
    model_gateway_telemetry_enabled: bool


def create_model_gateway(
    settings: GatewaySettings,
    *,
    fake_provider: ModelProvider | None = None,
    llama_provider: ModelProvider | None = None,
) -> ModelGateway:
    """Select fake for mock/CI and llama.cpp for explicitly selected real profiles."""

    mode = settings.model_provider
    if mode == "auto":
        mode = "fake" if settings.aaa_profile == "mock" else "llama_cpp"
    if mode == "fake":
        provider = fake_provider or FakeProvider(model_id=settings.model_id)
        return ModelGateway(
            {provider.name: provider},
            default_provider=provider.name,
            config=_gateway_config(settings),
        )
    if mode == "llama_cpp":
        lock_path = Path(settings.model_lock_path)
        artifact_sha256 = load_model_lock(lock_path).sha256 if lock_path.is_file() else None
        provider = llama_provider or LlamaCppProvider(
            base_url=settings.model_base_url,
            model_id=settings.model_id or MODEL_ID,
            artifact_filename=Path(settings.model_artifact_path).name,
            artifact_sha256=artifact_sha256,
        )
        return ModelGateway(
            {provider.name: provider},
            default_provider=provider.name,
            config=_gateway_config(settings),
        )
    raise ValueError(f"unsupported MODEL_PROVIDER: {settings.model_provider}")


def _gateway_config(settings: GatewaySettings) -> GatewayConfig:
    return GatewayConfig(
        interactive_capacity=settings.model_gateway_interactive_capacity,
        prefetch_capacity=settings.model_gateway_prefetch_capacity,
        batch_capacity=settings.model_gateway_batch_capacity,
        default_timeout_seconds=settings.model_gateway_timeout_seconds,
        retry_max_attempts=settings.model_gateway_retry_max_attempts,
        retry_base_delay_seconds=settings.model_gateway_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.model_gateway_retry_max_delay_seconds,
        retry_jitter_seconds=settings.model_gateway_retry_jitter_seconds,
        circuit_failure_threshold=settings.model_gateway_circuit_failure_threshold,
        circuit_open_duration_seconds=settings.model_gateway_circuit_open_duration_seconds,
        circuit_half_open_probe_capacity=settings.model_gateway_circuit_half_open_probe_capacity,
        cache_enabled=settings.model_gateway_cache_enabled,
        cache_ttl_seconds=settings.model_gateway_cache_ttl_seconds,
        telemetry_enabled=settings.model_gateway_telemetry_enabled,
    )
