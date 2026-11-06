"""Normalized model-client errors shared by providers and the gateway."""

from __future__ import annotations


class ModelClientError(Exception):
    """Base error whose public fields are safe for gateway callers to inspect."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class ModelTimeoutError(ModelClientError):
    """A provider or gateway operation exceeded its request deadline."""

    def __init__(self, *, provider: str | None = None) -> None:
        super().__init__(
            "Model generation timed out",
            code="MODEL_TIMEOUT",
            retryable=True,
            provider=provider,
        )


class ModelUnavailableError(ModelClientError):
    """A provider could not be reached or is not ready."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            "Model provider is unavailable",
            code="MODEL_UNAVAILABLE",
            retryable=True,
            provider=provider,
            status_code=status_code,
        )


class ModelProviderError(ModelClientError):
    """A provider returned a failure that is not a transport timeout."""

    def __init__(
        self,
        message: str = "Model provider failed",
        *,
        provider: str | None = None,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            code="MODEL_PROVIDER_ERROR",
            retryable=retryable,
            provider=provider,
            status_code=status_code,
        )


class ModelResponseError(ModelClientError):
    """A provider response did not satisfy the transport contract."""

    def __init__(self, *, provider: str | None = None) -> None:
        super().__init__(
            "Model provider returned an invalid response",
            code="MODEL_INVALID_RESPONSE",
            retryable=False,
            provider=provider,
        )


class StructuredOutputValidationError(ModelClientError):
    """Untrusted structured output failed its bounded validation attempts."""

    def __init__(
        self,
        *,
        task: str,
        attempts: int,
        errors: list[str],
        provider: str | None = None,
    ) -> None:
        self.task = task
        self.attempts = attempts
        self.errors = errors
        super().__init__(
            f"Structured output failed validation for task {task!r}",
            code="MODEL_VALIDATION_ERROR",
            retryable=False,
            provider=provider,
        )
