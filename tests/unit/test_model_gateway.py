"""Deterministic Phase 4.2 provider and gateway tests."""

import json

import httpx
import pytest

from apps.api.config import Settings
from apps.model_gateway.factory import create_model_gateway
from apps.model_gateway.gateway import ModelGateway
from apps.model_gateway.llama_cpp import LlamaCppProvider
from packages.model_client.contracts import (
    ChatMessage,
    GenerationRequest,
    StructuredGenerationRequest,
)
from packages.model_client.errors import (
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputValidationError,
)
from packages.model_client.fake import FakeProvider
from packages.model_client.runtime import MODEL_ID
from packages.model_client.schema import (
    generate_question_tag_generation_schema,
    generate_subject_neutral_question_tag_generation_schema,
)


def request(
    *, task: str = "lesson_block", prompt: str = "Explain photosynthesis"
) -> GenerationRequest:
    return GenerationRequest(task=task, prompt=prompt, correlation_id="corr-123")


@pytest.mark.asyncio
async def test_fake_provider_generation_is_deterministic_and_records_request() -> None:
    provider = FakeProvider(responses={"lesson_block": "fixed answer"})

    response = await provider.generate(request())

    assert response.text == "fixed answer"
    assert response.provider == "fake"
    assert response.model_id == MODEL_ID
    assert response.provenance.runtime == "fake"
    assert provider.requests == [request()]


@pytest.mark.asyncio
async def test_fake_provider_streaming_is_configurable() -> None:
    provider = FakeProvider(stream_responses={"lesson_block": ("one", " two")})

    chunks = [chunk async for chunk in provider.stream(request())]

    assert [chunk.text for chunk in chunks] == ["one", " two", ""]
    assert [chunk.done for chunk in chunks] == [False, False, True]
    assert all(chunk.provider == "fake" for chunk in chunks)


@pytest.mark.asyncio
async def test_fake_provider_structured_response_is_configurable() -> None:
    provider = FakeProvider(structured_responses={"extract": {"items": ["one", "two"]}})
    structured = StructuredGenerationRequest(
        task="extract",
        prompt="Extract items",
        schema={"type": "object", "properties": {"items": {"type": "array"}}},
    )

    response = await provider.generate_structured(structured)

    assert response.data == {"items": ["one", "two"]}
    assert response.raw_text == '{"items":["one","two"]}'


@pytest.mark.asyncio
async def test_fake_provider_errors_are_deterministic() -> None:
    provider = FakeProvider(timeout_tasks=("slow",))

    with pytest.raises(ModelTimeoutError) as error:
        await provider.generate(request(task="slow"))

    assert error.value.code == "MODEL_TIMEOUT"
    assert error.value.provider == "fake"


@pytest.mark.asyncio
async def test_gateway_selects_provider_delegates_and_attaches_provenance() -> None:
    fake = FakeProvider(response_text="delegated")
    gateway = ModelGateway({"fake": fake}, default_provider="fake")

    response = await gateway.generate(request())

    assert response.text == "delegated"
    assert response.provenance.provider == "fake"
    assert gateway.provider_names == ("fake",)


@pytest.mark.asyncio
async def test_gateway_normalizes_unknown_provider_and_timeouts() -> None:
    fake = FakeProvider(timeout_tasks=("slow",))
    gateway = ModelGateway({"fake": fake}, default_provider="fake")

    with pytest.raises(ModelProviderError) as missing:
        await gateway.generate(request(), provider="missing")
    assert missing.value.code == "MODEL_PROVIDER_ERROR"

    with pytest.raises(ModelTimeoutError):
        await gateway.generate(request(task="slow"))


@pytest.mark.asyncio
async def test_gateway_streaming_delegates_to_fake_provider() -> None:
    gateway = ModelGateway(
        {"fake": FakeProvider(stream_chunks=("a", "b"))}, default_provider="fake"
    )

    chunks = [chunk async for chunk in gateway.stream(request())]

    assert "".join(chunk.text for chunk in chunks) == "ab"
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_llama_cpp_translates_openai_compatible_response() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["model"] == "aaa-slm"
        assert body["messages"] == [{"role": "user", "content": "Explain photosynthesis"}]
        assert body["stream"] is False
        assert http_request.headers["X-Request-ID"] == "corr-123"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "aaa-slm",
                "choices": [{"message": {"content": "Plants use light."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)

    response = await provider.generate(request())
    await client.aclose()

    assert response.text == "Plants use light."
    assert response.provider == "llama_cpp"
    assert response.model_id == MODEL_ID
    assert response.provenance.runtime_version == "v0.6.0"
    assert response.usage is not None
    assert response.usage.total_tokens == 7


@pytest.mark.asyncio
async def test_llama_cpp_translates_sse_stream() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        del http_request
        lines = (
            'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=lines.encode(),
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)

    chunks = [chunk async for chunk in provider.stream(request())]
    await client.aclose()

    assert [chunk.text for chunk in chunks] == ["Hello", " world", ""]
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_llama_cpp_structured_request_and_http_errors_are_normalized() -> None:
    async def structured_handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"] == {"type": "object"}
        assert "schema" not in body["response_format"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":42}'}}],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 22,
                    "total_tokens": 62,
                    "prompt_tokens_details": {"cached_tokens": 39},
                },
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(structured_handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)
    structured = StructuredGenerationRequest(
        task="structured",
        messages=[ChatMessage(role="user", content="Return JSON")],
        schema={"type": "object"},
    )

    response = await provider.generate_structured(structured)
    await client.aclose()

    assert response.data == {"answer": 42}
    assert response.usage is not None
    assert response.usage.model_dump() == {
        "prompt_tokens": 40,
        "completion_tokens": 22,
        "total_tokens": 62,
    }

    async def unavailable_handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=http_request)

    unavailable_client = httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable_handler), base_url="http://model.test"
    )
    unavailable = LlamaCppProvider(base_url="http://model.test", client=unavailable_client)
    with pytest.raises(ModelUnavailableError) as error:
        await unavailable.generate(request())
    assert error.value.retryable is True
    await unavailable_client.aclose()


@pytest.mark.asyncio
async def test_gateway_forwards_question_tag_generation_schema_to_llama_cpp() -> None:
    captured: dict[str, object] = {}

    async def structured_handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"tags":["fractions","comparison"]}'}}],
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(structured_handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)
    gateway = ModelGateway({"llama_cpp": provider}, default_provider="llama_cpp")

    response = await gateway.generate_structured(
        StructuredGenerationRequest(task="question_tag", prompt="Return tags")
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"schema": generate_question_tag_generation_schema()},
    }
    assert response.data is not None
    assert response.data.model_dump() == {"tags": ["fractions", "comparison"]}
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_forwards_subject_neutral_question_tag_v3_schema() -> None:
    captured: dict[str, object] = {}

    async def structured_handler(http_request: httpx.Request) -> httpx.Response:
        body = json.loads(http_request.content)
        captured["body"] = body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"tags":["algorithms","calculation"]}'}}
                ],
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(structured_handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)
    gateway = ModelGateway({"llama_cpp": provider}, default_provider="llama_cpp")

    response = await gateway.generate_structured(
        StructuredGenerationRequest(task="question_tag_v3", prompt="Return tags")
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"schema": generate_subject_neutral_question_tag_generation_schema()},
    }
    assert response.data is not None
    assert response.data.model_dump() == {"tags": ["algorithms", "calculation"]}
    assert response.validation is not None and response.validation.valid
    await client.aclose()


@pytest.mark.asyncio
async def test_llama_cpp_malformed_provider_envelope_is_normalized() -> None:
    async def malformed_handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []}, request=http_request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(malformed_handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)

    with pytest.raises(ModelResponseError) as error:
        await provider.generate_structured(
            StructuredGenerationRequest(
                task="structured", prompt="Return JSON", schema={"type": "object"}
            )
        )

    assert error.value.code == "MODEL_INVALID_RESPONSE"
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_separates_valid_provider_envelope_from_structured_validation() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"instructional_topics":["Fractions"]}',
                        },
                    }
                ],
                "model": "aaa-slm",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 22,
                    "total_tokens": 62,
                    "prompt_tokens_details": {"cached_tokens": 39},
                },
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)
    gateway = ModelGateway(
        {"llama_cpp": provider}, default_provider="llama_cpp"
    )

    with pytest.raises(StructuredOutputValidationError) as error:
        await gateway.generate_structured(
            StructuredGenerationRequest(
                task="syllabus_unit_extract",
                prompt="Extract the instructional topics.",
            )
        )

    assert error.value.code == "MODEL_VALIDATION_ERROR"
    assert error.value.code != "MODEL_INVALID_RESPONSE"
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_accepts_valid_structured_llama_cpp_response() -> None:
    async def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"items":["Fractions","Decimals"]}',
                        },
                    }
                ],
                "model": "aaa-slm",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 22,
                    "total_tokens": 62,
                    "prompt_tokens_details": {"cached_tokens": 39},
                },
            },
            request=http_request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)
    gateway = ModelGateway(
        {"llama_cpp": provider}, default_provider="llama_cpp"
    )

    response = await gateway.generate_structured(
        StructuredGenerationRequest(
            task="syllabus_unit_extract",
            prompt="Extract the instructional topics.",
        )
    )

    assert response.data is not None
    assert response.data.model_dump() == {"items": ["Fractions", "Decimals"]}
    assert response.validation is not None
    assert response.validation.valid is True
    assert response.usage is not None
    assert response.usage.total_tokens == 62
    await client.aclose()


@pytest.mark.asyncio
async def test_llama_cpp_timeout_is_normalized() -> None:
    async def timeout_handler(http_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=http_request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler), base_url="http://model.test"
    )
    provider = LlamaCppProvider(base_url="http://model.test", client=client)

    with pytest.raises(ModelTimeoutError) as error:
        await provider.generate(request())

    assert error.value.provider == "llama_cpp"
    await client.aclose()


def test_configuration_selects_fake_for_mock_and_llama_for_cpu() -> None:
    mock_settings = Settings(_env_file=None)
    mock_gateway = create_model_gateway(mock_settings)
    assert mock_gateway.provider_names == ("fake",)

    llama_settings = Settings(_env_file=None, aaa_profile="cpu")
    llama_gateway = create_model_gateway(llama_settings)
    assert llama_gateway.provider_names == ("llama_cpp",)
