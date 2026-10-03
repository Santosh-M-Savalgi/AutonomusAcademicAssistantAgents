"""JWT signing and validation tests for the authentication foundation."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from apps.api.auth.jwt import InvalidTokenError, JWTConfigurationError, JWTService
from apps.api.config import Settings

_TEST_SIGNING_KEY = "unit-test-only-key-with-at-least-32-characters"


@pytest.fixture
def jwt_settings() -> Settings:
    return Settings(_env_file=None, jwt_secret_key=_TEST_SIGNING_KEY)


def test_access_token_round_trip(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    token = service.create_access_token("student-123", additional_claims={"course_id": "abc"})

    claims = service.validate_access_token(token)

    assert claims.subject == "student-123"
    assert claims.token_type == "access"
    assert claims.token_id
    assert claims.issuer == jwt_settings.jwt_issuer
    assert claims.audience == jwt_settings.jwt_audience
    assert claims.expires_at > claims.issued_at
    assert claims.model_extra == {"course_id": "abc"}


def test_refresh_token_is_not_accepted_as_access_token(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    token = service.create_refresh_token("student-123")

    assert service.decode_token(token).token_type == "refresh"
    with pytest.raises(InvalidTokenError, match="type"):
        service.validate_access_token(token)


def test_expired_token_is_rejected(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    token = service.create_access_token("student-123", expires_delta=timedelta(seconds=-1))

    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


def test_invalid_token_or_signature_is_rejected(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    token = service.create_access_token("student-123")
    other_service = JWTService(
        Settings(_env_file=None, jwt_secret_key="other-test-only-key-with-at-least-32-characters")
    )

    with pytest.raises(InvalidTokenError):
        service.decode_token("not-a-jwt")
    with pytest.raises(InvalidTokenError):
        other_service.decode_token(token)


@pytest.mark.parametrize("omitted", ["sub", "iat", "exp", "jti", "token_type", "iss", "aud"])
def test_required_claim_is_enforced(jwt_settings: Settings, omitted: str) -> None:
    service = JWTService(jwt_settings)
    now = datetime.now(UTC)
    payload = {
        "sub": "student-123",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": "token-123",
        "token_type": "access",
        "iss": jwt_settings.jwt_issuer,
        "aud": jwt_settings.jwt_audience,
    }
    payload.pop(omitted)
    token = jwt.encode(payload, _TEST_SIGNING_KEY, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


@pytest.mark.parametrize("claim", ["sub", "jti", "iss", "aud"])
def test_empty_claim_is_rejected(jwt_settings: Settings, claim: str) -> None:
    service = JWTService(jwt_settings)
    now = datetime.now(UTC)
    payload = {
        "sub": "student-123",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": "token-123",
        "token_type": "access",
        "iss": jwt_settings.jwt_issuer,
        "aud": jwt_settings.jwt_audience,
    }
    payload[claim] = ""
    token = jwt.encode(payload, _TEST_SIGNING_KEY, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


@pytest.mark.parametrize(
    ("claim", "value"),
    [("sub", 123), ("jti", 123), ("token_type", "admin"), ("iss", 123), ("aud", 123)],
)
def test_malformed_claim_is_rejected(
    jwt_settings: Settings, claim: str, value: object
) -> None:
    service = JWTService(jwt_settings)
    now = datetime.now(UTC)
    payload = {
        "sub": "student-123",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": "token-123",
        "token_type": "access",
        "iss": jwt_settings.jwt_issuer,
        "aud": jwt_settings.jwt_audience,
    }
    payload[claim] = value
    token = jwt.encode(payload, _TEST_SIGNING_KEY, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


def test_future_issued_at_is_rejected(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    now = datetime.now(UTC)
    payload = {
        "sub": "student-123",
        "iat": now + timedelta(hours=1),
        "exp": now + timedelta(hours=2),
        "jti": "token-123",
        "token_type": "access",
        "iss": jwt_settings.jwt_issuer,
        "aud": jwt_settings.jwt_audience,
    }
    token = jwt.encode(payload, _TEST_SIGNING_KEY, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


def test_wrong_issuer_audience_and_algorithm_are_rejected(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)
    now = datetime.now(UTC)
    payload = {
        "sub": "student-123",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "jti": "token-123",
        "token_type": "access",
        "iss": jwt_settings.jwt_issuer,
        "aud": jwt_settings.jwt_audience,
    }
    for key, value in (("iss", "wrong"), ("aud", "wrong")):
        token = jwt.encode({**payload, key: value}, _TEST_SIGNING_KEY, algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            service.decode_token(token)

    token = jwt.encode(payload, _TEST_SIGNING_KEY, algorithm="HS512")
    with pytest.raises(InvalidTokenError):
        service.decode_token(token)


def test_reserved_claims_cannot_be_overridden(jwt_settings: Settings) -> None:
    service = JWTService(jwt_settings)

    with pytest.raises(ValueError, match="reserved claims"):
        service.create_access_token("student-123", additional_claims={"exp": "override"})


def test_missing_short_or_placeholder_signing_key_is_rejected() -> None:
    for key in (None, "too-short", "replace-with-a-unique-random-secret-at-least-32-characters"):
        service = JWTService(Settings(_env_file=None, jwt_secret_key=key))
        with pytest.raises(JWTConfigurationError):
            service.create_access_token("student-123")


def test_empty_subject_is_rejected(jwt_settings: Settings) -> None:
    with pytest.raises(ValueError, match="subject"):
        JWTService(jwt_settings).create_access_token("")
