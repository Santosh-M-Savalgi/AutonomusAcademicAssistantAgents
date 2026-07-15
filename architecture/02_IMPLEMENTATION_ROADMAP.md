# AAA v2 Implementation Roadmap

**Source of truth:** `01_AAA_Next_Generation_Architecture.md`  
**Scope rule:** This roadmap is derived only from the architecture specification.

---

## 1) AI Implementation Rules

1. **Read the architecture before every implementation session.**  
   Always review `architecture/01_AAA_Next_Generation_Architecture.md` before starting sprint work.
2. **Read and update implementation progress.**  
   At sprint start/end, read and update `architecture/04_IMPLEMENTATION_PROGRESS.md` (implementation progress tracker).
3. **Implement only the current sprint.**  
   Deliver the current sprint scope fully; do not begin downstream sprint code early.
4. **Do not implement future sprints.**  
   Backlog and dependencies may be prepared, but code changes must stay within approved sprint scope.
5. **Do not redesign the architecture.**  
   Architectural choices in `01_AAA_Next_Generation_Architecture.md` are authoritative.
6. **Keep backward compatibility.**  
   Preserve v1 behavior and compatibility constraints during additive migration and phased cutover.
7. **Produce production-quality code.**  
   Ensure correctness, observability, error handling, and operational readiness per architecture standards.
8. **Write tests for all delivered behavior.**  
   Add/maintain unit, integration, contract, and e2e coverage appropriate to sprint scope.
9. **Explain any breaking changes explicitly.**  
   If unavoidable, document impact, mitigation, migration path, and rollback strategy.
10. **Wait for user approval before moving to the next sprint.**  
    Sprint transitions require explicit approval after exit criteria are met and evidence is shared.

---

## 2) Roadmap Objective

Deliver AAA v2 as an adaptive, checkpointed, multi-agent tutoring platform with:

- Knowledge-graph-driven learning paths
- Mastery-aware quiz and root-cause diagnostics
- Durable session recovery
- Authenticated multi-user support
- Analytics-backed dashboarding
- Production-grade reliability and provider fallback

while preserving existing v1 capability and following additive migration before cutover.

---

## 3) Delivery Principles (from Architecture)

1. **Additive first, cutover second** (Section 23.1)
2. **Short, checkpointed LangGraph nodes** with durable resume (Sections 5, 18)
3. **Deterministic adaptive routing policy** (Section 14.2)
4. **Provider-router boundary for all LLM calls** (Sections 3, 22.5)
5. **Request path stays fast; heavy work moves to workers** (Sections 3, 10, 19)
6. **Performance measured against explicit p95 targets** (Section 2.2)

---

## 4) Workstreams

1. **Platform & Data Foundation**
   - PostgreSQL + Redis + ChromaDB integration
   - Schema, migrations, indexing, checkpoint persistence

2. **Graph Runtime & Agents**
   - LangGraph state/checkpoint architecture
   - 9-agent implementation and deterministic routing

3. **Pipelines**
   - Knowledge graph ingestion
   - Search/ranking/caching/fallback
   - Retrieval, embeddings, teaching cards, quiz bank, root-cause analysis

4. **API & Product Surfaces**
   - `/api/v2/*` domains
   - Session, lesson streaming, quiz flow, dashboard/analytics endpoints

5. **Security, Reliability, and Operations**
   - JWT + refresh + RBAC
   - CI/CD, observability, health checks, rate limits, provider failover

6. **Migration and Cutover**
   - Dual-write, sprinted feature flags, validation, rollback readiness

---

## 5) Sprint Implementation Plan

## Sprint 0 - Foundation Bootstrap

### Scope
- Stand up Postgres, Redis, ChromaDB, object storage integration.
- Introduce v2 code structure (backend services, graph, agents, workers, API v2 modules).
- Implement baseline config/security/logging/rate-limit scaffolding.

### Exit Criteria
- Local and staging environments run all core stores.
- Backend boots with v2 skeleton and health endpoints.
- Structured logging includes request/session correlation IDs.

---

## Sprint 1 - Data Model & Persistence Core

### Scope
- Implement Section 15 schema:
  - Users, StudentProfiles, Syllabi, Topics, TopicEdge, TopicClosure
  - Resources, YouTubeResources, TrustedChannels
  - QuizQuestions, QuizAttempts, QuizAttemptAnswers
  - ConceptMastery, Sessions, RefreshTokens, Preferences, AnalyticsEvents
- Add required indexes and partition strategy for analytics events.
- Build LangGraph checkpointer adapter (Redis hot + Postgres durable).

### Exit Criteria
- Migrations apply cleanly in CI and staging.
- Session checkpoint write/read works through both storage tiers.
- Topic traversal and mastery lookup queries meet expected response times.

---

## Sprint 2 - Authentication Core

### Scope
- Implement `/api/v2/auth/*` endpoints from Section 16:
  - Register, verify email, login, logout, refresh
  - Forgot-password and reset-password
- Implement token model from Section 17:
  - Access JWT (15 min)
  - Opaque refresh tokens (30 days), hashed at rest, rotation on use
- Implement role-based route guards (`student`, `admin`, reserved `instructor`).
- Wire auth dependencies so downstream services operate on authenticated users and profile context.

### Exit Criteria
- Auth lifecycle and token rotation are validated end-to-end.
- Refresh token revocation and replay-limiting behavior works as designed.
- RBAC checks correctly gate protected endpoints.

---

## Sprint 3 - Session Management Core

### Scope
- Implement session API endpoints from Section 16:
  - `GET /session/current`
  - `POST /session/heartbeat`
  - `POST /session/end`
- Implement two-tier session behavior from Section 18:
  - Redis hot state
  - Postgres durable checkpoint pointers and path stack
- Implement resume flow (Redis fast path, Postgres rehydrate path).
- Persist required state artifacts: current card/question, quiz progress, selected mode, weak-concept state, path stack.

### Exit Criteria
- Session resume correctly restores mid-lesson or mid-quiz state.
- Rehydration from Postgres works when Redis state is absent.
- Heartbeat/end flows update authoritative session metadata correctly.

---

## Sprint 4 - LLM Provider Router & Core Runtime

### Scope
- Implement provider router with:
  - Provider priority by agent
  - Retry + exponential backoff
  - Circuit breaker and health state
- Enforce router boundary: no direct provider SDK calls in agents.
- Build typed `AAAState` and graph builder skeleton with checkpoint boundaries.

### Exit Criteria
- Simulated provider failures fail over without user-visible request failure.
- Graph can run and resume from checkpoints for a mock topic flow.

---

## Sprint 5 - Knowledge Graph Ingestion & Context Tooling

### Scope
- Build Syllabus Parser and Knowledge Graph Agent flow:
  - Topic extraction
  - Edge inference
  - Embedding-based topic de-duplication
  - Incremental `TopicClosure` maintenance
  - Low-confidence edge flagging
- Expose read-only `get_topic_context(topic_id)` tool for runtime usage.

### Exit Criteria
- Syllabus ingestion creates usable DAG + closure rows.
- `get_topic_context` returns prerequisites, mastery overlays, and children in one call.
- No-cycle and closure consistency tests pass.

---

## Sprint 6 - Search, Retrieval, and Embedding Pipelines

### Scope
- Extend Search Agent with parallel web + YouTube branches.
- Add trusted-channel filtering, ranking formula, Redis cache key/TTL, fallback chain.
- Build retrieval pipeline: hybrid semantic + keyword + KG-proximity rerank + mode-aware context budget.
- Build batch embedding worker and stale-embedding recompute policy.

### Exit Criteria
- Cache hit path and fallback path are both validated.
- Resource bundles persist to DB + cache with ranking metadata.
- Batch worker processes queued embedding jobs reliably.

---

## Sprint 7 - API Domain Surfaces (Non-Auth/Session)

### Scope
- Implement `/api/v2/*` domain endpoints from Section 16 (excluding auth/session already delivered):
  - Knowledge Graph, Lessons, Quiz, Search, Recommendations, Dashboard, Analytics, Resources
- Provide typed request/response contracts aligned with OpenAPI.
- Ensure frontend integration paths can call these endpoints incrementally.

### Exit Criteria
- Domain endpoints are reachable with authenticated context and valid contract responses.
- Frontend can consume v2 APIs for lesson, quiz, and progress journeys.

---

## Sprint 8 - Teaching Pipeline & Memory Engine

### Scope
- Implement Teaching Agent:
  - Micro-learning cards
  - Mode-aware generation (Sprint/Journey/Mastery)
  - Streaming-first lesson delivery
  - Card-level refinement actions
- Implement Memory Engine EMA updates from learning behavior signals.

### Exit Criteria
- Lesson cards stream progressively with mode-appropriate depth.
- Card refinements update only the current card context.
- Memory profile updates influence subsequent teaching behavior.

---

## Sprint 9 - Quiz Pipeline

### Scope
- Implement Quiz Agent:
  - Mastery-weighted current/prerequisite ratio
  - Question-bank-first assembly
  - Generation-on-bank-miss
  - Dedup and retake logic
- Integrate quiz retrieval from KG + ConceptMastery context.

### Exit Criteria
- Quiz assembly follows mastery-weighted policy correctly.
- Bank hit and miss paths both function and persist expected artifacts.
- Duplicate suppression and retake behavior match architecture rules.

---

## Sprint 10 - Root Cause Analysis & Adaptive Routing

### Scope
- Implement Root Cause Agent:
  - Deterministic scoring
  - Weak-concept report
  - Knowledge-gap report
  - Dependency trace generation
- Implement Adaptive Router:
  - Deterministic advance/reroute/retry policy
  - Path stack pause/resume semantics
- Integrate full teaching -> quiz -> score -> route cycle.

### Exit Criteria
- Full topic cycle executes end-to-end with deterministic route decisions.
- Reroute pauses current topic and resumes correctly after prerequisite mastery.
- Path stack survives crash/restart and resumes at exact prior state.

---

## Sprint 11 - Analytics, Dashboard Read Models, and Insights

### Scope
- Event-sourced analytics emission from core student actions.
- Aggregation worker builds dashboard read models.
- Implement analytics summary and insights endpoints.
- Keep LLM narrative generation for insights bounded and off interactive path.

### Exit Criteria
- Dashboard endpoints return mastery/progress/velocity/retention aggregates.
- Aggregation jobs are stable under continuous event ingestion.

---

## Sprint 12 - Testing, Quality Gates, and Performance Hardening

### Scope
- Layered testing from Section 21:
  - Unit, integration, contract, e2e, load
- Golden-set quality evaluation for Teaching/Quiz/Root Cause outputs.
- Multi-provider failure simulation tests.
- Tune system to performance goals from Section 2.2:
  - Curriculum generation < 3s
  - First lesson < 8s (first visible content < 2s via streaming)
  - Quiz generation < 3s
  - Topic transition < 500ms
  - Search/ranking < 4s

### Exit Criteria
- Required test suites pass in CI.
- p95 performance targets are met in staging load tests.
- Golden-set quality threshold passes for all generative paths.

---

## Sprint 13 - Production Readiness

### Scope
- Docker optimization for backend/frontend/workers (image size, layers, startup profile).
- CI/CD hardening across lint/type-check/test/golden/staging/e2e/load gates.
- Monitoring and alerting setup (metrics, dashboards, SLO-aligned alert thresholds).
- Structured logging validation with request-id/session-id/agent correlation.
- Rate limiting policy rollout and validation (global + stricter auth policies).
- Secrets management and environment validation for all deploy environments.
- Worker scaling policy validation (queue-depth autoscaling, backpressure behavior).
- Redis tuning (memory policy, eviction strategy, persistence, latency tuning).
- PostgreSQL tuning (connection pooling, indexing verification, query tuning, partition maintenance).
- Health checks (`/healthz`, `/readyz`) and readiness dependencies validated.

### Exit Criteria
- Deployment artifacts are production-optimized and reproducible.
- Operational telemetry, logging, and alerting are complete and actionable.
- Security/secret handling and env validation pass pre-production checks.
- Worker autoscaling and datastore tuning validated under staging load.
- Health/readiness checks gate rollout safely.

---

## Sprint 14 - Migration, Gradual Traffic Shift, and Decommission

### Scope
- Execute migration plan from Section 23:
  - Sprint 0 foundation + dual-write
  - KG backfill
  - Agent-by-agent feature-flag cutover
  - Auth/session additive rollout
  - SQLite historical ETL into Postgres
  - Legacy path decommission
- Keep v1 endpoints live during sprinted v2 rollout.
- Use monitored flag flips with rollback runbooks.

### Exit Criteria
- Dual-write consistency stable for 7+ days before read shift.
- Each cutover gate satisfies latency + quality monitoring checks.
- Legacy v1 paths removed only after full monitoring cycle at 100% v2 traffic.

---

## 6) Dependency Order (Critical Path)

1. Foundation infra + schema + checkpointer
2. Authentication core
3. Session management core
4. Provider router + graph runtime skeleton
5. Knowledge graph ingestion + context tools
6. Search/retrieval/embedding pipelines
7. API domain surfaces
8. Teaching pipeline + memory engine
9. Quiz pipeline
10. Root cause + adaptive routing
11. Analytics + dashboard read models
12. Quality/performance hardening
13. Production readiness
14. Migration and decommission

---

## 7) Release Gates

Progression between sprints requires:

- **Functional gate:** sprint exit criteria met
- **Reliability gate:** no critical errors in logs/health checks
- **Performance gate:** sprint-relevant p95 targets hold
- **Rollback gate:** tested rollback path exists for new behavior
- **Approval gate:** explicit user approval before starting the next sprint

---

## 8) Done Definition for AAA v2

AAA v2 is implementation-complete when:

1. The adaptive tutor flow runs end-to-end with deterministic rerouting and resume.
2. v2 API surface is production-ready and authenticated.
3. All major pipelines (KG, search/retrieval, embedding, teaching, quiz, analytics) are operational.
4. Performance and quality goals from Sections 2 and 21 are consistently met.
5. v1 migration/cutover plan is executed with safe decommission of legacy paths.
