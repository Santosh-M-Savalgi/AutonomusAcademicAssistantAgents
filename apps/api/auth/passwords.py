"""Password hashing and verification primitives.

Only Argon2id encoded hashes leave this module. Plaintext passwords are never logged,
serialized, or persisted by the authentication foundation.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from apps.api.config import Settings, get_settings


def _password_hasher(settings: Settings) -> PasswordHasher:
    """Construct an Argon2id hasher from environment-backed parameters."""

    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
        hash_len=settings.argon2_hash_length,
        salt_len=settings.argon2_salt_length,
    )


def hash_password(password: str, *, settings: Settings | None = None) -> str:
    """Hash a non-empty password with Argon2id.

    The returned encoded value contains the algorithm parameters and random salt,
    so callers only need to persist the returned string.
    """

    if not password:
        raise ValueError("Password must not be empty")

    resolved_settings = settings or get_settings()
    return _password_hasher(resolved_settings).hash(password)


def verify_password(
    password: str,
    encoded_hash: str,
    *,
    settings: Settings | None = None,
) -> bool:
    """Return whether a password matches an Argon2id encoded hash.

    Invalid or malformed stored hashes are treated as a failed verification and
    never leak details to the caller.
    """

    if not password or not encoded_hash:
        return False

    resolved_settings = settings or get_settings()
    try:
        return _password_hasher(resolved_settings).verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
