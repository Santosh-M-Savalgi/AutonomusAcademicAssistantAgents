"""Password hashing and verification using bcrypt (Sprint 6).

Provides secure password hashing with configurable rounds,
verification against stored hashes, and password policy validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import bcrypt

from app.core.config import get_settings


@dataclass(frozen=True)
class PasswordPolicy:
    """Password strength policy.

    Attributes:
        min_length: Minimum password length.
        require_uppercase: At least one uppercase letter required.
        require_lowercase: At least one lowercase letter required.
        require_digit: At least one digit required.
        require_special: At least one special character required.
    """

    min_length: int = 8
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True


@dataclass(frozen=True)
class PasswordValidationResult:
    """Result of password validation.

    Attributes:
        valid: Whether the password meets all policy rules.
        message: Human-readable explanation if invalid, empty if valid.
    """

    valid: bool
    message: str = ""


# Module-level singleton policy (can be overridden via env in the future).
_PASSWORD_POLICY = PasswordPolicy()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with configurable rounds.

    Args:
        password: The plain-text password to hash. Must not be empty.

    Returns:
        The bcrypt hash string suitable for storage.

    Raises:
        ValueError: If the password is empty.
    """
    if not password:
        raise ValueError("Password must not be empty")
    settings = get_settings()
    rounds = settings.bcrypt_rounds
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash.

    Args:
        plain_password: The plain-text password to verify.
        hashed_password: The stored bcrypt hash to check against.

    Returns:
        True if the password matches the hash, False otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def validate_password(password: str, policy: PasswordPolicy = _PASSWORD_POLICY) -> PasswordValidationResult:
    """Validate a password against the configured password policy.

    Args:
        password: The plain-text password to validate.
        policy: The password policy to enforce (defaults to module singleton).

    Returns:
        A PasswordValidationResult with valid flag and message.
    """
    if len(password) < policy.min_length:
        return PasswordValidationResult(
            valid=False,
            message=f"Password must be at least {policy.min_length} characters long",
        )
    if policy.require_uppercase and not re.search(r"[A-Z]", password):
        return PasswordValidationResult(
            valid=False,
            message="Password must contain at least one uppercase letter",
        )
    if policy.require_lowercase and not re.search(r"[a-z]", password):
        return PasswordValidationResult(
            valid=False,
            message="Password must contain at least one lowercase letter",
        )
    if policy.require_digit and not re.search(r"\d", password):
        return PasswordValidationResult(
            valid=False,
            message="Password must contain at least one digit",
        )
    if policy.require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\;'/`~]", password):
        return PasswordValidationResult(
            valid=False,
            message="Password must contain at least one special character",
        )
    return PasswordValidationResult(valid=True, message="")
