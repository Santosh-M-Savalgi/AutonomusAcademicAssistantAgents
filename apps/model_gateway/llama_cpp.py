"""OpenAI-compatible llama-server provider owned by the internal gateway."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from packages.model_client.contracts import (
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    UsageStats,
)
from packages.model_client.errors import (
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from packages.model_client.protocols import message_sequence
from packages.model_client.runtime import (
    LLAMA_CPP_COMMIT,
    LLAMA_CPP_VERSION,
    MODEL_FILENAME,
    MODEL_ID,
)


class LlamaCppProvider:
    """Translate neutral model calls to the pinned llama-server HTTP API."""

    def __init__(
        self,
        *,
        base_url: str,
        model_id: str = MODEL_ID,
        artifact_filename: str = MODEL_FILENAME,
        artifact_sha256: str | None = None,
        quantization: str = "Q4_K_M",
        server_model_alias: str = "aaa-slm",
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._name = "llama_cpp"
        self._model_id = model_id
        self._server_model_alias = server_model_alias
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self._base_url)
        self._metadata = ModelMetadata(
            provider=self._name,
            model_id=model_id,
            runtime="llama.cpp",
            runtime_version=LLAMA_CPP_VERSION,
            runtime_commit=LLAMA_CPP_COMMIT,
            artifact_filename=artifact_filename,
            artifact_sha256=artifact_sha256,
            quantization=quantization,
            verified=artifact_sha256 is not None,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(
        self, request: GenerationRequest, *, stream: bool = False
    ) -> dict[str, Any]:
        return {
            "model": self._server_model_alias,
            "messages": list(message_sequence(request)),
            "temperature": request.temperature if request.temperature is not None else 0.2,
            "max_tokens": request.max_tokens if request.max_tokens is not None else 256,
            "stream": stream,
        }

    @staticmethod
    def _headers(request: GenerationRequest) -> dict[str, str]:
        if request.correlation_id is None:
            return {}
        return {"X-Request-ID": request.correlation_id}

    async def _request_json(
        self, request: GenerationRequest, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(
                "/v1/chat/completions",
                json=dict(payload),
                headers=self._headers(request),
                timeout=request.timeout_seconds or self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(provider=self.name) from exc
        except httpx.RequestError as exc:
            raise ModelUnavailableError(provider=self.name) from exc
        return self._decode_response(response)

    def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable:
                raise ModelUnavailableError(provider=self.name, status_code=response.status_code)
            raise ModelProviderError(
                provider=self.name,
                retryable=False,
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ModelResponseError(provider=self.name) from exc
        if not isinstance(payload, dict):
            raise ModelResponseError(provider=self.name)
        return payload

    def _translate_response(self, payload: Mapping[str, Any]) -> GenerationResponse:
        try:
            choices = payload["choices"]
            choice = choices[0]
            message = choice["message"]
            content = message.get("content", "")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            finish_reason = choice.get("finish_reason")
            usage_payload = payload.get("usage")
            if isinstance(usage_payload, Mapping):
                usage_payload = {
                    field: usage_payload[field]
                    for field in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if field in usage_payload
                }
            usage = UsageStats.model_validate(usage_payload) if usage_payload else None
            response_id = payload.get("id")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelResponseError(provider=self.name) from exc
        return GenerationResponse(
            text=content,
            model_id=self._model_id,
            provider=self.name,
            provenance=self.metadata,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=usage,
            response_id=response_id if isinstance(response_id, str) else None,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload = await self._request_json(request, self._payload(request))
        return self._translate_response(payload)

    async def _stream_response(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=self._payload(request, stream=True),
                headers=self._headers(request),
                timeout=request.timeout_seconds or self._timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    self._decode_response(response)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        yield GenerationChunk(
                            model_id=request.model_id,
                            provider=self.name,
                            provenance=self.metadata,
                            done=True,
                            finish_reason="stop",
                        )
                        return
                    try:
                        payload = json.loads(data)
                        choice = payload["choices"][0]
                        delta = choice.get("delta", {}).get("content", "")
                        finish_reason = choice.get("finish_reason")
                        if delta is None:
                            delta = ""
                        if not isinstance(delta, str):
                            raise TypeError("delta content is not text")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                        raise ModelResponseError(provider=self.name) from exc
                    yield GenerationChunk(
                        text=delta,
                        model_id=request.model_id,
                        provider=self.name,
                        provenance=self.metadata,
                        done=finish_reason is not None,
                        finish_reason=finish_reason
                        if isinstance(finish_reason, str)
                        else None,
                    )
                yield GenerationChunk(
                    model_id=request.model_id,
                    provider=self.name,
                    provenance=self.metadata,
                    done=True,
                    finish_reason="stop",
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(provider=self.name) from exc
        except httpx.RequestError as exc:
            raise ModelUnavailableError(provider=self.name) from exc

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        return self._stream_response(request)

    async def generate_structured(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse:
        payload = self._payload(request)
        payload["response_format"] = {
            "type": request.format,
            "json_schema": {
                "schema": request.schema_spec,
            },
        }
        generation = self._translate_response(await self._request_json(request, payload))
        try:
            untrusted_data: Any = json.loads(generation.text)
        except json.JSONDecodeError:
            untrusted_data = None
        return StructuredGenerationResponse(
            data=untrusted_data,
            raw_text=generation.text,
            model_id=generation.model_id,
            provider=generation.provider,
            provenance=generation.provenance,
            usage=generation.usage,
            response_id=generation.response_id,
        )
