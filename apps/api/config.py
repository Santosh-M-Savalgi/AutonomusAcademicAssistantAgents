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
        populate_by_name=True,
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
    jwt_secret_key: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: Literal["HS256"] = Field(
        default="HS256", validation_alias="JWT_ALGORITHM"
    )
    jwt_issuer: str = Field(default="aaa-v3", min_length=1, validation_alias="JWT_ISSUER")
    jwt_audience: str = Field(default="aaa-v3-api", min_length=1, validation_alias="JWT_AUDIENCE")
    jwt_access_token_expire_minutes: int = Field(
        default=15, ge=1, le=1440, validation_alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, ge=1, le=30, validation_alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )
    argon2_time_cost: int = Field(default=3, ge=2, le=10, validation_alias="ARGON2_TIME_COST")
    argon2_memory_cost: int = Field(
        default=65536, ge=19456, le=262144, validation_alias="ARGON2_MEMORY_COST"
    )
    argon2_parallelism: int = Field(default=4, ge=1, le=16, validation_alias="ARGON2_PARALLELISM")
    argon2_hash_length: int = Field(default=32, ge=16, le=64, validation_alias="ARGON2_HASH_LENGTH")
    argon2_salt_length: int = Field(default=16, ge=16, le=64, validation_alias="ARGON2_SALT_LENGTH")
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
