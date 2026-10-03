"""Unit tests for request correlation and safe structured logging."""

import asyncio
import json
import logging
from typing import Annotated
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from apps.api.auth import AuthenticatedIdentity, get_current_identity
from apps.api.config import Settings
from apps.api.logging import configure_logging
from apps.api.main import create_app
from apps.api.runtime import RuntimeResources


def test_structured_logs_redact_credentials_and_student_content(capsys) -> None:
    """Sensitive fields are replaced before a JSON log line is rendered."""

    configure_logging("INFO")
    structlog.get_logger("aaa.test").info(
        "authentication_attempt",
        password="plain-text-password",
        password_hash="$argon2id$secret-hash",
        authorization="Bearer secret-token",
        student_answer="private answer",
        request_id="request-123",
    )

    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert record["password"] == "[REDACTED]"
    assert record["password_hash"] == "[REDACTED]"
    assert record["authorization"] == "[REDACTED]"
    assert record["student_answer"] == "[REDACTED]"
    assert record["request_id"] == "request-123"
    assert "plain-text-password" not in json.dumps(record)
    assert "secret-token" not in json.dumps(record)


def test_invalid_request_id_is_replaced_with_safe_generated_id() -> None:
    """Untrusted header values cannot become response-header or log injection data."""

    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "invalid id"})

    request_id = response.headers["X-Request-ID"]
    assert UUID(request_id)
    assert request_id != "invalid id"


def test_unhandled_errors_have_a_generic_response_and_request_id() -> None:
    """Operational exception details stay in server-side classification only."""

    app = create_app(Settings(_env_file=None))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password=do-not-expose")

    with TestClient(app) as client:
        response = client.get("/boom", headers={"X-Request-ID": "error-test"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["X-Request-ID"] == "error-test"
    assert "database password" not in response.text


def test_standard_library_errors_are_json_and_do_not_leak_exception_text(capsys) -> None:
    configure_logging("INFO")
    try:
        raise ValueError("postgresql://user:private-password@database/private-data")
    except ValueError:
        logging.getLogger("aaa.test").exception("failure for student@example.test")
    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "log_message"
    assert record["level"] == "error"
    assert record["error_type"] == "ValueError"
    assert "private-password" not in json.dumps(record)
    assert "student@example.test" not in json.dumps(record)
    assert "exception" not in record


def test_logging_is_idempotent_and_honours_level(capsys) -> None:
    configure_logging("WARNING")
    configure_logging("WARNING")
    structlog.get_logger("aaa.test").info("filtered_event")
    structlog.get_logger("aaa.test").warning("visible_event")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "visible_event"


async def test_concurrent_requests_correlate_application_logs_and_restore_context(
    caplog, test_app: FastAPI, async_http_client: httpx.AsyncClient,
) -> None:
    @test_app.get("/correlate/{identifier}")
    async def correlate(request: Request, identifier: str) -> dict[str, str]:
        await asyncio.sleep(0)
        structlog.get_logger("aaa.test").info("inside_request")
        return {"request_id": request.state.request_id}

    caplog.clear()
    structlog.contextvars.bind_contextvars(request_id="outer-context")
    responses = await asyncio.gather(*(
        async_http_client.get(
            "/correlate/student@example.test?secret=private-query",
            headers={"X-Request-ID": rid, "Authorization": "Bearer private-bearer"},
        ) for rid in ("request-one", "request-two")
    ))
    assert [response.json()["request_id"] for response in responses] == [
        "request-one", "request-two"
    ]
    assert [response.headers["X-Request-ID"] for response in responses] == [
        "request-one", "request-two"
    ]
    assert structlog.contextvars.get_contextvars()["request_id"] == "outer-context"
    records = [record.msg for record in caplog.records if isinstance(record.msg, dict)]
    inside = [record for record in records if record["event"] == "inside_request"]
    assert {record["request_id"] for record in inside} == {"request-one", "request-two"}
    completions = [record for record in records if record["event"] == "request_complete"]
    assert len(completions) == 2
    assert all(record["route"] == "/correlate/{identifier}" for record in completions)
    assert "private-query" not in json.dumps(records)
    assert "private-bearer" not in json.dumps(records)
    assert "student@example.test" not in json.dumps(records)


@pytest.mark.parametrize("supplied", ["", "x" * 129, "invalid\r\nid"])
def test_invalid_ids_are_bounded(http_client: TestClient, supplied: str) -> None:
    response = http_client.get("/healthz", headers={"X-Request-ID": supplied})
    assert UUID(response.headers["X-Request-ID"])


def test_generated_ids_are_unique(http_client: TestClient) -> None:
    first = http_client.get("/healthz")
    second = http_client.get("/healthz")
    assert UUID(first.headers["X-Request-ID"]) != UUID(second.headers["X-Request-ID"])


def test_auth_rejections_are_expected_conditions_without_credential_logs(
    caplog, test_app: FastAPI, http_client: TestClient, auth_headers: dict[str, str],
) -> None:
    @test_app.get("/protected")
    async def protected(
        identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    ) -> dict[str, str]:
        return {"subject": identity.subject}

    caplog.clear()
    assert http_client.get("/protected", headers=auth_headers).status_code == 200
    rejected = http_client.get(
        "/protected", headers={"Authorization": "Bearer private-invalid-token"}
    )
    assert rejected.status_code == 401
    assert rejected.headers["WWW-Authenticate"] == "Bearer"
    assert rejected.headers["X-Request-ID"]
    records = [record.msg for record in caplog.records if isinstance(record.msg, dict)]
    rejections = [r for r in records if r["event"] == "authentication_rejected"]
    assert rejections[0]["level"] == "info"
    assert rejections[0]["request_id"] == rejected.headers["X-Request-ID"]
    assert "private-invalid-token" not in json.dumps(records)
    assert auth_headers["Authorization"] not in json.dumps(records)


def test_auth_override_fixture(
    override_authentication: FastAPI, http_client: TestClient,
    auth_identity: AuthenticatedIdentity,
) -> None:
    @override_authentication.get("/identity")
    async def identity_route(
        identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    ) -> str:
        return identity.subject

    assert http_client.get("/identity").json() == auth_identity.subject


async def test_shutdown_closes_all_resources_even_if_one_fails() -> None:
    storage = Mock(close=AsyncMock(side_effect=RuntimeError("synthetic failure")))
    redis = Mock(close=AsyncMock())
    database = Mock(close=AsyncMock())
    runtime = RuntimeResources(database, redis, storage)
    with pytest.raises(RuntimeError):
        await runtime.close()
    storage.close.assert_awaited_once()
    redis.close.assert_awaited_once()
    database.close.assert_awaited_once()


def test_lifecycle_events_do_not_claim_dependency_health(
    test_app: FastAPI, fake_runtime: RuntimeResources, capsys,
) -> None:
    with TestClient(test_app) as client:
        assert client.get("/healthz").status_code == 200
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["event"] for r in records if r["event"].startswith("api_")] == [
        "api_starting", "api_started", "api_stopping", "api_stopped"
    ]
    assert not any(r["event"] == "dependency_available" for r in records)
    fake_runtime.database.check.assert_not_called()


async def test_readiness_timeout_is_observed_without_details(
    caplog, fake_runtime: RuntimeResources, test_app: FastAPI,
    async_http_client: httpx.AsyncClient,
) -> None:
    async def hanging_probe() -> None:
        await asyncio.sleep(10)

    test_app.state.settings.healthcheck_timeout_seconds = 0.01
    fake_runtime.redis.check.side_effect = hanging_probe
    caplog.clear()
    response = await async_http_client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["dependencies"]["redis"] == {
        "status": "unavailable", "error": "TimeoutError"
    }
    records = [record.msg for record in caplog.records if isinstance(record.msg, dict)]
    unavailable = [r for r in records if r["event"] == "dependency_unavailable"]
    assert unavailable[0]["dependency"] == "redis"
    assert unavailable[0]["request_id"] == response.headers["X-Request-ID"]
