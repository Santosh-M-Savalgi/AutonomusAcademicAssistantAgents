"""Shared test configuration for Sprint 1.1."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolate_settings_cache() -> Iterator[None]:
    """Prevent one test's environment-backed settings from leaking into another."""

    from apps.api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
