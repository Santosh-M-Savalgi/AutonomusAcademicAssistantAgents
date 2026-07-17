"""Prometheus metrics for AAA v2.

Tracks API request counts, latency, error rates, provider latency,
job queue metrics, session metrics, and knowledge graph metrics.

Exposes a ``/metrics`` endpoint via a FastAPI route.
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    REGISTRY,
)

# ── API Metrics ──────────────────────────────────────────────────────────────

api_requests_total = Counter(
    "aaa_api_requests_total",
    "Total API requests",
    labelnames=["method", "path", "status"],
)

api_request_duration_seconds = Histogram(
    "aaa_api_request_duration_seconds",
    "API request latency in seconds",
    labelnames=["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

api_requests_in_flight = Gauge(
    "aaa_api_requests_in_flight",
    "Currently in-flight API requests",
    labelnames=["method"],
)

# ── Provider Metrics ─────────────────────────────────────────────────────────

llm_request_duration_seconds = Histogram(
    "aaa_llm_request_duration_seconds",
    "LLM provider request latency in seconds",
    labelnames=["provider", "operation"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

embedding_request_duration_seconds = Histogram(
    "aaa_embedding_request_duration_seconds",
    "Embedding provider request latency in seconds",
    labelnames=["provider"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

retrieval_request_duration_seconds = Histogram(
    "aaa_retrieval_request_duration_seconds",
    "Retrieval (vector search / web search) latency in seconds",
    labelnames=["source"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

provider_errors_total = Counter(
    "aaa_provider_errors_total",
    "Total provider errors",
    labelnames=["provider", "operation"],
)

# ── Job Metrics ──────────────────────────────────────────────────────────────

jobs_queued_total = Counter(
    "aaa_jobs_queued_total",
    "Total jobs queued",
    labelnames=["job_type"],
)

jobs_running = Gauge(
    "aaa_jobs_running",
    "Jobs currently running",
    labelnames=["job_type"],
)

jobs_completed_total = Counter(
    "aaa_jobs_completed_total",
    "Total jobs completed successfully",
    labelnames=["job_type"],
)

jobs_failed_total = Counter(
    "aaa_jobs_failed_total",
    "Total jobs failed",
    labelnames=["job_type"],
)

jobs_retries_total = Counter(
    "aaa_jobs_retries_total",
    "Total job retries",
    labelnames=["job_type"],
)

# ── Session Metrics ──────────────────────────────────────────────────────────

sessions_active = Gauge(
    "aaa_sessions_active",
    "Currently active learning sessions",
)

sessions_resumed_total = Counter(
    "aaa_sessions_resumed_total",
    "Total sessions resumed",
)

sessions_expired_total = Counter(
    "aaa_sessions_expired_total",
    "Total sessions expired",
)

# ── Knowledge Graph Metrics ──────────────────────────────────────────────────

kg_traversal_duration_seconds = Histogram(
    "aaa_kg_traversal_duration_seconds",
    "Knowledge graph traversal latency in seconds",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

kg_planning_duration_seconds = Histogram(
    "aaa_kg_planning_duration_seconds",
    "Knowledge graph planning latency in seconds",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── Middleware helper ────────────────────────────────────────────────────────


def observe_request(method: str, path: str, status: int, duration: float) -> None:
    """Record API request metrics.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: Request path.
        status: HTTP status code.
        duration: Request duration in seconds.
    """
    api_requests_total.labels(method=method, path=path, status=str(status)).inc()
    api_request_duration_seconds.labels(method=method, path=path).observe(duration)


def track_in_flight(method: str, delta: int = 1) -> None:
    """Adjust the in-flight request gauge.

    Args:
        method: HTTP method.
        delta: +1 when entering, -1 when leaving.
    """
    api_requests_in_flight.labels(method=method).inc(delta)


# ── Prometheus endpoint ──────────────────────────────────────────────────────


async def metrics_endpoint() -> Any:
    """Return Prometheus-formatted metrics.

    Returns:
        A FastAPI Response with ``text/plain; version=0.0.4`` content type.
    """
    from fastapi.responses import Response

    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4",
    )
