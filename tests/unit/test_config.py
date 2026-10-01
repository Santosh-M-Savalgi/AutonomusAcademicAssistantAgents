"""Configuration loading tests for Sprint 1.1."""

from pydantic import SecretStr

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
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.minio_secure is False
    assert settings.app_secret_key.get_secret_value() == "local-development-only"
