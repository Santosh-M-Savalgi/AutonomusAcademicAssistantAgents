"""Environment-backed configuration loading tests."""

import pytest
from pydantic import SecretStr, ValidationError

from apps.api.config import Settings


def test_settings_load_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("AAA_PROFILE", "cpu")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db:5432/app")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/4")
    monkeypatch.setenv("MINIO_ENDPOINT", "storage:9000")
    monkeypatch.setenv("MINIO_SECRET_KEY", "not-a-default")
    monkeypatch.setenv("MINIO_SECURE", "true")

    settings = Settings(_env_file=None)

    assert settings.aaa_profile == "cpu"
    assert settings.database_url.endswith("@db:5432/app")
    assert settings.redis_url == "redis://cache:6379/4"
    assert settings.minio_endpoint == "storage:9000"
    assert settings.minio_secret_key == SecretStr("not-a-default")
    assert settings.minio_secure is True


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.aaa_profile == "mock"
    assert settings.model_id == "meta-llama/Llama-3.2-3B-Instruct"
    assert settings.model_artifact_path.endswith("llama-3.2-3b-instruct-q4_k_m.gguf")
    assert settings.model_provider == "auto"
    assert settings.model_gateway_interactive_capacity == 4
    assert settings.model_gateway_prefetch_capacity == 2
    assert settings.model_gateway_batch_capacity == 1
    assert settings.model_gateway_timeout_seconds == 30.0
    assert settings.model_gateway_cache_enabled is False
    assert settings.llama_cpp_version == "v0.6.0"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.minio_secure is False
    assert settings.app_secret_key.get_secret_value() == "local-development-only"


def test_authentication_settings_load_from_environment(monkeypatch) -> None:
    secret = "environment-only-jwt-signing-key-long-enough"
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "20")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "4")
    monkeypatch.setenv("JWT_ISSUER", "aaa-test-issuer")
    monkeypatch.setenv("ARGON2_TIME_COST", "2")

    settings = Settings(_env_file=None)

    assert settings.jwt_secret_key == SecretStr(secret)
    assert settings.jwt_access_token_expire_minutes == 20
    assert settings.jwt_refresh_token_expire_days == 4
    assert settings.jwt_issuer == "aaa-test-issuer"
    assert settings.argon2_time_cost == 2
    assert secret not in repr(settings)


def test_authentication_settings_reject_unsafe_parameters(monkeypatch) -> None:
    for algorithm in ("none", "HS512"):
        monkeypatch.setenv("JWT_ALGORITHM", algorithm)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    monkeypatch.delenv("JWT_ALGORITHM")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
