# D-04: PostgreSQL with pgvector

- **Status:** Accepted
- **Decision:** Use pgvector inside PostgreSQL for vector search, alongside PostgreSQL full-text search. ChromaDB is not part of v3.
- **Rationale:** PostgreSQL remains the transactional source of truth and supports hybrid search and metadata filtering.
