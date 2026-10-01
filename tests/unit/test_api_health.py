"""FastAPI liveness and readiness endpoint tests."""

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app


class FakeProbe:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class FakeRuntime:
    def __init__(self, *, minio_error: Exception | None = None) -> None:
        self.database = FakeProbe()
        self.redis = FakeProbe()
        self.object_storage = FakeProbe(minio_error)


def make_app() -> object:
    return create_app(Settings(_env_file=None))


def test_healthz_reports_process_liveness_and_request_id() -> None:
    with TestClient(make_app()) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request"


def test_readyz_checks_all_required_dependencies() -> None:
    app = make_app()
    runtime = FakeRuntime()
    with TestClient(app) as client:
        app.state.runtime = runtime
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "postgresql": {"status": "ok"},
            "redis": {"status": "ok"},
            "minio": {"status": "ok"},
        },
    }
    assert runtime.database.calls == 1
    assert runtime.redis.calls == 1
    assert runtime.object_storage.calls == 1


def test_readyz_returns_failure_when_a_dependency_is_unavailable() -> None:
    app = make_app()
    runtime = FakeRuntime(minio_error=ConnectionError("offline"))
    with TestClient(app) as client:
        app.state.runtime = runtime
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["dependencies"]["postgresql"] == {"status": "ok"}
    assert body["dependencies"]["redis"] == {"status": "ok"}
    assert body["dependencies"]["minio"] == {
        "status": "unavailable",
        "error": "ConnectionError",
    }


def test_readyz_fails_when_runtime_resources_are_missing() -> None:
    app = make_app()
    with TestClient(app) as client:
        app.state.runtime = None
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
