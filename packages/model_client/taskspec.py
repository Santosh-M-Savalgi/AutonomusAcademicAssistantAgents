"""Small, deterministic TaskSpec definitions and registry."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.model_client.runtime import MODEL_ID

TaskOutputMode = Literal["text", "structured"]
_TASK_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class TaskGenerationDefaults(BaseModel):
    """Generation defaults owned by a task, without routing concerns."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(default=MODEL_ID, min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=256, ge=1, le=4096)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)


class ValidationPolicy(BaseModel):
    """Validation policy with one bounded retry at most."""

    model_config = ConfigDict(extra="forbid")

    max_retries: Literal[0, 1] = 1
    strict: bool = True

    @property
    def max_attempts(self) -> int:
        return self.max_retries + 1


class TaskSpec(BaseModel):
    """Static execution metadata for one model task or task family."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    output_mode: TaskOutputMode
    output_model: type[BaseModel] | None = None
    generation: TaskGenerationDefaults = Field(default_factory=TaskGenerationDefaults)
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)
    metadata: dict[str, str] = Field(default_factory=dict)
    family_prefix: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TASK_NAME.fullmatch(value) is None:
            raise ValueError("task name must use lowercase letters, digits, and underscores")
        return value

    @field_validator("family_prefix")
    @classmethod
    def validate_family_prefix(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.endswith("_") or _TASK_NAME.fullmatch(value[:-1]) is None
        ):
            raise ValueError("family_prefix must be a lowercase task prefix ending in '_'")
        return value

    @model_validator(mode="after")
    def validate_output_definition(self) -> TaskSpec:
        if self.output_mode == "structured" and self.output_model is None:
            raise ValueError("structured tasks require an output_model")
        if self.output_mode == "text" and self.output_model is not None:
            raise ValueError("text tasks must not define an output_model")
        if self.family_prefix is not None and not self.name.startswith(self.family_prefix[:-1]):
            raise ValueError("family_prefix must describe the task name")
        return self

    @property
    def registration_id(self) -> str:
        """Stable display identifier; family registrations are explicit patterns."""

        return f"{self.family_prefix}*" if self.family_prefix is not None else self.name

    @property
    def output_schema(self) -> type[BaseModel] | None:
        """Compatibility name emphasizing that the model defines the schema."""

        return self.output_model

    @property
    def task_id(self) -> str:
        return self.name

    @property
    def task_version(self) -> str:
        return self.version

    @property
    def structured(self) -> bool:
        return self.output_mode == "structured"

    @property
    def retry_limit(self) -> int:
        return self.validation.max_retries


class TaskSpecError(ValueError):
    """Invalid registration or unresolved task identifier."""


class TaskSpecRegistry:
    """In-memory registry with exact and explicit prefix-family lookup."""

    def __init__(self, specs: tuple[TaskSpec, ...] = ()) -> None:
        self._specs: dict[str, TaskSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: TaskSpec) -> None:
        if spec.registration_id in self._specs:
            raise TaskSpecError(f"task is already registered: {spec.registration_id}")
        if spec.family_prefix is not None:
            for existing in self._specs.values():
                if existing.family_prefix == spec.family_prefix:
                    raise TaskSpecError(
                        f"task family is already registered: {spec.registration_id}"
                    )
        self._specs[spec.registration_id] = spec

    def resolve(self, identifier: str) -> TaskSpec:
        try:
            return self._specs[identifier]
        except KeyError:
            pass
        matches = [
            spec
            for spec in self._specs.values()
            if spec.family_prefix is not None and identifier.startswith(spec.family_prefix)
        ]
        if not matches:
            raise TaskSpecError(f"task is not registered: {identifier}")
        return max(matches, key=lambda spec: len(spec.family_prefix or ""))

    def get(self, identifier: str) -> TaskSpec:
        return self.resolve(identifier)

    def list_specs(self) -> tuple[TaskSpec, ...]:
        return tuple(sorted(self._specs.values(), key=lambda spec: spec.registration_id))

    def list_names(self) -> tuple[str, ...]:
        return tuple(spec.registration_id for spec in self.list_specs())

    def list_tasks(self) -> tuple[TaskSpec, ...]:
        return self.list_specs()
