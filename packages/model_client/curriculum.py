"""Small vendor-neutral curriculum provider interface and offline deterministic fake."""

from typing import Literal, Protocol

from packages.domain.curriculum import (
    GeneratedElement,
    GenerationInput,
    GenerationOutput,
    element_id,
)
from packages.domain.extraction import NodeType
from packages.domain.models import VersionStamp


class ProviderError(Exception):
    """Messages never cross the application boundary; only retryability is interpreted."""

    def __init__(self, *, retryable: bool = True):
        self.retryable = retryable
        super().__init__("Curriculum provider failed")


class CurriculumProvider(Protocol):
    @property
    def versions(self) -> VersionStamp: ...

    async def generate(self, request: GenerationInput) -> bytes:
        """Return untrusted UTF-8 JSON conforming to GenerationOutput, validated by the caller."""
        ...


class FakeProvider:
    """Copy source leaf headings into topics; no invented prose, model calls or randomness."""

    @property
    def versions(self) -> VersionStamp:
        return VersionStamp(model_id="fake-curriculum-v1", adapter_version="curriculum-v1",
                            prompt_version="syllabus-unit-v1", retrieval_version="not-used",
                            mastery_policy_version="not-used", planner_policy_version="not-used")

    async def generate(self, request: GenerationInput) -> bytes:
        parents = {section.parent_id for section in request.sections}
        elements = []
        for section in request.sections:
            if section.id not in parents:
                generated_type: Literal["TOPIC", "SUBTOPIC"] = ("SUBTOPIC" if section.type in {
                    NodeType.TOPIC, NodeType.SUBTOPIC,
                } else "TOPIC")
                key = "generated-subtopic" if generated_type == "SUBTOPIC" else "generated-topic"
                elements.append(GeneratedElement(
                    id=element_id(request.draft_id, section.id, key), key=key,
                    type=generated_type, title=f"{section.title} practice",
                    parent_id=element_id(request.draft_id, section.id),
                    source_node_id=section.id, sources=[section.source],
                ))
        return GenerationOutput(schema_version="curriculum-unit-v1",
                                elements=elements).model_dump_json().encode()
