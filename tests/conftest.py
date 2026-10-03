"""Shared, service-independent test fixtures for the AAA v3 foundation."""

import logging
import os
from collections.abc import AsyncIterator, Callable, Iterator
from unittest.mock import Mock

import httpx
import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AliasChoices

from apps.api.auth.dependencies import get_current_identity
from apps.api.auth.jwt import JWTService
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.config import Settings, get_settings
from apps.api.main import create_app
from apps.api.runtime import RuntimeResources
from packages.persistence import Database, ObjectStorage, RedisClient

_TEST_SIGNING_KEY = "fixture-test-only-key-with-at-least-32-characters"


@pytest.fixture(autouse=True)
def isolate_settings_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep developer environment values and cached settings out of tests."""

    names = set(Settings.model_fields)
    for field in Settings.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.casefold())
        elif isinstance(alias, AliasChoices):
            names.update(choice.casefold() for choice in alias.choices if isinstance(choice, str))
    for name in os.environ:
        if name.casefold() in names:
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def isolate_logging() -> Iterator[None]:
    """Restore process-global logging and context after lifecycle/capture tests."""

    config = structlog.get_config().copy()
    context = structlog.contextvars.get_contextvars()
    loggers = [
        logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    ]
    original = [(logger, logger.handlers[:], logger.level, logger.propagate, logger.disabled)
                for logger in loggers]
    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        for logger, handlers, level, propagate, disabled in original:
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled
        structlog.configure(**config)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**context)


@pytest.fixture
def test_settings() -> Settings:
    """Return deterministic settings that never read a developer .env file."""

    return Settings(
        _env_file=None,
        app_env="test",
        jwt_secret_key=_TEST_SIGNING_KEY,
    )


@pytest.fixture
def app_factory(test_settings: Settings) -> Iterator[Callable[..., FastAPI]]:
    """Create fresh production applications and restore all dependency overrides."""

    applications: list[FastAPI] = []

    def factory(settings: Settings | None = None) -> FastAPI:
        application = create_app(settings or test_settings)
        applications.append(application)
        return application

    yield factory
    for application in applications:
        application.dependency_overrides.clear()


@pytest.fixture
def fake_runtime() -> RuntimeResources:
    """Controlled dependency probes without sockets or Docker."""

    return RuntimeResources(
        database=Mock(spec=Database),
        redis=Mock(spec=RedisClient),
        object_storage=Mock(spec=ObjectStorage),
    )


@pytest.fixture
def test_app(
    app_factory: Callable[..., FastAPI],
    fake_runtime: RuntimeResources,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """Use the production lifespan with controlled resources for unit tests."""

    monkeypatch.setattr("apps.api.main.create_runtime_resources", lambda _: fake_runtime)
    return app_factory()


@pytest.fixture
def http_client(test_app: FastAPI) -> Iterator[TestClient]:
    """Provide a lifecycle-managed HTTP client for API unit tests."""

    with TestClient(test_app) as client:
        yield client


@pytest.fixture
async def async_http_client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run startup/shutdown explicitly: HTTPX's ASGITransport does not do so."""

    async with (
        test_app.router.lifespan_context(test_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=test_app), base_url="http://testserver"
        ) as client,
    ):
        yield client


@pytest.fixture
def jwt_test_token(test_settings: Settings) -> str:
    """Create a valid access token without exposing token material in logs."""

    return JWTService(test_settings).create_access_token("fixture-student")


@pytest.fixture
def auth_identity(test_settings: Settings, jwt_test_token: str) -> AuthenticatedIdentity:
    """Return the validated identity represented by the fixture access token."""

    claims = JWTService(test_settings).validate_access_token(jwt_test_token)
    return AuthenticatedIdentity.from_claims(claims)


@pytest.fixture
def auth_headers(jwt_test_token: str) -> dict[str, str]:
    """Return an Authorization header suitable for protected-route tests."""

    return {"Authorization": f"Bearer {jwt_test_token}"}


@pytest.fixture
def override_authentication(
    test_app: FastAPI,
    auth_identity: AuthenticatedIdentity,
) -> Iterator[FastAPI]:
    """Override identity resolution and restore the app's dependency map after use."""

    async def resolve_identity() -> AuthenticatedIdentity:
        return auth_identity

    original = test_app.dependency_overrides.copy()
    test_app.dependency_overrides[get_current_identity] = resolve_identity
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()
        test_app.dependency_overrides.update(original)
