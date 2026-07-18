"""Graph node: retrieval.

Wraps the existing RetrievalService + ContextBuilder as a LangGraph node.
This is where retrieval_enabled=True finally gets turned on.

Input: state.current_topic_name, state.current_topic_description
Output: state.retrieval_context (dict-serialized RetrievalResult)
"""

from __future__ import annotations

import logging

from app.graph.state import AAAState
from app.ingestion.embedding_factory import EmbeddingFactory
from app.ingestion.vector_store import VectorStoreService
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


def _log_state(node: str, event: str, state: AAAState) -> None:
    """Log key state fields for tracing state flow through the graph."""
    logger.info(
        "STATE %s/%s: learning_goal=%r syllabus_id=%r topics=%d phase=%r error=%r",
        node, event,
        state.get("learning_goal", "")[:80],
        state.get("syllabus_id", "")[:36],
        len(state.get("topics", [])),
        state.get("phase"),
        state.get("error"),
    )


async def retrieve_context_node(state: AAAState) -> AAAState:
    """Retrieve relevant context chunks for the current topic.

    Enriches the state with retrieval context used by the tutor node
    to ground lesson generation in real search results.
    """
    _log_state("retrieve", "enter", state)

    topic_name = state.get("current_topic_name", "")
    topic_description = state.get("current_topic_description", "")

    if not topic_name:
        state["error"] = "No topic name for retrieval"
        state["phase"] = "complete"
        _log_state("retrieve", "exit(no_topic)", state)
        return state

    try:
        # Build retrieval pipeline from existing services
        embedding_provider = EmbeddingFactory.from_settings().get_embedding_provider()
        vector_store = VectorStoreService()
        retrieval_service = RetrievalService(vector_store, embedding_provider)
        context_builder = ContextBuilder()

        # Search
        result = await retrieval_service.search(
            query=f"{topic_name} {topic_description}",
            top_k=5,
        )

        # Build tutor context
        tutor_ctx = context_builder.build_tutor_context(
            topic_name=topic_name,
            topic_description=topic_description,
            retrieval_result=result,
            mastery_score=state.get("mastery_scores", {}).get(
                state.get("current_topic_id", ""), 0.0
            ),
        )

        # Serialize for checkpoint storage
        state["retrieval_context"] = {
            "chunks": [
                {
                    "content": c.content,
                    "score": c.score,
                    "headings": c.headings,
                    "topic_tags": c.topic_tags,
                }
                for c in result.chunks
            ],
            "formatted_prompt": context_builder.format_tutor_context_for_prompt(tutor_ctx),
        }

        state["phase"] = "tutor"
        logger.info(
            "Retrieval complete for '%s': %d chunks",
            topic_name,
            len(result.chunks),
        )
        _log_state("retrieve", "exit(success)", state)

    except Exception as exc:
        # Retrieval failure is non-blocking — tutor can still generate
        logger.warning("Retrieval failed for '%s': %s", topic_name, exc)
        state["retrieval_context"] = None
        state["phase"] = "tutor"
        _log_state("retrieve", "exit(fallback)", state)

    return state
