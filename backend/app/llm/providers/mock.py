"""Mock LLM provider for testing (Sprint 3 Phase A).

Returns deterministic responses — no SDK calls, no API keys needed.
Use in unit tests and CI where real LLM calls are undesirable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.llm.providers.base import (
    BaseProvider,
    ModelCapability,
    ProviderConfig,
    ProviderResponse,
)


@dataclass
class MockResponseRule:
    """A rule mapping prompt patterns to canned responses."""

    prompt_contains: str
    response_text: str
    priority: int = 0


class MockProvider(BaseProvider):
    """Mock LLM provider for deterministic, network-free testing.

    Supports:
    - ``add_rule()`` to register prompt→response mappings.
    - ``clear_rules()`` to reset.
    - Falls back to a default response when no rule matches.

    Example::

        provider = MockProvider()
        provider.add_rule("lesson", "Mock lesson content for testing")
        response = await provider.generate("Generate a lesson on Python")
        assert "Mock lesson content" in response.content
    """

    def __init__(self, config: ProviderConfig | None = None):
        super().__init__(config)
        self._provider_name = "mock"
        self._captabilities = {
            ModelCapability.CHAT,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.STREAMING,
            ModelCapability.EMBEDDING,
        }
        self._rules: list[MockResponseRule] = []
        self._call_history: list[dict] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self._captabilities

    def add_rule(
        self,
        prompt_contains: str,
        response_text: str,
        priority: int = 0,
    ) -> MockResponseRule:
        """Register a canned response for prompts containing the given text.

        Higher priority rules are matched first.
        """
        rule = MockResponseRule(
            prompt_contains=prompt_contains,
            response_text=response_text,
            priority=priority,
        )
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        return rule

    def clear_rules(self) -> None:
        """Remove all registered rules."""
        self._rules.clear()

    def clear_history(self) -> None:
        """Clear the call history."""
        self._call_history.clear()

    @property
    def call_history(self) -> list[dict]:
        """Return a copy of the call history for test assertions."""
        return list(self._call_history)

    def _match(self, prompt: str) -> str | None:
        """Find the best matching rule for a prompt.

        Returns the canned response text or None.
        """
        for rule in self._rules:
            if rule.prompt_contains.lower() in prompt.lower():
                return rule.response_text
        return None

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        matched = self._match(prompt)

        self._call_history.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "matched": matched is not None,
        })

        if matched is not None:
            return ProviderResponse(
                content=matched,
                model_used="mock-model",
                finish_reason="stop",
                usage={"input_tokens": 0, "output_tokens": len(matched.split())},
            )

        return ProviderResponse(
            content="Mock provider default response",
            model_used="mock-model",
            finish_reason="stop",
            usage={"input_tokens": len(prompt.split()), "output_tokens": 5},
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """Mock structured output — tries to return JSON matching the schema."""
        matched = self._match(prompt)

        self._call_history.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "structured": True,
            "matched": matched is not None,
        })

        if matched is not None:
            # Try to parse the matched text as JSON; if it fails, wrap it as JSON
            try:
                json.loads(matched)
                return ProviderResponse(
                    content=matched,
                    model_used="mock-model",
                    finish_reason="stop",
                )
            except (json.JSONDecodeError, TypeError):
                pass

        # Return a simple JSON structure as fallback
        fallback = json.dumps({"response": matched or "default mock response"})
        return ProviderResponse(
            content=fallback,
            model_used="mock-model",
            finish_reason="stop",
        )

    def add_lesson_rule(self, topic: str = "") -> None:
        """Add a rule that returns structured lesson content."""
        self.add_rule(
            "lesson" if not topic else topic,
            json.dumps({
                "topic": topic or "Test Topic",
                "content": f"# {topic or 'Test Topic'}\n\nMock lesson content for testing purposes.",
                "cards": [
                    {"title": "Introduction", "body": "Mock card 1 content"},
                    {"title": "Key Concept", "body": "Mock card 2 content"},
                    {"title": "Summary", "body": "Mock card 3 content"},
                ],
                "estimated_minutes": 5,
            }),
            priority=10,
        )

    def add_quiz_rule(self, topic: str = "") -> None:
        """Add a rule that returns structured quiz content."""
        self.add_rule(
            "quiz" if not topic else topic,
            json.dumps({
                "topic": topic or "Test Topic",
                "questions": [
                    {
                        "id": "q1",
                        "question": "What is the primary concept?",
                        "options": ["Option A", "Option B", "Option C", "Option D"],
                        "correct_answer": "Option A",
                        "difficulty": "easy",
                        "concept_tag": "basics",
                    },
                    {
                        "id": "q2",
                        "question": "Which of the following is correct?",
                        "options": ["Option X", "Option Y", "Option Z", "Option W"],
                        "correct_answer": "Option Y",
                        "difficulty": "medium",
                        "concept_tag": "core",
                    },
                ],
                "total_questions": 2,
            }),
            priority=10,
        )
