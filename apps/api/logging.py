"""Safe structured logging configuration for the API process."""

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "bearer",
        "body",
        "credential",
        "database_url",
        "dsn",
        "password",
        "password_hash",
        "payload",
        "raw_body",
        "refresh_token",
        "request_body",
        "response_body",
        "secret",
        "secret_key",
        "student_answer",
        "student_id",
        "student_email",
        "student_name",
        "student_profile",
        "token",
        "user_email",
    }
)
_REDACTED = "[REDACTED]"
_EVENT_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_OPERATIONAL_FIELDS = frozenset(
    {
        "event", "logger", "level", "timestamp", "request_id", "service",
        "method", "route", "status_code", "duration_ms", "error_type",
        "dependency", "dependencies", "reason", "app_env",
        "job_id", "worker_id",
    }
)


def _normalise_key(key: object) -> str:
    """Convert log field names to a stable form for sensitivity checks."""

    return str(key).casefold().replace("-", "_")


def _redact_value(key: object, value: Any) -> Any:
    """Redact secrets and request-content fields before rendering a log entry."""

    normalised_key = _normalise_key(key)
    if (
        normalised_key in _SENSITIVE_KEYS
        or normalised_key.endswith("_password")
        or normalised_key.endswith("_password_hash")
        or normalised_key.endswith("_secret")
        or normalised_key.endswith("_secret_key")
        or normalised_key.endswith("_dsn")
        or normalised_key.endswith("_email")
        or normalised_key.endswith("_token")
        or normalised_key.endswith("_answer")
        or normalised_key.endswith("_content")
        or normalised_key.endswith("_credentials")
    ):
        return _REDACTED

    if isinstance(value, Mapping):
        return {
            nested_key: _redact_value(nested_key, nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value("value", item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value("value", item) for item in value)
    return value


def redact_sensitive_fields(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Render only operational metadata, never arbitrary objects or exception text.

    Free-form standard-library messages (HTTP URLs, SQL, traceback messages) are
    replaced with a static event. Application events must be static identifiers;
    unknown fields are redacted as defense in depth, including nested payloads.
    """

    exc_info = event_dict.pop("exc_info", None)
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, tuple) and isinstance(exc_info[1], BaseException):
        event_dict["error_type"] = type(exc_info[1]).__name__
    elif isinstance(exc_info, BaseException):
        event_dict["error_type"] = type(exc_info).__name__
    for field in ("exception", "stack", "stack_info"):
        event_dict.pop(field, None)
    event = event_dict.get("event")
    if not isinstance(event, str) or not _EVENT_NAME.fullmatch(event):
        event_dict["event"] = "log_message"
    event_dict.setdefault("service", "aaa-api")
    return {
        key: _redact_value(key, value) if key in _OPERATIONAL_FIELDS else _REDACTED
        for key, value in event_dict.items()
    }


def _processors() -> list[Processor]:
    """Return processors shared by structlog and standard-library log records."""

    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive_fields,
    ]


def configure_logging(log_level: str, *, service: str = "aaa-api") -> None:
    """Configure JSON logs for both application and standard-library loggers.

    Request bodies, credentials, tokens, password material, and database
    connection values are redacted by a processor before serialization. The
    API deliberately logs request metadata only; callers must not pass raw
    request content to a logger.
    """

    level = logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=_processors(),
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    structlog.contextvars.bind_contextvars(service=service)
    # Uvicorn otherwise owns plaintext handlers, including raw URL access logs.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True

    structlog.configure(
        processors=[*_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
