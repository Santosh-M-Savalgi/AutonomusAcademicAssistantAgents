"""Deterministic provider used by the mock profile and all normal tests."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from packages.model_client.contracts import (
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from packages.model_client.errors import ModelClientError, ModelTimeoutError
from packages.model_client.runtime import MODEL_ID


class FakeProvider:
    """A configurable, in-memory provider with no network or model dependencies."""

    def __init__(
        self,
        *,
        model_id: str = MODEL_ID,
        response_text: str = "fake response",
        responses: Mapping[str, str] | None = None,
        stream_chunks: Sequence[str] = ("fake ", "response"),
        stream_responses: Mapping[str, Sequence[str]] | None = None,
        structured_response: Any = None,
        structured_responses: Mapping[str, Any] | None = None,
        structured_raw_responses: Mapping[str, Sequence[str]] | None = None,
        errors: Mapping[str, ModelClientError] | None = None,
        error_sequences: Mapping[str, Sequence[ModelClientError]] | None = None,
        timeout_tasks: Sequence[str] = (),
        metadata: ModelMetadata | None = None,
    ) -> None:
        self._name = "fake"
        self._metadata = metadata or ModelMetadata(
            provider=self._name,
            model_id=model_id,
            runtime="fake",
            runtime_version="deterministic-v1",
            verified=True,
        )
        self._response_text = response_text
        self._responses = dict(responses or {})
        self._stream_chunks = tuple(stream_chunks)
        self._stream_responses = {
            key: tuple(value) for key, value in (stream_responses or {}).items()
        }
        self._structured_response = structured_response if structured_response is not None else {}
        self._structured_responses = dict(structured_responses or {})
        self._structured_raw_responses = {
            key: tuple(value) for key, value in (structured_raw_responses or {}).items()
        }
        self._structured_attempts: dict[str, int] = {}
        self._errors = dict(errors or {})
        self._error_sequences = {
            key: tuple(value) for key, value in (error_sequences or {}).items()
        }
        self._error_attempts: dict[str, int] = {}
        self._timeout_tasks = set(timeout_tasks)
        self.requests: list[GenerationRequest | StructuredGenerationRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    def _record_and_raise(self, request: GenerationRequest) -> None:
        self.requests.append(request)
        if request.task in self._timeout_tasks:
            raise ModelTimeoutError(provider=self.name)
        error_sequence = self._error_sequences.get(request.task)
        if error_sequence:
            attempt = self._error_attempts.get(request.task, 0)
            self._error_attempts[request.task] = attempt + 1
            if attempt < len(error_sequence):
                raise error_sequence[attempt]
        error = self._errors.get(request.task)
        if error is not None:
            raise error

    def _response(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            text=self._responses.get(request.task, self._response_text),
            model_id=request.model_id,
            provider=self.name,
            provenance=self._metadata,
            finish_reason="stop",
        )

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self._record_and_raise(request)
        return self._response(request)

    async def _stream_values(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        self._record_and_raise(request)
        chunks = self._stream_responses.get(request.task, self._stream_chunks)
        for text in chunks:
            yield GenerationChunk(
                text=text,
                model_id=request.model_id,
                provider=self.name,
                provenance=self._metadata,
            )
        yield GenerationChunk(
            model_id=request.model_id,
            provider=self.name,
            provenance=self._metadata,
            done=True,
            finish_reason="stop",
        )

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return self._stream_values(request)

    async def generate_structured(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse:
        self._record_and_raise(request)
        attempt = self._structured_attempts.get(request.task, 0)
        self._structured_attempts[request.task] = attempt + 1
        raw_values = self._structured_raw_responses.get(request.task)
        if raw_values:
            raw_text = raw_values[min(attempt, len(raw_values) - 1)]
            try:
                data = copy.deepcopy(json.loads(raw_text))
            except json.JSONDecodeError:
                data = None
        else:
            data = copy.deepcopy(
                self._structured_responses.get(request.task, self._structured_response)
            )
            raw_text = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return StructuredGenerationResponse(
            data=data,
            raw_text=raw_text,
            model_id=request.model_id,
            provider=self.name,
            provenance=self._metadata,
        )
