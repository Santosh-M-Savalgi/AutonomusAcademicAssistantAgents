# D-05: Deterministic planner

- **Status:** Accepted
- **Decision:** The Planner is a deterministic policy engine. LLMs may explain decisions or optionally tie-break among enumerated candidates, but may not choose arbitrary actions.
- **Rationale:** Determinism makes sequencing auditable, testable, and simulatable.
