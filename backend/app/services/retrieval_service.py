"""Retrieval Service — semantic search and context retrieval (Sprint 4 Phase E).

Responsibilities:
- Semantic search over embedded chunks
- Top-k retrieval with configurable count
- Metadata filtering (by document, topic, section, source type)
- Prerequisite-aware retrieval (include chunks from prerequisite topics)
- Syllabus-aware retrieval (scope search to a specific syllabus)
- Similarity threshold filtering (minimum cosine similarity)

Returns structured ``RetrievalResult`` objects.
Does NOT generate prompts — that's ContextBuilder's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ingestion.embedding.base import EmbeddingProvider
from app.ingestion.vector_store import VectorStoreService


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class RetrievedChunk:
    """A single retrieved chunk with relevance information."""

    chunk_id: str
    document_id: str
    content: str
    score: float  # cosine similarity (higher = more relevant)
    headings: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    source_type: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """Complete retrieval result for a query."""

    query: str
    chunks: list[RetrievedChunk]
    total_results: int
    filtered_by_threshold: int = 0  # number of results removed by similarity threshold
    prerequisite_chunks: list[RetrievedChunk] = field(default_factory=list)


# ── RetrievalService ────────────────────────────────────────────────────────


class RetrievalService:
    """Semantic search and retrieval over indexed content.

    Usage::

        service = RetrievalService(vector_store, embedding_provider)
        result = await service.search("Python lists", top_k=5)
    """

    def __init__(
        self,
        vector_store: VectorStoreService,
        embedding_provider: EmbeddingProvider,
        similarity_threshold: float = 0.3,
    ):
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self.similarity_threshold = similarity_threshold

    async def search(
        self,
        query: str,
        top_k: int = 10,
        where: dict | None = None,
        where_document: dict | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Perform semantic search over indexed chunks.

        Args:
            query: The search query text.
            top_k: Maximum number of results to return.
            where: Optional ChromaDB metadata filter.
            where_document: Optional document-content filter.
            min_score: Minimum similarity score threshold.
                Defaults to ``self.similarity_threshold``.

        Returns:
            A ``RetrievalResult`` with ranked chunks.
        """
        # Embed the query
        embedding_result = await self._embedding_provider.embed_text(query)
        query_embedding = embedding_result.embedding

        # Search vector store
        threshold = min_score if min_score is not None else self.similarity_threshold
        results = self._vector_store.search(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where,
            where_document=where_document,
        )

        # Process results
        chunks: list[RetrievedChunk] = []
        filtered = 0

        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                score = 1.0 - results["distances"][0][i] if results["distances"] else 0.0

                # Apply similarity threshold
                if score < threshold:
                    filtered += 1
                    continue

                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                content = results["documents"][0][i] if results["documents"] else ""

                headings = []
                if metadata and "headings" in metadata and metadata["headings"]:
                    headings = metadata["headings"].split("|")

                topic_tags = []
                if metadata and "topic_tags" in metadata and metadata["topic_tags"]:
                    topic_tags = metadata["topic_tags"].split(",")

                chunk = RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=metadata.get("document_id", "") if metadata else "",
                    content=content,
                    score=score,
                    headings=headings,
                    topic_tags=topic_tags,
                    source_type=metadata.get("source_type", "") if metadata else "",
                    metadata=metadata or {},
                )
                chunks.append(chunk)

        # Sort by score descending
        chunks.sort(key=lambda c: c.score, reverse=True)

        return RetrievalResult(
            query=query,
            chunks=chunks,
            total_results=len(chunks),
            filtered_by_threshold=filtered,
        )

    async def search_by_topic(
        self,
        topic_name: str,
        topic_description: str,
        top_k: int = 10,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Search for content related to a specific topic.

        Uses the topic name + description as the query, then optionally
        filters by topic tags.
        """
        query = f"{topic_name}: {topic_description}" if topic_description else topic_name
        return await self.search(
            query=query,
            top_k=top_k,
            min_score=min_score,
        )

    async def search_with_prerequisites(
        self,
        topic_name: str,
        topic_description: str,
        prerequisite_topics: list[dict],
        top_k: int = 10,
        prereq_top_k: int = 5,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Search for content including prerequisite context.

        Performs two searches:
        1. Main search for the current topic
        2. Supplementary search for prerequisite topics

        Returns:
            A ``RetrievalResult`` with both primary and prerequisite chunks.
        """
        # Main search
        main_result = await self.search_by_topic(
            topic_name=topic_name,
            topic_description=topic_description,
            top_k=top_k,
            min_score=min_score,
        )

        # Prerequisite search
        prereq_names = [p.get("name", "") for p in prerequisite_topics if p.get("name")]
        prereq_chunks: list[RetrievedChunk] = []

        if prereq_names:
            prereq_query = " | ".join(prereq_names)
            prereq_result = await self.search(
                query=prereq_query,
                top_k=prereq_top_k,
                min_score=min_score,
            )
            prereq_chunks = prereq_result.chunks

        main_result.prerequisite_chunks = prereq_chunks
        return main_result

    async def search_by_syllabus(
        self,
        query: str,
        syllabus_id: str,
        top_k: int = 10,
        min_score: float | None = None,
    ) -> RetrievalResult:
        """Search within a specific syllabus scope.

        Filters chunks by document_id or syllabus metadata.
        """
        return await self.search(
            query=query,
            top_k=top_k,
            where={"syllabus_id": syllabus_id},
            min_score=min_score,
        )

    async def search_chunks_by_ids(
        self,
        chunk_ids: list[str],
    ) -> list[RetrievedChunk]:
        """Retrieve specific chunks by their IDs.

        Used for re-ranking or expanding context from specific source chunks.
        """
        collection = self._vector_store.chunks_collection
        result = collection.get(ids=chunk_ids)

        chunks: list[RetrievedChunk] = []
        if result["ids"]:
            for i, chunk_id in enumerate(result["ids"]):
                metadata = result["metadatas"][i] if result["metadatas"] else {}
                content = result["documents"][i] if result["documents"] else ""

                headings = []
                if metadata and "headings" in metadata and metadata["headings"]:
                    headings = metadata["headings"].split("|")

                topic_tags = []
                if metadata and "topic_tags" in metadata and metadata["topic_tags"]:
                    topic_tags = metadata["topic_tags"].split(",")

                chunks.append(RetrievedChunk(
                    chunk_id=chunk_id,
                    document_id=metadata.get("document_id", "") if metadata else "",
                    content=content,
                    score=1.0,  # exact retrieval, no similarity
                    headings=headings,
                    topic_tags=topic_tags,
                    source_type=metadata.get("source_type", "") if metadata else "",
                    metadata=metadata or {},
                ))

        return chunks
