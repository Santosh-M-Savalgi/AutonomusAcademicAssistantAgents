"""Provider-neutral model client contracts and deterministic test provider."""

from packages.model_client.contracts import (
    ChatMessage,
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    ModelMetadata,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredValidationInfo,
    UsageStats,
)
from packages.model_client.errors import (
    ModelClientError,
    ModelProviderError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputValidationError,
)
from packages.model_client.fake import FakeProvider
from packages.model_client.policies import (
    AdmissionRejectedError,
    CircuitOpenError,
    CircuitState,
    Lane,
    PriorityAdmission,
    RetryPolicy,
)
from packages.model_client.protocols import ModelGatewayProtocol, ModelProvider
from packages.model_client.schema import (
    StructuredSchemaError,
    generate_json_schema,
    generate_subject_neutral_question_tag_generation_schema,
    stable_schema_json,
)
from packages.model_client.tasks import (
    QuestionTagResult,
    SubjectNeutralQuestionTagResult,
    default_task_registry,
)
from packages.model_client.taskspec import (
    TaskGenerationDefaults,
    TaskSpec,
    TaskSpecError,
    TaskSpecRegistry,
    ValidationPolicy,
)
from packages.model_client.validation import validate_structured_response
from packages.model_client.vocabularies import (
    QUESTION_TAG_VOCABULARY,
    SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY,
    QuestionTagVocabulary,
    QuestionTagVocabularyEntry,
)

__all__ = [
    "ChatMessage",
    "FakeProvider",
    "GenerationChunk",
    "GenerationRequest",
    "GenerationResponse",
    "ModelClientError",
    "ModelGatewayProtocol",
    "ModelMetadata",
    "ModelProvider",
    "ModelProviderError",
    "ModelResponseError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "QUESTION_TAG_VOCABULARY",
    "SUBJECT_NEUTRAL_QUESTION_TAG_VOCABULARY",
    "QuestionTagResult",
    "SubjectNeutralQuestionTagResult",
    "QuestionTagVocabulary",
    "QuestionTagVocabularyEntry",
    "AdmissionRejectedError",
    "CircuitOpenError",
    "CircuitState",
    "Lane",
    "PriorityAdmission",
    "RetryPolicy",
    "StructuredSchemaError",
    "StructuredGenerationRequest",
    "StructuredGenerationResponse",
    "StructuredOutputValidationError",
    "StructuredValidationInfo",
    "TaskGenerationDefaults",
    "TaskSpec",
    "TaskSpecError",
    "TaskSpecRegistry",
    "UsageStats",
    "ValidationPolicy",
    "default_task_registry",
    "generate_json_schema",
    "generate_subject_neutral_question_tag_generation_schema",
    "stable_schema_json",
    "validate_structured_response",
]
