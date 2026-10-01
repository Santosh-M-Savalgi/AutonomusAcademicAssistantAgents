# D-03: Embedding model selection

- **Status:** Accepted
- **Decision:** Default to BAAI/bge-small-en-v1.5 (384 dimensions), with nomic-embed-text-v1.5 as the challenger. Switch only after the specified Recall@5 and latency comparison.
- **Rationale:** The default is small and fast while preserving a measured upgrade path.
