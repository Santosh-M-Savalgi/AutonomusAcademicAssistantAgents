"""Application configuration for AAA v2 Sprint 0 foundation.

Sprint 6: adds JWT secret, access/refresh token expiration, bcrypt rounds.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings."""

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
    enable_rate_limit: bool = False

    # --- Authentication (Sprint 6) ---
    jwt_secret_key: str = "super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = 12

    service_name_backend: str = "backend"
    service_name_postgres: str = "postgres"
    service_name_redis: str = "redis"
    service_name_chroma: str = "chroma"
    service_name_object_storage: str = "object_storage"

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
