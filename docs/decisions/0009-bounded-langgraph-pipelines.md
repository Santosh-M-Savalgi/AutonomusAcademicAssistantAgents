# D-09: Bounded LangGraph pipelines

- **Status:** Accepted
- **Decision:** Use LangGraph for bounded pipelines within individual jobs. The macro learning loop remains the Postgres Session FSM plus Planner.
- **Rationale:** Separate workflow checkpoints from durable session and planning state.
