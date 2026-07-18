"""Gemini LLM provider implementation (Sprint 3 Phase A).

Wraps the google-genai SDK behind the BaseProvider interface.
The application must never call google-genai directly.
"""

from __future__ import annotations

import logging
import asyncio

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


class GeminiProvider(BaseProvider):
    """Provider implementation for Google Gemini models.

    Uses the ``google-genai`` SDK. Configured via ``ProviderConfig``.
    """

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._client = None
        self._provider_name = "gemini"
        self._capabilities = {
            ModelCapability.CHAT,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.STREAMING,
        }

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self._capabilities

    def _lazy_client(self):
        """Initialize the google-genai client on first use (lazy import)."""
        if self._client is not None:
            return self._client
        try:
            from google import genai

            self._client = genai.Client()
        except ImportError:
            raise ProviderError(
                "google-genai package not installed",
                provider=self.provider_name,
            )
        except Exception as exc:
            raise ProviderError(
                f"Failed to initialize Gemini client: {exc}",
                provider=self.provider_name,
                cause=exc,
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
        client = self._lazy_client()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        max_attempts = self.config.retry_count + 1

        config_kwargs = {
            "temperature": temp,
            "max_output_tokens": tokens
        }

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await asyncio.to_thread(
                    lambda: client.models.generate_content(
                        model=self.config.model_name,
                        contents=[{"role": "user", "parts": [{"text": prompt}]}],
                        config=config_kwargs,
                    )
                )

                if response is None or response.text is None:
                    raise ProviderError(
                        "Gemini returned empty response",
                        provider=self.provider_name,
                    )

                return ProviderResponse(
                    content=response.text,
                    model_used=self.config.model_name,
                    finish_reason=str(getattr(response, "finish_reason", "stop")),
                    usage=None,
                    raw={"candidates": getattr(response, "candidates", None)},
                )

            except (ProviderError, ProviderTimeoutError, ProviderRateLimitError):
                raise
            except Exception as exc:
                last_exc = exc
                exc_str = str(exc).lower()
                # Re-raise immediately for timeout/rate-limit
                if "timeout" in exc_str or "deadline" in exc_str:
                    raise ProviderTimeoutError(
                        provider=self.provider_name,
                        timeout_seconds=self.config.timeout_seconds,
                    ) from exc
                if "429" in exc_str or "rate" in exc_str or "resource_exhausted" in exc_str:
                    raise ProviderRateLimitError(provider=self.provider_name) from exc

                if attempt < max_attempts:
                    delay = 2 ** attempt  # exponential backoff: 2s, 4s, 8s
                    LOGGER.warning(
                        "Gemini attempt %d/%d failed, retrying in %ds: %s",
                        attempt, max_attempts, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    LOGGER.error(
                        "Gemini all %d attempts exhausted: %s",
                        max_attempts, exc,
                    )

        # All attempts exhausted
        raise ProviderError(
            f"Gemini generation failed after {max_attempts} attempts: {last_exc}",
            provider=self.provider_name,
            cause=last_exc,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """Gemini supports native structured output via response_schema config."""
        client = self._lazy_client()
        temp = temperature if temperature is not None else self.config.temperature

        try:
            import asyncio

            config_kwargs = {
                "temperature": temp,
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            }

            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            response = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model=self.config.model_name,
                    contents=[{"role": "user", "parts": [{"text": full_prompt}]}],
                    config=config_kwargs,
                )
            )

            if response is None or response.text is None:
                raise ProviderError(
                    "Gemini returned empty structured response",
                    provider=self.provider_name,
                )

            return ProviderResponse(
                content=response.text,
                model_used=self.config.model_name,
                finish_reason="stop",
                usage=None,
                raw=None,
            )

        except ProviderError:
            raise
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "deadline" in exc_str:
                raise ProviderTimeoutError(
                    provider=self.provider_name,
                    timeout_seconds=self.config.timeout_seconds,
                ) from exc
            if "429" in exc_str or "rate" in exc_str or "resource_exhausted" in exc_str:
                raise ProviderRateLimitError(provider=self.provider_name) from exc
            raise ProviderError(
                f"Gemini structured generation failed: {exc}",
                provider=self.provider_name,
                cause=exc,
            )
