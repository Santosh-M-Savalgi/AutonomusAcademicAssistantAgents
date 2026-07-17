"""Retrieval API endpoints (Sprint 4 Phase H).

POST /api/v2/retrieval/search  — semantic search over indexed content
POST /api/v2/retrieval/context — retrieve context for a topic (retrieval + context assembly)
POST /api/v2/retrieval/index   — index a document
GET /api/v2/retrieval/status   — retrieval index status/health

Uses the Sprint 4 retrieval pipeline: DocumentProcessor → ChunkingService →
EmbeddingProvider → VectorStoreService → RetrievalService → ContextBuilder.

Reuses dependency injection patterns from Sprint 0-3.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ingestion.chunker import ChunkingService
from app.ingestion.document_processor import DocumentProcessor
from app.ingestion.embedding.base import EmbeddingProvider, EmbeddingConfig
from app.ingestion.embedding_factory import EmbeddingFactory
from app.ingestion.vector_store import VectorStoreService
from app.services.context_builder import ContextBuilder
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


# ── Singleton services ──────────────────────────────────────────────────────


def _get_embedding_provider() -> EmbeddingProvider:
    factory = EmbeddingFactory.from_settings()
    return factory.get_embedding_provider()


def _get_vector_store() -> VectorStoreService:
    return VectorStoreService()


def _get_retrieval_service() -> RetrievalService:
    return RetrievalService(
        vector_store=_get_vector_store(),
        embedding_provider=_get_embedding_provider(),
    )


def _get_context_builder() -> ContextBuilder:
    return ContextBuilder()


def _get_document_processor() -> DocumentProcessor:
    return DocumentProcessor()


def _get_chunking_service() -> ChunkingService:
    return ChunkingService(strategy="section", chunk_size=1000, overlap=200)


# ── Request / Response schemas ──────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query text")
    top_k: int = Field(10, ge=1, le=100, description="Maximum number of results")
    min_score: float = Field(0.0, ge=0.0, le=1.0, description="Minimum similarity threshold")
    where: dict | None = Field(None, description="Optional metadata filter")
    syllabus_id: str | None = Field(None, description="Optional syllabus ID to scope search")


class RetrievedChunkResponse(BaseModel):
    chunk_id: str
    content: str
    score: float
    headings: list[str] = []
    topic_tags: list[str] = []
    source_type: str = ""


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunkResponse]
    total_results: int
    filtered_by_threshold: int = 0


class ContextRequest(BaseModel):
    topic_name: str = Field(..., description="Name of the topic")
    topic_description: str = Field("", description="Description of the topic")
    prerequisite_topics: list[dict] = Field(default_factory=list, description="Prerequisite topic data")
    mastery_score: float = Field(0.0, ge=0.0, le=1.0, description="Current mastery score")
    top_k: int = Field(10, ge=1, le=50, description="Number of chunks to retrieve")
    max_context_tokens: int = Field(2000, ge=100, le=8000, description="Max context token budget")


class ContextResponse(BaseModel):
    topic_name: str
    relevant_chunks_count: int
    prerequisite_summaries_count: int
    estimated_tokens: int
    formatted_context: str


class IndexRequest(BaseModel):
    source_type: str = Field("plain_text", description="plain_text | markdown | syllabus")
    content: str = Field(..., description="Document content to index")
    file_name: str = Field("", description="Optional file name for metadata")
    chunking_strategy: str = Field("section", description="fixed | section | topic")


class IndexResponse(BaseModel):
    document_id: str
    chunk_count: int
    source_type: str
    content_hash: str


class StatusResponse(BaseModel):
    documents_count: int
    chunks_count: int
    is_valid: bool
    issues: list[str] = []


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResponse)
async def retrieval_search(request: SearchRequest) -> SearchResponse:
    """Semantic search over indexed document chunks."""
    service = _get_retrieval_service()

    if request.syllabus_id:
        result = await service.search_by_syllabus(
            query=request.query,
            syllabus_id=request.syllabus_id,
            top_k=request.top_k,
            min_score=request.min_score,
        )
    else:
        result = await service.search(
            query=request.query,
            top_k=request.top_k,
            where=request.where,
            min_score=request.min_score,
        )

    return SearchResponse(
        query=result.query,
        results=[
            RetrievedChunkResponse(
                chunk_id=c.chunk_id,
                content=c.content[:500],  # Truncate for API responses
                score=c.score,
                headings=c.headings,
                topic_tags=c.topic_tags,
                source_type=c.source_type,
            )
            for c in result.chunks
        ],
        total_results=result.total_results,
        filtered_by_threshold=result.filtered_by_threshold,
    )


@router.post("/context", response_model=ContextResponse)
async def retrieval_context(request: ContextRequest) -> ContextResponse:
    """Retrieve and assemble context for a topic.

    Performs retrieval, then context assembly — ready for consumption
    by TutorService or QuizService prompt builders.
    """
    service = _get_retrieval_service()
    builder = ContextBuilder(max_context_tokens=request.max_context_tokens)

    # Perform prerequisite-aware retrieval
    retrieval_result = await service.search_with_prerequisites(
        topic_name=request.topic_name,
        topic_description=request.topic_description,
        prerequisite_topics=request.prerequisite_topics,
        top_k=request.top_k,
    )

    # Build tutor context
    tutor_ctx = builder.build_tutor_context(
        topic_name=request.topic_name,
        topic_description=request.topic_description,
        retrieval_result=retrieval_result,
        mastery_score=request.mastery_score,
    )

    # Format for prompt injection
    formatted = builder.format_tutor_context_for_prompt(tutor_ctx)

    return ContextResponse(
        topic_name=request.topic_name,
        relevant_chunks_count=len(tutor_ctx.relevant_chunks),
        prerequisite_summaries_count=len(tutor_ctx.prerequisite_summaries),
        estimated_tokens=tutor_ctx.estimated_tokens,
        formatted_context=formatted,
    )


@router.post("/index", response_model=IndexResponse)
async def retrieval_index(request: IndexRequest) -> IndexResponse:
    """Index a document for retrieval.

    Processes the document through:
        DocumentProcessor → ChunkingService → EmbeddingProvider → VectorStoreService
    """
    processor = _get_document_processor()
    chunker = _get_chunking_service()
    embedding_provider = _get_embedding_provider()
    vector_store = _get_vector_store()

    # Process document
    doc = processor.process_text(
        text=request.content,
        source_type=request.source_type,
        file_name=request.file_name,
    )

    # Chunk
    chunker = ChunkingService(strategy=request.chunking_strategy, chunk_size=1000, overlap=200)
    chunks = chunker.chunk(doc)

    # Embed and index
    chunk_texts = [c.content for c in chunks]
    embedding_results = await embedding_provider.embed_batch(chunk_texts)
    embeddings = [r.embedding for r in embedding_results]

    vector_store.index_chunks(chunks, embeddings)

    # Index document metadata
    vector_store.index_document(
        document_id=doc.id,
        title=doc.metadata.title,
        source_type=doc.metadata.source_type,
        content_hash=doc.metadata.content_hash,
        chunk_count=len(chunks),
    )

    return IndexResponse(
        document_id=doc.id,
        chunk_count=len(chunks),
        source_type=doc.metadata.source_type,
        content_hash=doc.metadata.content_hash,
    )


@router.get("/status", response_model=StatusResponse)
async def retrieval_status() -> StatusResponse:
    """Get retrieval index status."""
    vector_store = _get_vector_store()
    validation = vector_store.validate_index()

    return StatusResponse(
        documents_count=validation.document_count,
        chunks_count=validation.chunk_count,
        is_valid=validation.is_valid,
        issues=validation.issues,
    )
