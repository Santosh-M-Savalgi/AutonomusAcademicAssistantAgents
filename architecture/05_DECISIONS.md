# AAA v2 Architecture Decisions

**Source of truth:** `01_AAA_Next_Generation_Architecture.md`  
**Scope:** Decisions captured from the architecture only.

---

## Decision Register

| ID | Decision | Status | Why (from architecture) | Consequence |
|---|---|---|---|---|
| D-001 | Use layered architecture (Client -> Stateless API -> LangGraph -> Agents -> Data/Workers) | Accepted in architecture | Separate orchestration, request handling, long-running work, and state | Clear scaling boundaries and cleaner failure isolation |
| D-002 | Keep API layer stateless | Accepted in architecture | Horizontal scalability and safe rolling deploys require no pod-local state | All durable/session state must live in shared stores |
| D-003 | Use LangGraph as the decision/control plane | Accepted in architecture | Routing logic centralized in graph edges avoids hidden coupling | API handlers stay thin; behavior is graph-defined |
| D-004 | Use short, checkpointed, resumable graph nodes | Accepted in architecture | Prevent full restart on slow/failing steps; support exact resume | Requires robust checkpointing discipline |
| D-005 | Split v1 Tutor+Quiz into Teaching, Quiz Generation, Root Cause agents | Accepted in architecture | Different latency/quality patterns require separate scaling and caching | Better isolation; more components to coordinate |
| D-006 | Extend existing Search Agent instead of adding new YouTube agent | Accepted in architecture | Design mandate: preserve Search substrate and add retrieval branch in-agent | Shared caching/ranking/fallback path, less agent sprawl |
| D-007 | Use Postgres for relational + knowledge graph storage | Accepted in architecture | Multi-user concurrency, JSONB, joins, migration support, recursive queries | Retires SQLite as v2 system of record |
| D-008 | Implement KG with adjacency list + materialized closure table in Postgres (not Neo4j) | Accepted in architecture | Workload is shallow traversal; avoid adding a 4th stateful system | Must maintain closure consistency incrementally |
| D-009 | Keep Knowledge Graph read-only during active tutoring sessions | Accepted in architecture | Fast, side-effect-free lesson path; writes only via ingestion/curation | Runtime reads are predictable and testable |
| D-010 | Use hybrid retrieval (semantic + keyword) with KG-proximity rerank | Accepted in architecture | Pure semantic retrieval can be level-misaligned | Better relevance at chosen difficulty/mode |
| D-011 | Keep embedding model `gemini-embedding-001` at 768 dimensions | Accepted in architecture | Preserve v1 compatibility; avoid bulk re-embedding migration cost | Cross-version embedding comparability maintained |
| D-012 | Batch embeddings in worker queue, not per-request for bulk items | Accepted in architecture | Keep request path latency low and absorb ingestion bursts | Requires queue/worker reliability controls |
| D-013 | Use mastery-weighted quiz ratios across current topic + prerequisites | Accepted in architecture | Root-cause diagnosis requires prerequisite-sensitive assessment | Quiz assembly depends on mastery and KG context |
| D-014 | Quiz generation is bank-first; LLM generation only on bank miss | Accepted in architecture | Meet <3s steady-state quiz latency targets | Requires question bank growth and dedup safeguards |
| D-015 | Use deterministic adaptive routing policy (no LLM for route decision) | Accepted in architecture | Sub-200ms predictable routing, full unit-testability | Policy logic must be explicit and exhaustive |
| D-016 | Use path stack pause/resume for prerequisite rerouting | Accepted in architecture | Fix underlying prerequisite gaps before resuming paused topic | Requires checkpointed stack integrity |
| D-017 | Session state is two-tier: Redis hot + Postgres durable | Accepted in architecture | Fast active reads plus durable recovery across cache/pod failures | Dual-write consistency is mandatory |
| D-018 | Auth model: short-lived JWT access + rotated hashed refresh tokens + RBAC | Accepted in architecture | Security and scale: stateless request auth with revocable long-lived sessions | Token lifecycle and revocation infrastructure needed |
| D-019 | Keep prompt-injection sanitization as hard boundary for fetched content | Accepted in architecture | Prevent malicious retrieved text from entering LLM prompts unsanitized | Sanitization applies to web pages and YouTube transcripts |
| D-020 | Search cache-first strategy with explicit fallback chain | Accepted in architecture | Meet latency goals while avoiding lesson blocking on search outages | Requires curated static fallback resources |
| D-021 | Event-sourced analytics ingestion + async aggregation | Accepted in architecture | Preserve action-level truth while avoiding request-path delays | Requires rollup jobs and partition strategy |
| D-022 | Multi-provider router with retries/backoff/circuit breaker | Accepted in architecture | Provider independence and outage resilience | Router health logic is operationally critical |
| D-023 | Deploy as separate backend/frontend/worker images on Kubernetes | Accepted in architecture | Independent scaling and operational control by workload type | Requires queue-depth and pod-autoscaling policies |
| D-024 | Use additive migration with dual-write and per-agent feature-flag cutover | Accepted in architecture | Safe reversibility and controlled risk during transition from v1 | Migration must be monitored phase-by-phase |
| D-025 | Keep v1 APIs live while introducing `/api/v2/*` in parallel | Accepted in architecture | Enables gradual frontend migration and non-disruptive rollout | Temporary duplication overhead until decommission |

---

## Decision Constraints

1. Decisions in this register remain valid unless superseded by an updated architecture document.
2. Any implementation that violates these decisions must be treated as an explicit architecture deviation.
3. Migration-related decisions (D-024, D-025) are safety-critical and cannot be skipped.

