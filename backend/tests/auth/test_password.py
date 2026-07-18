"""Password hashing tests (Sprint 6).

Covers:
- bcrypt password hashing and verification
- Password policy validation
- Edge cases: empty password, policy violations
"""

from __future__ import annotations

import bcrypt
import pytest

from app.auth.password import (
    PasswordPolicy,
    PasswordValidationResult,
    hash_password,
    validate_password,
    verify_password,
)


class TestPasswordHashing:
    """Password hashing and verification."""

    def test_hash_password_returns_string(self) -> None:
        hashed = hash_password("SecurePass1!")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_starts_with_bcrypt_prefix(self) -> None:
        hashed = hash_password("SecurePass1!")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_different_salts(self) -> None:
        """Same password should produce different hashes (different salt)."""
        h1 = hash_password("SecurePass1!")
        h2 = hash_password("SecurePass1!")
        assert h1 != h2

    def test_verify_password_correct(self) -> None:
        password = "SecurePass1!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self) -> None:
        hashed = hash_password("SecurePass1!")
        assert verify_password("WrongPass1!", hashed) is False

    def test_verify_password_empty(self) -> None:
        hashed = hash_password("SecurePass1!")
        assert verify_password("", hashed) is False

    def test_hash_empty_password_raises(self) -> None:
        with pytest.raises(ValueError, match="Password must not be empty"):
            hash_password("")

    def test_bcrypt_rounds_configurable(self) -> None:
        """Verify bcrypt uses configurable rounds from settings."""
        # Default is 12, should produce hash with $2b$12$
        hashed = hash_password("SecurePass1!")
        assert "$12$" in hashed


class TestPasswordValidation:
    """Password policy validation."""

    def test_valid_password_passes(self) -> None:
        result = validate_password("SecurePass1!")
        assert result.valid is True
        assert result.message == ""

    def test_too_short_fails(self) -> None:
        result = validate_password("Ab1!")
        assert result.valid is False
        assert "at least 8" in result.message

    def test_no_uppercase_fails(self) -> None:
        result = validate_password("securepass1!")
        assert result.valid is False
        assert "uppercase" in result.message

    def test_no_lowercase_fails(self) -> None:
        result = validate_password("SECUREPASS1!")
        assert result.valid is False
        assert "lowercase" in result.message

    def test_no_digit_fails(self) -> None:
        result = validate_password("SecurePass!")
        assert result.valid is False
        assert "digit" in result.message

    def test_no_special_fails(self) -> None:
        result = validate_password("SecurePass1")
        assert result.valid is False
        assert "special" in result.message

    def test_custom_policy_min_length(self) -> None:
        custom = PasswordPolicy(min_length=4, require_uppercase=False, require_lowercase=False, require_digit=False, require_special=False)
        result = validate_password("ab", custom)
        assert result.valid is False
        assert "at least 4" in result.message

        result = validate_password("abcd", custom)
        assert result.valid is True

    def test_password_validation_result_frozen(self) -> None:
        result = PasswordValidationResult(valid=True, message="")
        assert result.valid
        assert result.message == ""
