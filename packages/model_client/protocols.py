"""Provider and gateway protocols used across the application boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from packages.model_client.contracts import (
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)


class ModelProvider(Protocol):
    """Provider-neutral interface implemented by fake and runtime providers."""

    @property
    def name(self) -> str: ...

    @property
    def metadata(self) -> ModelMetadata: ...

    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...

    async def generate_structured(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse: ...


class ModelGatewayProtocol(Protocol):
    """Stable caller-facing gateway boundary; scheduling is intentionally deferred."""

    async def generate(
        self, request: GenerationRequest, *, provider: str | None = None
    ) -> GenerationResponse: ...

    def stream(
        self, request: GenerationRequest, *, provider: str | None = None
    ) -> AsyncIterator[GenerationChunk]: ...

    async def generate_structured(
        self, request: StructuredGenerationRequest, *, provider: str | None = None
    ) -> StructuredGenerationResponse: ...


def message_sequence(request: GenerationRequest) -> Sequence[dict[str, str]]:
    """Convert the neutral prompt representation to an OpenAI-shaped message list."""

    if request.messages:
        return [message.model_dump() for message in request.messages]
    assert request.prompt is not None
    return [{"role": "user", "content": request.prompt}]
