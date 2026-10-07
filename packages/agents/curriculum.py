"""Bounded LangGraph per-section generation; providers and validated outputs only, no DB I/O."""

from typing import Any, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from packages.curriculum.drafts import generation_inputs, validate_provider_output
from packages.domain.curriculum import GenerationOutput
from packages.domain.extraction import ExtractionResult
from packages.model_client.curriculum import CurriculumProvider


class GenerationState(TypedDict):
    outputs: list[str]


async def generate_sections(
    provider: CurriculumProvider, extraction: ExtractionResult, draft_id: UUID, attempt: int,
    saver: BaseCheckpointSaver[Any], *, max_sections: int, max_output_bytes: int,
) -> list[GenerationOutput]:
    requests = generation_inputs(draft_id, extraction)
    if len(requests) > max_sections or any(len(r.sections) > 64 for r in requests):
        raise ValueError("Curriculum input limit exceeded")
    if not requests:
        return []
    # Attempts have separate threads: stale work cannot corrupt a replacement's checkpoints.
    # Resume only a fully validated prefix, never trust even internally persisted JSON blindly.
    prefix: list[str] = []
    for previous in range(attempt, 0, -1):
        checkpoint = await saver.aget_tuple({
            "configurable": {"thread_id": f"draft:{draft_id}:{previous}"},
        })
        if checkpoint:
            values = checkpoint.checkpoint.get("channel_values", {}).get("outputs", [])
            if isinstance(values, list) and len(values) <= len(requests):
                for request, value in zip(requests, values, strict=False):
                    if not isinstance(value, str) or len(value.encode()) > max_output_bytes:
                        raise ValueError("Invalid saved provider output")
                    validate_provider_output(request, value.encode())
                prefix = values
                break

    async def generate(state: GenerationState) -> GenerationState:
        position = len(state["outputs"])
        if position == len(requests):
            return state
        content = await provider.generate(requests[position])
        if not isinstance(content, bytes) or len(content) > max_output_bytes:
            raise ValueError("Invalid provider response size/type")
        output = validate_provider_output(requests[position], content)
        return {"outputs": [*state["outputs"], output.model_dump_json()]}

    def next_step(state: GenerationState) -> str:
        return END if len(state["outputs"]) == len(requests) else "generate"

    builder = StateGraph(GenerationState)
    builder.add_node("generate", generate)
    builder.add_edge(START, "generate")
    builder.add_conditional_edges("generate", next_step)
    graph = builder.compile(checkpointer=saver)
    config: RunnableConfig = {
        "configurable": {"thread_id": f"draft:{draft_id}:{attempt}"},
        "recursion_limit": max_sections + 2, "callbacks": [],
    }
    result = await graph.ainvoke({"outputs": prefix}, config, durability="sync")
    return [GenerationOutput.model_validate_json(value) for value in result["outputs"]]
