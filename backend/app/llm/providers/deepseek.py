"""DeepSeek LLM provider — OpenAI-compatible endpoint via httpx.

DeepSeek v4 exposes an OpenAI-compatible chat completions API at
``https://api.deepseek.com/v1``. This provider uses ``httpx`` (already
a project dependency) instead of the ``openai`` package to avoid adding
a new heavyweight dependency for a single API call.

Model: ``deepseek-v4-flash`` (not the legacy ``deepseek-chat`` or
``deepseek-reasoner`` names, which deprecate 2026-07-24).

Environment:
    DEEPSEEK_API_KEY — required; startup fails if LLM_PROVIDER=deepseek
                       and this is unset.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.llm.providers.base import (
    BaseProvider,
    ModelCapability,
    ProviderConfig,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)

LOGGER = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_CHAT_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekProvider(BaseProvider):
    """Provider for DeepSeek v4 models via OpenAI-compatible API.

    Uses ``httpx.AsyncClient`` for all requests. No ``openai`` package
    required.
    """

    def __init__(self, config: ProviderConfig | None = None):
        if config is None:
            config = ProviderConfig(model_name=DEFAULT_MODEL)
        elif not config.model_name or config.model_name in (
            "gemini-2.5-flash",
            "deepseek-chat",
            "deepseek-reasoner",
        ):
            config.model_name = DEFAULT_MODEL
        super().__init__(config)
        self._provider_name = "deepseek"
        self._capabilities = {
            ModelCapability.CHAT,
            ModelCapability.STRUCTURED_OUTPUT,
        }
        self._api_key: str | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self._capabilities

    def _get_api_key(self) -> str:
        """Return the API key, reading from env if not injected."""
        if self._api_key:
            return self._api_key
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise ProviderError(
                "DEEPSEEK_API_KEY is not set. "
                "Set it in .env or the environment.",
                provider=self.provider_name,
            )
        self._api_key = key
        return key

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (or create) the shared httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=DEEPSEEK_BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._get_api_key()}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.config.timeout_seconds),
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None
    ) -> ProviderResponse:
        """Send a chat completion request to DeepSeek."""
        client = await self._get_client()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        max_attempts = self.config.retry_count + 1

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens
        }

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(
                    "/chat/completions",
                    json=payload,
                )

                if response.status_code == 401:
                    raise ProviderError(
                        "DeepSeek authentication failed — check DEEPSEEK_API_KEY",
                        provider=self.provider_name,
                    )
                if response.status_code == 429:
                    raise ProviderRateLimitError(
                        provider=self.provider_name,
                    )
                if response.status_code >= 500:
                    raise ProviderError(
                        f"DeepSeek server error (HTTP {response.status_code})",
                        provider=self.provider_name,
                    )

                response.raise_for_status()
                data = response.json()

                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")

                if not content:
                    raise ProviderError(
                        "DeepSeek returned empty response",
                        provider=self.provider_name,
                    )

                return ProviderResponse(
                    content=content,
                    model_used=data.get("model", self.config.model_name),
                    finish_reason=choice.get("finish_reason", "stop"),
                    usage=data.get("usage"),
                    raw=data,
                )

            except (ProviderError, ProviderTimeoutError, ProviderRateLimitError):
                raise
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    provider=self.provider_name,
                    timeout_seconds=self.config.timeout_seconds,
                ) from exc
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc).lower()
                if "timeout" in exc_str or "timed out" in exc_str:
                    raise ProviderTimeoutError(
                        provider=self.provider_name,
                        timeout_seconds=self.config.timeout_seconds,
                    ) from exc
                if "429" in exc_str or "rate" in exc_str:
                    raise ProviderRateLimitError(provider=self.provider_name) from exc

                if attempt < max_attempts:
                    delay = 2 ** attempt
                    LOGGER.warning(
                        "DeepSeek attempt %d/%d failed, retrying in %ds: %s",
                        attempt, max_attempts, delay, exc,
                    )
                    import asyncio
                    await asyncio.sleep(delay)
                else:
                    LOGGER.error(
                        "DeepSeek all %d attempts exhausted: %s",
                        max_attempts, exc,
                    )

        raise ProviderError(
            f"DeepSeek request failed after {max_attempts} attempts: {last_exc}",
            provider=self.provider_name,
        )
