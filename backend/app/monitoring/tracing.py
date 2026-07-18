"""OpenTelemetry tracing setup for AAA v2.

Instruments FastAPI, SQLAlchemy, Redis, HTTP clients, and background workers
to generate distributed traces for every request.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.core.config import get_settings

_tracer: trace.Tracer | None = None


def get_tracer() -> trace.Tracer:
    """Return the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(__name__)
    return _tracer


def setup_tracing(app: Any, engine: Any | None = None) -> None:
    """Configure OpenTelemetry tracing for the application.

    Sets up a TracerProvider with OTLP export (configurable via environment
    variables) and instruments FastAPI, SQLAlchemy, Redis, and HTTPX.

    Args:
        app: FastAPI application instance to instrument.
        engine: Optional SQLAlchemy engine to instrument (for database tracing).
    """
    settings = get_settings()

    # Build resource identifying this service
    resource = Resource.create({
        "service.name": settings.service_name_backend,
        "service.version": settings.app_version,
        "deployment.environment": settings.app_env,
    })

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter if endpoint is configured
    otlp_endpoint = getattr(settings, "otel_exporter_otlp_endpoint", None)
    if otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        )
    else:
        # Fall back to console exporter for development
        provider.add_span_processor(
            BatchSpanProcessor(ConsoleSpanExporter())
        )

    # Set the global tracer provider
    trace.set_tracer_provider(provider)

    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Instrument HTTPX for outbound HTTP calls
    HTTPXClientInstrumentor().instrument()

    # Instrument Redis
    try:
        RedisInstrumentor().instrument()
    except Exception:
        pass  # Redis instrumentor may fail if redis is not fully configured

    # Instrument SQLAlchemy if engine is provided
    if engine is not None:
        try:
            SQLAlchemyInstrumentor().instrument(
                engine=engine,
            )
        except Exception:
            pass

    global _tracer
    _tracer = trace.get_tracer(__name__)
