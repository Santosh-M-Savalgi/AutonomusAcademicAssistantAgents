"""Environment-backed application settings for the runtime foundation."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="AAA v3 API", validation_alias=AliasChoices("APP_NAME"))
    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development", validation_alias=AliasChoices("APP_ENV")
    )
    aaa_profile: Literal["mock", "cpu", "gpu"] = Field(
        default="mock", validation_alias=AliasChoices("AAA_PROFILE")
    )
    app_secret_key: SecretStr = Field(
        default=SecretStr("local-development-only"),
        validation_alias=AliasChoices("APP_SECRET_KEY", "SECRET_KEY"),
    )
    api_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("API_HOST"))
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias=AliasChoices("API_PORT"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))
    database_url: str = Field(
        default="postgresql+asyncpg://aaa:aaa@localhost:5433/aaa",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_DSN"),
    )
    redis_url: str = Field(
        default="redis://localhost:6380/0", validation_alias=AliasChoices("REDIS_URL")
    )
    minio_endpoint: str = Field(
        default="localhost:9000", validation_alias=AliasChoices("MINIO_ENDPOINT")
    )
    minio_access_key: str = Field(
        default="aaa-minio", validation_alias=AliasChoices("MINIO_ACCESS_KEY")
    )
    minio_secret_key: SecretStr = Field(
        default=SecretStr("aaa-minio-secret"),
        validation_alias=AliasChoices("MINIO_SECRET_KEY"),
    )
    minio_bucket: str = Field(default="aaa", validation_alias=AliasChoices("MINIO_BUCKET"))
    minio_secure: bool = Field(default=False, validation_alias=AliasChoices("MINIO_SECURE"))
    healthcheck_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=30,
        validation_alias=AliasChoices("HEALTHCHECK_TIMEOUT_SECONDS"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings object."""

    return Settings()
