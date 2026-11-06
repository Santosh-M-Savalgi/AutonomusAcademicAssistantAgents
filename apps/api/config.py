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
    model_provider: Literal["auto", "fake", "llama_cpp"] = Field(
        default="auto", validation_alias=AliasChoices("MODEL_PROVIDER")
    )
    model_base_url: str = Field(
        default="http://127.0.0.1:8080", validation_alias=AliasChoices("MODEL_BASE_URL")
    )
    model_id: Literal["meta-llama/Llama-3.2-3B-Instruct"] = Field(
        default="meta-llama/Llama-3.2-3B-Instruct", validation_alias=AliasChoices("MODEL_ID")
    )
    model_artifact_path: str = Field(
        default="models/llama-3.2-3b-instruct-q4_k_m.gguf",
        validation_alias=AliasChoices("MODEL_ARTIFACT_PATH"),
    )
    model_lock_path: str = Field(
        default="models/MODELS.lock", validation_alias=AliasChoices("MODEL_LOCK_PATH")
    )
    llama_cpp_version: Literal["v0.6.0"] = Field(
        default="v0.6.0", validation_alias=AliasChoices("LLAMA_CPP_VERSION")
    )
    model_gateway_retry_max_attempts: int = Field(
        default=2, ge=1, le=3, validation_alias=AliasChoices("MODEL_GATEWAY_RETRY_MAX_ATTEMPTS")
    )
    model_gateway_retry_base_delay_seconds: float = Field(
        default=0.05,
        ge=0,
        le=60,
        validation_alias=AliasChoices("MODEL_GATEWAY_RETRY_BASE_DELAY_SECONDS"),
    )
    model_gateway_retry_max_delay_seconds: float = Field(
        default=1.0,
        ge=0,
        le=120,
        validation_alias=AliasChoices("MODEL_GATEWAY_RETRY_MAX_DELAY_SECONDS"),
    )
    model_gateway_retry_jitter_seconds: float = Field(
        default=0.05,
        ge=0,
        le=60,
        validation_alias=AliasChoices("MODEL_GATEWAY_RETRY_JITTER_SECONDS"),
    )
    model_gateway_interactive_capacity: int = Field(
        default=4, ge=1, le=100, validation_alias=AliasChoices("MODEL_GATEWAY_INTERACTIVE_CAPACITY")
    )
    model_gateway_prefetch_capacity: int = Field(
        default=2, ge=1, le=100, validation_alias=AliasChoices("MODEL_GATEWAY_PREFETCH_CAPACITY")
    )
    model_gateway_batch_capacity: int = Field(
        default=1, ge=1, le=100, validation_alias=AliasChoices("MODEL_GATEWAY_BATCH_CAPACITY")
    )
    model_gateway_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600,
        validation_alias=AliasChoices("MODEL_GATEWAY_TIMEOUT_SECONDS"),
    )
    model_gateway_circuit_failure_threshold: int = Field(
        default=3,
        ge=1,
        le=100,
        validation_alias=AliasChoices("MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD"),
    )
    model_gateway_circuit_open_duration_seconds: float = Field(
        default=30.0,
        ge=0,
        le=3600,
        validation_alias=AliasChoices("MODEL_GATEWAY_CIRCUIT_OPEN_DURATION_SECONDS"),
    )
    model_gateway_circuit_half_open_probe_capacity: int = Field(
        default=1,
        ge=1,
        le=100,
        validation_alias=AliasChoices("MODEL_GATEWAY_CIRCUIT_HALF_OPEN_PROBE_CAPACITY"),
    )
    model_gateway_cache_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("MODEL_GATEWAY_CACHE_ENABLED")
    )
    model_gateway_cache_ttl_seconds: float = Field(
        default=60.0,
        gt=0,
        le=86400,
        validation_alias=AliasChoices("MODEL_GATEWAY_CACHE_TTL_SECONDS"),
    )
    model_gateway_telemetry_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("MODEL_GATEWAY_TELEMETRY_ENABLED")
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
    max_upload_size_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1,
        le=20 * 1024 * 1024,
        validation_alias=AliasChoices("MAX_UPLOAD_SIZE_BYTES"),
    )
    max_pdf_pages: int = Field(
        default=500,
        ge=1,
        le=10000,
        validation_alias=AliasChoices("MAX_PDF_PAGES"),
    )
    upload_chunk_size_bytes: int = Field(
        default=1024 * 1024,
        ge=4096,
        le=4 * 1024 * 1024,
        validation_alias=AliasChoices("UPLOAD_CHUNK_SIZE_BYTES"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings object."""

    return Settings()
