"""Application configuration for AAA v2.

Supports environment-driven settings with startup validation, Pydantic field validators,
and a runtime configuration status check.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.llm.provider_router import validate_provider_startup


class Settings(BaseSettings):
    """Environment-driven settings with startup validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AAA v2 Backend"
    app_env: str = "development"
    app_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    cors_origins_raw: str = "http://localhost:5173"

    postgres_dsn: str = (
        "postgresql+asyncpg://aaa:aaa_password@postgres:5432/aaa"
    )
    redis_url: str = "redis://redis:6379/0"

    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_ssl: bool = False

    object_storage_endpoint: str = "http://minio:9000"
    object_storage_health_path: str = "/minio/health/ready"

    dependency_check_timeout_seconds: float = 2.0
    enable_rate_limit: bool = True

    # --- Authentication (Sprint 6) ---
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = 12

    service_name_backend: str = "backend"
    service_name_postgres: str = "postgres"
    service_name_redis: str = "redis"
    service_name_chroma: str = "chroma"
    service_name_object_storage: str = "object_storage"

    # --- LLM Provider ---
    llm_provider: str = Field("mock", alias="LLM_PROVIDER")
    deepseek_api_key: str = ""
    tavily_api_key: str = ""

    # --- Sprint 10: OTLP / Tracing ---
    otel_exporter_otlp_endpoint: str = ""

    # --- Sprint 10: Slow request threshold ---
    slow_request_threshold_ms: int = 500

    # --- Sprint 10: Object Storage Access ---
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def chroma_base_url(self) -> str:
        scheme = "https" if self.chroma_ssl else "http"
        return f"{scheme}://{self.chroma_host}:{self.chroma_port}"

    @property
    def object_storage_health_url(self) -> str:
        return f"{self.object_storage_endpoint.rstrip('/')}{self.object_storage_health_path}"

    # ── Validation ───────────────────────────────────────────────────────────

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Validate that the Redis URL starts with redis:// or rediss://."""
        if v and not v.startswith("redis://") and not v.startswith("rediss://"):
            raise ValueError(
                f"Invalid Redis URL: '{v}'. Must start with 'redis://' or 'rediss://'."
            )
        return v

    @field_validator("postgres_dsn")
    @classmethod
    def validate_postgres_dsn(cls, v: str) -> str:
        """Validate that the Postgres DSN starts with postgresql:// or postgresql+asyncpg://."""
        if v:
            if not v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
                raise ValueError(
                    f"Invalid Postgres DSN: '{v}'. "
                    "Must start with 'postgresql://' or 'postgresql+asyncpg://'."
                )
        return v

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT secret is set and has minimum length in production."""
        if not v:
            raise ValueError("JWT_SECRET_KEY must not be empty")
        return v

    @field_validator("object_storage_endpoint")
    @classmethod
    def validate_object_storage_endpoint(cls, v: str) -> str:
        """Validate object storage endpoint starts with http:// or https://."""
        if v and not v.startswith("http://") and not v.startswith("https://"):
            raise ValueError(
                f"Invalid object storage endpoint: '{v}'. "
                "Must start with 'http://' or 'https://'."
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings with validation.

    Raises:
        pydantic.ValidationError: If any configuration value is invalid.
    """
    return Settings()


def validate_configuration() -> dict[str, Any]:
    """Run explicit configuration validation and return a status report.

    Useful for startup health checks and diagnostics.

    Returns:
        A dict mapping each setting name to its validation status.
    """
    errors: dict[str, str] = {}

    try:
        settings = get_settings()
    except Exception as exc:
        return {"status": "invalid", "errors": {"global": str(exc)}}

    checks = {
        "redis_url": settings.redis_url,
        "postgres_dsn": settings.postgres_dsn,
        "jwt_secret_key": "set" if settings.jwt_secret_key else "missing",
        "object_storage_endpoint": settings.object_storage_endpoint,
        "chroma_host": settings.chroma_host,
        "chroma_port": settings.chroma_port,
    }

    # ── Provider startup validation ─────────────────────────────────────
    provider_errors = validate_provider_startup()
    for i, err in enumerate(provider_errors):
        errors[f"llm_provider_{i}"] = err

    for name, value in checks.items():
        if value is None or value == "" or value == "missing":
            errors[name] = f"{name} is not set"

    if errors:
        return {"status": "invalid", "errors": errors}

    return {"status": "valid"}
