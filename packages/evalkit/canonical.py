"""Canonical serialization helpers for reproducible benchmark metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json(value: BaseModel | dict[str, Any] | list[Any]) -> str:
    """Serialize JSON-compatible values with stable ordering and separators."""

    material = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(material, sort_keys=True, separators=(",", ":"))


def configuration_fingerprint(configuration: BaseModel | dict[str, Any]) -> str:
    """Hash only canonical configuration material, never raw prompts."""

    return hashlib.sha256(canonical_json(configuration).encode()).hexdigest()


def canonical_report_json(report: BaseModel) -> str:
    return canonical_json(report)
