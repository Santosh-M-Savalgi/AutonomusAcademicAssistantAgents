"""Deterministic local-runtime checks for the real-model evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from apps.api.config import Settings
from packages.evalkit.contracts import RuntimePreflightReport
from packages.model_client.runtime import load_model_lock


class EvaluationRuntimeError(RuntimeError):
    """The real-model evaluation cannot run against the configured runtime."""


class ServerMetricsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens_total: float | None = None
    predicted_tokens_total: float | None = None
    prompt_seconds_total: float | None = None
    predicted_seconds_total: float | None = None


@dataclass(frozen=True)
class PreflightResult:
    report: RuntimePreflightReport
    metrics: ServerMetricsSnapshot | None


def effective_provider(settings: Settings) -> str:
    if settings.model_provider == "auto":
        return "fake" if settings.aaa_profile == "mock" else "llama_cpp"
    return settings.model_provider


async def run_preflight(settings: Settings) -> PreflightResult:
    provider = effective_provider(settings)
    artifact_path = Path(settings.model_artifact_path)
    lock_path = Path(settings.model_lock_path)
    artifact_sha256 = ""
    artifact_verified = False
    health_ok = False
    models_ok = False
    identity_consistent = False
    returned_model_ids: list[str] = []
    metrics: ServerMetricsSnapshot | None = None

    try:
        lock = load_model_lock(lock_path)
        artifact_sha256 = lock.sha256
        lock.verify_file(artifact_path)
        artifact_verified = True
        if provider != "llama_cpp":
            raise EvaluationRuntimeError(
                f"real-model evaluation requires provider llama_cpp; configured {provider}"
            )
        async with httpx.AsyncClient(
            base_url=settings.model_base_url,
            timeout=settings.model_gateway_timeout_seconds,
        ) as client:
            health_response = await client.get("/health")
            health_response.raise_for_status()
            health_ok = True

            models_response = await client.get("/v1/models")
            models_response.raise_for_status()
            models_ok = True
            models_payload: Any = models_response.json()
            returned_model_ids = _model_ids(models_payload)
            identity_consistent = bool(
                set(returned_model_ids)
                & {settings.model_id, "aaa-slm"}
            )
            if not identity_consistent:
                raise EvaluationRuntimeError(
                    "llama-server model identity does not match the configured model or alias"
                )
            metrics = await read_server_metrics(client)
        report = RuntimePreflightReport(
            status="PASS",
            provider=provider,
            endpoint=settings.model_base_url,
            model_id=settings.model_id,
            artifact_path=str(artifact_path),
            artifact_sha256=artifact_sha256,
            artifact_verified=artifact_verified,
            health_ok=health_ok,
            models_endpoint_ok=models_ok,
            returned_model_ids=returned_model_ids,
            model_identity_consistent=identity_consistent,
            server_metrics_available=metrics is not None,
        )
        return PreflightResult(report=report, metrics=metrics)
    except Exception as exc:
        report = RuntimePreflightReport(
            status="FAIL",
            provider=provider,
            endpoint=settings.model_base_url,
            model_id=settings.model_id,
            artifact_path=str(artifact_path),
            artifact_sha256=artifact_sha256,
            artifact_verified=artifact_verified,
            health_ok=health_ok,
            models_endpoint_ok=bool(returned_model_ids),
            returned_model_ids=returned_model_ids,
            model_identity_consistent=identity_consistent,
            server_metrics_available=metrics is not None,
            error=str(exc),
        )
        return PreflightResult(report=report, metrics=metrics)


async def read_server_metrics(client: httpx.AsyncClient) -> ServerMetricsSnapshot | None:
    try:
        response = await client.get("/metrics")
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    values = _parse_prometheus(response.text)
    if not values:
        return None
    return ServerMetricsSnapshot(
        prompt_tokens_total=_find_metric(values, "prompt_tokens_total"),
        predicted_tokens_total=_find_metric(values, "tokens_predicted_total"),
        prompt_seconds_total=_find_metric(values, "prompt_seconds_total"),
        predicted_seconds_total=_find_metric(values, "tokens_predicted_seconds_total"),
    )


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    return [
        item["id"]
        for item in payload["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([-+0-9.eE]+)", line)
        if match is None:
            continue
        try:
            values[match.group(1)] = float(match.group(2))
        except ValueError:
            continue
    return values


def _find_metric(values: dict[str, float], suffix: str) -> float | None:
    for name, value in values.items():
        if name == suffix or name.endswith(f"_{suffix}"):
            return value
    return None
