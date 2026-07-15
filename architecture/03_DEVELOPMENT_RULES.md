# AAA v2 Development Rules

**Source of truth:** `01_AAA_Next_Generation_Architecture.md`  
**Constraint:** All rules in this document are derived solely from that architecture.

---

## 1) Architecture Authority Rules

1. **Architecture-first implementation:** Build only what is specified by the v2 architecture unless explicitly approved as future scope.
2. **No capability regression from v1:** v1 capabilities must be re-hosted in v2 architecture; do not remove existing core functionality during migration.
3. **Additive migration rule:** Introduce v2 systems in parallel first, then cut over; avoid big-bang replacements.
4. **Versioned API rule:** New backend APIs must be exposed under `/api/v2/*`.
5. **LangGraph orchestration authority:** Routing decisions and flow control belong in LangGraph graph edges, not scattered in API handlers.

---

## 2) System Design Rules

1. **Stateless API pods only:** FastAPI edge layer remains stateless; durable state must live in Postgres/Redis/ChromaDB.
2. **Short-node graph rule:** Graph nodes must stay small, checkpointable, and resumable.
3. **Checkpoint everywhere:** Every meaningful graph stage must checkpoint state to support exact resume.
4. **Deterministic routing policy:** Adaptive routing decisions are policy-based deterministic logic (no LLM in routing).
5. **Agent purity rule:** Agents act as explicit state transforms with declared reads/writes; hidden side effects are prohibited.
6. **Background-work off request path:** Prefetch, batch embeddings, and analytics aggregation must run in workers.

---

## 3) Data & Persistence Rules

1. **Postgres as system of record:** SQLite is not acceptable for v2 concurrent, multi-user production behavior.
2. **Two-tier session persistence:** Keep hot state in Redis and durable session/checkpoint pointers in Postgres.
3. **Knowledge graph model compliance:** Use `Topics`, `TopicEdge`, and `TopicClosure` schema conventions from the architecture.
4. **Closure-table integrity:** Maintain transitive closure incrementally on edge updates.
5. **Mastery model compliance:** Track concept mastery per user/topic with score, confidence, attempts, and practice timestamps.
6. **Append-only analytics events:** Analytics ingestion must append events first; aggregation happens asynchronously.
7. **Hashed sensitive tokens:** Store refresh/reset tokens only as hashes; never persist raw tokens.

---

## 4) AI/LLM Usage Rules

1. **Provider-router boundary:** Agents must never call provider SDKs directly; all calls go through the provider router.
2. **Per-agent provider policy:** Provider priority can vary by agent based on quality/latency/cost needs.
3. **Fallback resilience required:** Implement retries, exponential backoff, and circuit-breaker behavior.
4. **Retrieval-first quiz generation:** Quiz assembly should prefer question-bank retrieval; LLM generation is a miss-path.
5. **Bounded LLM use in deterministic paths:** Root-cause scoring and adaptive decisions remain deterministic; LLM use is narrative-only where specified.

---

## 5) Learning Experience Rules

1. **Micro-learning format:** Lessons must be card-based (one concept + concise explanation + example + takeaway).
2. **Mode-aware behavior:** Sprint, Journey, and Mastery modes must alter depth and context budget consistently.
3. **Streaming-first lesson UX:** Return first visible lesson content quickly via progressive card streaming.
4. **Card-level refinement only:** In-lesson refinements target the current card, not full lesson regeneration.
5. **Memory Engine adaptation:** Student interaction signals must update preference profile via EMA.
6. **Mastery-weighted quizzes:** Current-topic vs prerequisite question ratio must follow architecture thresholds.
7. **Prerequisite-sensitive rerouting:** If root cause is a weak prerequisite, pause current topic and reroute using path stack.
8. **Exact-resume guarantee:** Mid-lesson/mid-quiz/session reroute state must be recoverable exactly.

---

## 6) Search, Retrieval, and Content Safety Rules

1. **Search-agent extension rule:** Keep one Search & Retrieval Agent; do not split a separate YouTube agent.
2. **Cache-first retrieval:** Use Redis cache keys with difficulty/mode-sensitive dimensions.
3. **Trusted-channel filtering:** YouTube content must be filtered by curated allowlist before ranking.
4. **Shared ranking model:** Apply composite scoring based on relevance, authority, difficulty match, and freshness.
5. **Prompt-injection sanitization boundary:** Sanitize fetched web/transcript content before any LLM prompt usage.
6. **Graceful degradation:** Search/resource failures must not block lesson progression.
7. **Hybrid retrieval requirement:** Use semantic + keyword retrieval with KG-proximity reranking and mode-aware trimming.

---

## 7) API & Security Rules

1. **JWT + refresh token model:** Access tokens are short-lived JWTs; refresh tokens are long-lived opaque tokens with rotation.
2. **RBAC enforcement:** Route access must be policy-gated by role (`student`, `admin`, reserved `instructor`).
3. **Session endpoints required:** `/session/current`, heartbeat, and end-session flows are required behavior.
4. **Auth lifecycle completeness:** Register, verify email, login/logout, refresh, forgot/reset password must be implemented together.
5. **Admin curation isolation:** Knowledge-graph edge curation operations are admin-scoped.

---

## 8) Performance & Reliability Rules

1. **Performance budgets are contractual:** Maintain architecture p95 targets for curriculum, lesson start, quiz generation, transitions, and search.
2. **Non-blocking analytics:** Analytics emission and aggregation must not degrade interactive teaching/quiz latency.
3. **Observability by default:** Log every agent call, cache hit/miss, and routing decision in structured form.
4. **Health checks mandatory:** Provide liveness (`/healthz`) and readiness (`/readyz`) probes.
5. **Rate limiting mandatory:** Apply per-user/per-IP limits, with stricter limits for auth endpoints.

---

## 9) Testing & Quality Rules

1. **Layered test model required:** Unit, integration, contract, e2e, and load tests are all mandatory.
2. **Deterministic logic must be unit-tested as pure functions:** adaptive routing policy, ranking math, closure maintenance, mastery ratios.
3. **Generative quality gate:** Teaching/Quiz/Root-Cause outputs must pass golden-set rubric thresholds.
4. **Provider-failure tests required:** Simulate timeout, 5xx, rate-limit, and malformed response scenarios.
5. **Graph integrity tests required:** Enforce no cycles, closure consistency, and orphan-node detection.

---

## 10) Deployment & Operations Rules

1. **Container separation:** Backend, frontend, and each worker type deploy as separate images.
2. **Horizontal scaling model:** API scales on compute + in-flight requests; workers scale by queue depth.
3. **Managed stateful services:** Postgres/Redis/ChromaDB/object storage are externalized managed state.
4. **CI/CD quality gates:** Lint/type-check, tests, golden eval, staging deploy, e2e, load test, manual approval, smoke tests.
5. **Feature-flagged cutover:** Agent-by-agent traffic shifts require measurable quality/performance validation before advancement.

---

## 11) Migration Rules

1. **Dual-write before read-shift:** Verify consistency over sustained period before redirecting read traffic.
2. **Backfill before behavior change:** Build and validate knowledge graph from existing syllabus/topic data before adaptive routing rollout.
3. **Per-agent rollbackability:** Every cutover step must be reversible without full-system rollback.
4. **Legacy decommission last:** Remove v1 paths only after stable full-traffic monitoring on v2.
5. **Compatibility over churn:** Preserve embedding compatibility (`gemini-embedding-001`, 768-dim) to avoid unnecessary re-embedding.

---

## 12) Out-of-Scope Guardrails

1. Items explicitly marked as future scope (e.g., instructor cohort tooling, spaced-repetition scheduler enhancements, voice tutor interface, multiplayer learning, LMS connectors, knowledge-graph marketplace) are not part of core v2 delivery unless promoted by explicit decision.
2. Designing for compatibility with future scope is allowed; implementing future-scope product features is not required for v2 completion.

---

## 13) Definition of Rule Compliance

A change is compliant with these rules only if it:

1. Preserves the architecture’s layered boundaries,
2. Keeps adaptive tutoring behavior deterministic where specified,
3. Maintains durability/resume guarantees,
4. Meets security and observability requirements, and
5. Does not violate migration safety constraints.

