"""Password hashing regression tests for the authentication foundation."""

import pytest

from apps.api.auth.passwords import hash_password, verify_password
from apps.api.config import Settings


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(_env_file=None, argon2_memory_cost=19456, argon2_time_cost=2)


def test_hash_and_verify_password(auth_settings: Settings) -> None:
    password = "correct horse battery staple"

    encoded_hash = hash_password(password, settings=auth_settings)

    assert encoded_hash.startswith("$argon2id$")
    assert encoded_hash != password
    assert password not in encoded_hash
    assert verify_password(password, encoded_hash, settings=auth_settings)
    assert not verify_password("incorrect", encoded_hash, settings=auth_settings)


def test_password_hash_uses_fresh_salt(auth_settings: Settings) -> None:
    password = "unique-password"

    first = hash_password(password, settings=auth_settings)
    second = hash_password(password, settings=auth_settings)

    assert first != second
    assert verify_password(password, first, settings=auth_settings)
    assert verify_password(password, second, settings=auth_settings)


def test_empty_password_is_rejected(auth_settings: Settings) -> None:
    with pytest.raises(ValueError, match="empty"):
        hash_password("", settings=auth_settings)


def test_invalid_hash_is_rejected(auth_settings: Settings) -> None:
    assert not verify_password("password", "not-a-password-hash", settings=auth_settings)
    assert not verify_password("", "not-a-password-hash", settings=auth_settings)
