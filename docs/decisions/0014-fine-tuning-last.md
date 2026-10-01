# D-14: Fine-tuning is last

- **Status:** Accepted
- **Decision:** Defer fine-tuning to Phase 12 and gate promotion on benchmark results. Merge adapters into the higher-precision base before quantizing the shipped GGUF.
- **Rationale:** Establish task headroom and a reliable baseline before adding training complexity.
