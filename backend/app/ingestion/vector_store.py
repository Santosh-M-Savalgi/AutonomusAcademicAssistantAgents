"""ChromaDB vector store integration for Sprint 4 (Sprint 4 Phase D).

Reuses the existing ChromaDB singleton from ``app.db.chroma_client``.
Provides document indexing, topic indexing, incremental updates,
metadata filtering, deletion support, and index validation.

Does NOT duplicate storage logic — all existing Sprint 0-3 ChromaDB
collections are preserved and reused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import chromadb
from chromadb import Collection

from app.db.chroma_client import get_chroma_client

# ── Collection names ────────────────────────────────────────────────────────


DOCUMENTS_COLLECTION = "sprint4_documents"
CHUNKS_COLLECTION = "sprint4_chunks"
TOPIC_EMBEDDINGS_COLLECTION = "topic_embeddings"


# ── Domain types ────────────────────────────────────────────────────────────


@dataclass
class IndexedDocument:
    """Metadata about an indexed document."""

    document_id: str
    chunk_count: int
    content_hash: str
    source_type: str
    title: str


@dataclass
class IndexValidationResult:
    """Result of validating an index."""

    is_valid: bool
    document_count: int
    chunk_count: int
    missing_documents: list[str]
    issues: list[str] = field(default_factory=list)


# ── VectorStoreService ──────────────────────────────────────────────────────


class VectorStoreService:
    """ChromaDB-backed vector store for document chunks and topic embeddings.

    Manages three collections:
    1. ``sprint4_documents``: document-level metadata (title, source type, hash)
    2. ``sprint4_chunks``: embedded chunks with full metadata
    3. ``topic_embeddings``: topic-level embeddings (reuses existing schema)

    Usage::

        store = VectorStoreService()
        await store.index_chunks(chunks, embedding_provider)
        results = store.search("python lists", n_results=5)
    """

    def __init__(self, client: chromadb.ClientAPI | None = None):
        self._client = client or get_chroma_client()

    # ── Collection access ───────────────────────────────────────────────────

    def _get_or_create_collection(self, name: str) -> Collection:
        """Get an existing collection or create a new one."""
        try:
            return self._client.get_collection(name)
        except ValueError:
            return self._client.create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def documents_collection(self) -> Collection:
        return self._get_or_create_collection(DOCUMENTS_COLLECTION)

    @property
    def chunks_collection(self) -> Collection:
        return self._get_or_create_collection(CHUNKS_COLLECTION)

    @property
    def topic_collection(self) -> Collection:
        return self._get_or_create_collection(TOPIC_EMBEDDINGS_COLLECTION)

    # ── Document indexing ───────────────────────────────────────────────────

    def index_document(
        self,
        document_id: str,
        title: str,
        source_type: str,
        content_hash: str,
        chunk_count: int = 0,
    ) -> None:
        """Index document-level metadata.

        Uses upsert semantics: if a document with the same ID exists,
        it is replaced.
        """
        collection = self.documents_collection
        collection.upsert(
            ids=[document_id],
            embeddings=[[0.0]],  # placeholder, documents collection doesn't need real embeddings
            metadatas=[{
                "title": title,
                "source_type": source_type,
                "content_hash": content_hash,
                "chunk_count": chunk_count,
                "indexed_at": str(uuid.uuid4()),
            }],
        )

    def get_document(self, document_id: str) -> dict | None:
        """Retrieve document metadata by ID."""
        collection = self.documents_collection
        try:
            result = collection.get(ids=[document_id])
            if result["ids"]:
                return {
                    "id": result["ids"][0],
                    "metadata": result["metadatas"][0] if result["metadatas"] else {},
                }
        except Exception:
            pass
        return None

    def delete_document(self, document_id: str) -> None:
        """Delete a document and all its chunks.

        Deletes from both the documents collection and the chunks collection.
        """
        # Delete document metadata
        try:
            self.documents_collection.delete(ids=[document_id])
        except Exception:
            pass

        # Delete all chunks belonging to this document
        try:
            # Use metadata filter to find chunks by document_id
            chunks = self.chunks_collection.get(
                where={"document_id": document_id},
            )
            if chunks["ids"]:
                self.chunks_collection.delete(ids=chunks["ids"])
        except Exception:
            pass

    # ── Chunk indexing ──────────────────────────────────────────────────────

    def index_chunks(
        self,
        chunks: list,
        embeddings: list[list[float]],
    ) -> None:
        """Index a batch of chunks with their embeddings.

        Args:
            chunks: List of Chunk objects (from the chunker module).
            embeddings: List of embedding vectors for each chunk.
        """
        if not chunks:
            return

        if len(chunks) != len(embeddings):
            msg = f"Chunk count ({len(chunks)}) must match embedding count ({len(embeddings)})"
            raise ValueError(msg)

        collection = self.chunks_collection

        ids = [c.id for c in chunks]
        metadatas = []
        documents = []

        for chunk in chunks:
            metadata = dict(chunk.metadata)
            metadata["document_id"] = chunk.document_id
            metadata["chunk_index"] = chunk.chunk_index
            metadata["total_chunks"] = chunk.total_chunks
            if chunk.headings:
                metadata["headings"] = "|".join(chunk.headings)
            if chunk.section_id:
                metadata["section_id"] = chunk.section_id
            if chunk.topic_tags:
                metadata["topic_tags"] = ",".join(chunk.topic_tags)

            metadatas.append(metadata)
            documents.append(chunk.content)

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    # ── Topic indexing ──────────────────────────────────────────────────────

    def index_topic(
        self,
        topic_id: str,
        topic_name: str,
        topic_description: str,
        embedding: list[float],
    ) -> None:
        """Index a topic with its embedding."""
        collection = self.topic_collection
        collection.upsert(
            ids=[topic_id],
            embeddings=[embedding],
            metadatas=[{
                "topic_name": topic_name,
                "topic_description": topic_description,
            }],
            documents=[f"{topic_name}: {topic_description}"],
        )

    def delete_topic(self, topic_id: str) -> None:
        """Delete a topic embedding."""
        try:
            self.topic_collection.delete(ids=[topic_id])
        except Exception:
            pass

    # ── Search ──────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict | None = None,
        where_document: dict | None = None,
    ) -> dict:
        """Search chunks by embedding similarity.

        Args:
            query_embedding: The embedding vector to search with.
            n_results: Maximum number of results to return.
            where: Optional metadata filter (ChromaDB ``where`` clause).
            where_document: Optional document-content filter.

        Returns:
            ChromaDB query result with ids, distances, metadatas, documents.
        """
        collection = self.chunks_collection
        return collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=["metadatas", "documents", "distances"],
        )

    def search_topics(
        self,
        query_embedding: list[float],
        n_results: int = 10,
    ) -> dict:
        """Search topics by embedding similarity."""
        collection = self.topic_collection
        return collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )

    # ── Deletion ────────────────────────────────────────────────────────────

    def delete_chunks_by_document(self, document_id: str) -> int:
        """Delete all chunks for a given document.

        Returns the number of chunks deleted.
        """
        collection = self.chunks_collection
        result = collection.get(where={"document_id": document_id})
        ids = result["ids"]
        if ids:
            collection.delete(ids=ids)
        return len(ids)

    def delete_chunks_by_topic(self, topic_tag: str) -> int:
        """Delete all chunks tagged with a specific topic.

        Returns the number of chunks deleted.
        """
        collection = self.chunks_collection
        result = collection.get(where={"topic_tags": topic_tag})
        ids = result["ids"]
        if ids:
            collection.delete(ids=ids)
        return len(ids)

    def clear_collection(self, name: str) -> None:
        """Delete and recreate a collection."""
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
        self._get_or_create_collection(name)

    # ── Incremental updates ─────────────────────────────────────────────────

    def update_chunk_metadata(self, chunk_id: str, metadata: dict) -> None:
        """Update metadata for a single chunk."""
        collection = self.chunks_collection
        collection.update(
            ids=[chunk_id],
            metadatas=[metadata],
        )

    # ── Validation ──────────────────────────────────────────────────────────

    def validate_index(
        self,
        collection_name: str | None = None,
    ) -> IndexValidationResult:
        """Validate the integrity of an index collection.

        Checks:
        - Collections exist (creating them automatically if needed)
        - Document/chunk counts
        - Orphaned chunk references
        """

        if collection_name:
            names = [collection_name]
        else:
            names = [
                DOCUMENTS_COLLECTION,
                CHUNKS_COLLECTION,
                TOPIC_EMBEDDINGS_COLLECTION,
            ]

        issues: list[str] = []
        doc_count = 0
        chunk_count = 0
        missing_docs: list[str] = []

        # Ensure collections exist
        for name in names:
            try:
                collection = self._get_or_create_collection(name)
                count = collection.count()

                if name == DOCUMENTS_COLLECTION:
                    doc_count = count
                    if count == 0:
                        issues.append(
                            f"Documents collection '{name}' is empty"
                        )

                elif name == CHUNKS_COLLECTION:
                    chunk_count = count
                    if count == 0:
                        issues.append(
                            f"Chunks collection '{name}' is empty"
                        )

                elif name == TOPIC_EMBEDDINGS_COLLECTION:
                    # Empty topic collection is acceptable.
                    pass

            except Exception as exc:
                issues.append(
                    f"Collection '{name}' error: {exc}"
                )

        # Cross-reference chunks against documents
        try:
            chunk_collection = self._get_or_create_collection(
                CHUNKS_COLLECTION
            )
            all_chunks = chunk_collection.get(limit=10000)

            if all_chunks["metadatas"]:
                doc_ids_in_chunks = set()

                for metadata in all_chunks["metadatas"]:
                    if metadata and "document_id" in metadata:
                        doc_ids_in_chunks.add(metadata["document_id"])

                if doc_ids_in_chunks:
                    document_collection = self._get_or_create_collection(
                        DOCUMENTS_COLLECTION
                    )

                    existing_docs = set(document_collection.get()["ids"])

                    for document_id in doc_ids_in_chunks:
                        if document_id not in existing_docs:
                            missing_docs.append(document_id)

                    if missing_docs:
                        issues.append(
                            f"Found {len(missing_docs)} chunks referencing non-existent documents"
                        )

        except Exception:
            # Fresh installations may have empty collections.
            pass

        return IndexValidationResult(
            is_valid=len(issues) == 0,
            document_count=doc_count,
            chunk_count=chunk_count,
            missing_documents=missing_docs,
            issues=issues,
        )