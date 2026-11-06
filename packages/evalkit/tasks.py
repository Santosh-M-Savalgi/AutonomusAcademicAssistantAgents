"""Evaluation-only TaskSpec definitions that do not alter production tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.model_client.taskspec import TaskGenerationDefaults, TaskSpec, ValidationPolicy


class GroundingResult(BaseModel):
    """Source identifiers cited by the model for the grounding fixture."""

    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] = Field(max_length=32)


GROUNDING_TASK_SPEC = TaskSpec(
    name="eval_lesson_grounding",
    version="eval-lesson-grounding-v1",
    output_mode="structured",
    output_model=GroundingResult,
    generation=TaskGenerationDefaults(),
    validation=ValidationPolicy(max_retries=1, strict=True),
    metadata={"scope": "evaluation-only", "benchmark": "lesson-grounding"},
)
