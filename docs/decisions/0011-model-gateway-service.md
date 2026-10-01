# D-11: Internal Model Gateway

- **Status:** Accepted
- **Decision:** Put admission, priority lanes, routing, retries, circuit breaking, and telemetry in a small internal Model Gateway service. Clients use `packages/model_client`.
- **Rationale:** Global model-server capacity needs a single admission point across workers.
