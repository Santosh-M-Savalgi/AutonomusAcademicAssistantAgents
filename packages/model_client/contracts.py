"""Provider-neutral model request, response, and provenance contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.model_client.policies import Lane
from packages.model_client.runtime import MODEL_ID


class ModelMetadata(BaseModel):
    """Provenance attached to every model result returned to application code."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    runtime_commit: str | None = None
    artifact_filename: str | None = None
    artifact_sha256: str | None = None
    quantization: str | None = None
    task_version: str | None = None
    prompt_version: str | None = None
    retrieval_version: str | None = None
    verified: bool = False


class ChatMessage(BaseModel):
    """The small chat message subset shared by providers."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class UsageStats(BaseModel):
    """Optional usage values reported by a provider."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class GenerationRequest(BaseModel):
    """A provider-neutral text-generation request."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    model_id: str = Field(default=MODEL_ID, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=4096)
    timeout_seconds: float | None = Field(default=None, gt=0.0, le=600.0)
    lane: Lane = Lane.INTERACTIVE
    cacheable: bool = False
    correlation_id: str | None = Field(default=None, min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_one_prompt_form(self) -> GenerationRequest:
        if bool(self.prompt) == bool(self.messages):
            raise ValueError("provide exactly one of prompt or messages")
        return self


class StructuredGenerationRequest(GenerationRequest):
    """Generation request carrying a provider-neutral JSON-schema specification."""

    schema_spec: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        min_length=1,
        description="JSON-schema or equivalent format specification",
    )
    task_version: str | None = Field(default=None, min_length=1)
    format: Literal["json_schema"] = "json_schema"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GenerationResponse(BaseModel):
    """Normalized non-streaming generation output."""

    model_config = ConfigDict(extra="forbid")

    text: str
    model_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provenance: ModelMetadata
    finish_reason: str | None = None
    usage: UsageStats | None = None
    response_id: str | None = None


class GenerationChunk(BaseModel):
    """One normalized streaming delta."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    done: bool = False
    model_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provenance: ModelMetadata
    finish_reason: str | None = None

    @property
    def delta(self) -> str:
        """Compatibility name for callers that call a stream delta a delta."""

        return self.text


class StructuredValidationInfo(BaseModel):
    """Deterministic validation result attached after gateway processing."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    attempts: int = Field(ge=1, le=2)
    task: str = Field(min_length=1)
    task_version: str = Field(min_length=1)
    errors: list[str] = Field(default_factory=list)


StructuredValidationCategory = Literal[
    "success",
    "json_decoding_failure",
    "pydantic_validation_failure",
    "duplicate_label",
    "cardinality_failure",
    "enum_violation",
]


class StructuredValidationDiagnostic(BaseModel):
    """Sanitized, opt-in details for one structured-validation attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1, le=2)
    category: StructuredValidationCategory
    locations: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    success: bool
    sanitized_tags: list[str] | None = None
    tag_count: int | None = Field(default=None, ge=0)
    tag_frequencies: dict[str, int] | None = None


class StructuredGenerationResponse(BaseModel):
    """Structured output before or after deterministic gateway validation."""

    model_config = ConfigDict(extra="forbid")

    data: Any | None = None
    raw_text: str
    model_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provenance: ModelMetadata
    usage: UsageStats | None = None
    response_id: str | None = None
    validation: StructuredValidationInfo | None = None
