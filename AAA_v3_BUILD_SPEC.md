# AAA v3 - Build Specification (agent-executable)

Spec version: 3.2 - reviewed revision of `AAA_v3_COMPLETE_BUILD_PLAN.md` (v3.0), hardware-tuned for RTX 3050 4 GB VRAM / 16 GB RAM / i5-12500H (Section 7.11).
Audience: coding agents (Claude Code, Codex) and the human owner.
Usage: save as `AGENTS.md` (Codex reads it natively). For Claude Code create `CLAUDE.md` containing the single line `@AGENTS.md`.
Rationale for every change vs v3.0 is in Appendix A. This file is the source of truth; if code and this file disagree, fix one of them in the same PR.

---

## 0. Rules for coding agents (read first)

1. Work on **one phase task at a time** (Section 17). Do not start a phase whose predecessor's acceptance tests are red.
2. **Tests first or alongside.** Every task ships: code + tests + migration (if schema changes) + doc note. Run `make check` before declaring done.
3. **Never call a real LLM in unit/integration tests.** Use `FakeProvider` (Section 7.5). Real-model tests live under `tests/ai_eval/` and are marker-gated (`-m ai_eval`).
4. **Pure core.** `packages/mastery` and `packages/planner` contain no I/O (no DB, HTTP, clock, random without injected seed). Enforced by `import-linter` contracts (Section 4).
5. **LLM output is untrusted input.** Every model result is parsed into a Pydantic model and validated before it touches the DB or another agent. LLMs never write to the DB directly and never choose planner actions outside the enum.
6. **Model names, prompts, thresholds, and policy numbers live in config/versioned files**, never inline. Every persisted AI artifact records `model_id, adapter_version, prompt_version, retrieval_version, mastery_policy_version, planner_policy_version`.
7. **Postgres is the single source of truth.** Redis may be lost at any time without losing jobs, state, or evidence.
8. **Every state-changing operation is idempotent** (Section 12.4).
9. If the spec is ambiguous: choose the simplest option consistent with Section 2 (locked decisions), record it as an ADR in `docs/decisions/NNNN-title.md`, continue. Do not stall.
10. **Ask the human before**: destructive migrations, adding a paid/cloud dependency, changing any Section 2 decision, anything license-related, anything that sends student data off-host.
11. Do not add dependencies without adding a line to `docs/STACK.md` (name, pinned version, why, license).
12. Feature admission test (from v3.0, kept): a new feature must state (a) student state it consumes, (b) evidence it produces, (c) owning agent/service, (d) whether it changes the graph/plan, (e) how it is tested and observed.

Make targets every agent can rely on (implement in Phase 1, keep stable):

```
make up            # docker compose up (profile from $AAA_PROFILE: mock|cpu|gpu)
make down
make migrate       # alembic upgrade head
make test          # unit + integration (mock profile, no GPU)
make e2e           # end-to-end demo scenario (Section 16.5) on mock profile
make check         # ruff + mypy(strict on packages/) + import-linter + test
make eval          # ai_eval suites against the running model profile
make sim           # student simulator scenarios (Section 16.3)
make llama-up      # start llama.cpp servers (chat + embeddings) for cpu|gpu profile
make seed          # load sample syllabi + goldens
```

---

## 1. Product definition

AAA v3 is a **controlled-autonomy adaptive tutoring platform**: it turns a student's syllabus into a user-confirmed curriculum and prerequisite graph, teaches with grounded lesson blocks, assesses with concept-tagged questions, maintains an evidence-based student model, and **replans** after material learning events.

Central question: *given this student's curriculum, evidence, and constraints, what is the best valid next learning action, and what evidence justifies it?*

Claims policy: call it **controlled autonomy**. Do not claim "fully autonomous" or "better than a cloud LLM" without benchmark evidence (Section 16).

Non-goals for v3.0: training a model from scratch; multilingual support (embedding models chosen are English-only); scanned-syllabus OCR beyond an optional fallback; a native mobile app; instructor dashboards beyond read-only analytics.

Scope tiers (used in Section 17):
- **P0** - demoable core: everything through Phase 8, Docker Compose only.
- **P1** - hardening: Phases 9-10.
- **P2** - stretch: Phases 11-12 (Kubernetes, fine-tuning, code sandbox, resource agent).

---

## 2. Locked decisions

| ID | Decision | Why | Revisit when |
|---|---|---|---|
| D-01 | **Greenfield repo, but port proven v2 modules** (JWT auth, password hashing, Alembic env, MinIO client, config, observability wiring, pytest fixtures) after a short audit. Do **not** port v2's page-by-page service orchestration. | Rewriting solved problems burns schedule; the differentiator is the learning loop. | Audit finds port cost > rewrite cost |
| D-02 | **Chat SLM: Llama 3.2 3B Instruct, GGUF Q4_K_M, served by llama.cpp `llama-server`** behind the Model Gateway. | Required stack; ~2 GB weights fits the 4 GB dev GPU (7.11). | Go/no-go gate fails (Section 7.9) |
| D-03 | **Embeddings: default `BAAI/bge-small-en-v1.5` (384-d); challenger `nomic-embed-text-v1.5`.** Swap only if the challenger improves Recall@5 by >= 3 points on the retrieval golden set at acceptable latency. | BGE-small is tiny/fast on CPU (keeps GPU for the SLM) and halves vector storage; Nomic has longer context + Matryoshka dims but needs task prefixes. Both English-only. | Retrieval benchmark says otherwise |
| D-04 | **Vector store: pgvector inside PostgreSQL** (HNSW, cosine) + Postgres full-text search. ChromaDB is dropped. | One source of truth, transactional consistency, SQL metadata filtering, native hybrid search; scale here is thousands of chunks per course. | > ~5M chunks or p95 search > 100 ms |
| D-05 | **The Planner is a deterministic policy engine**, not an LLM. LLM use in planning is limited to (a) writing the human-readable explanation and (b) optional tie-break among enumerated candidates. | A 3B model cannot be trusted with sequencing decisions; determinism makes planning testable, auditable, and simulatable. | Simulation shows a learned policy beats rules |
| D-06 | **Grading pyramid**: deterministic grading first; LLM rubric grading only for free text; low confidence => escalate or mark UNCERTAIN. | Small models grade unreliably; most items don't need an LLM. | - |
| D-07 | **Mastery = per-concept Beta posterior with evidence weights and forgetting** (Section 6.1). Versioned policy. | v3.0 left the formula undefined. | Simulation/pilot data justifies BKT/IRT/FSRS |
| D-08 | **Job queue: Postgres `jobs` table claimed with `FOR UPDATE SKIP LOCKED`** (lease + heartbeat). Redis is used only for wake-up signals, SSE fan-out, caching, rate limits. | Removes the DB-to-queue dual-write problem; jobs are created in the same transaction as the domain write. | Throughput demands a broker |
| D-09 | **LangGraph runs bounded pipelines inside a single job** (parse pipeline, lesson pipeline, question pipeline) with `langgraph-checkpoint-postgres`. The macro learning loop is the **Session FSM + Planner** in Postgres, not one giant graph. Custom Redis checkpointers are removed. | v3.0 had four overlapping state mechanisms (LangGraph state, job checkpoints, session FSM, planner queue). | - |
| D-10 | **Streaming: Server-Sent Events**, not WebSockets. | Server->client only; simpler through ingress/proxies. | Need bidirectional realtime |
| D-11 | **Model Gateway is a small internal service** (FastAPI) owning a global priority queue, routing, retries, circuit breaking, telemetry. Clients use `packages/model_client`. | llama-server slots are global across worker replicas; only a single admission point can enforce interactive-over-batch priority. | - |
| D-12 | **Lesson prose is generated as plain Markdown per block**, not wrapped in JSON. JSON/grammar-constrained output is used only for structured tasks. | Streamable, less brittle for a 3B model. | - |
| D-13 | **Cloud fallback is opt-in per user/course** (`allow_cloud_fallback`, default false) with PII redaction. | Student data egress needs consent. | - |
| D-14 | **Fine-tuning is last (Phase 12) and benchmark-gated**; LoRA/QLoRA trains against the HF bf16/NF4 base, is merged in bf16, then quantized to Q4_K_M; the shipped GGUF is what gets evaluated. | Avoids tuning before knowing which tasks need it; avoids merging into already-quantized weights. | - |
| D-15 | English only in v3.0. | Chosen embedders are English-only. | Multilingual requirement (swap to a multilingual embedder + re-index) |

---

## 3. Architecture

### 3.1 Components

```
Web (React+TS) --HTTPS/SSE--> API (FastAPI, HTTP only)
                                 |  (txn: domain write + event row + job row)
                                 v
                           PostgreSQL  <-------------------------+
                  (truth: state, evidence, jobs, events,         |
                   plans, pgvector chunks, LangGraph checkpoints)|
                                 ^                               |
                                 | claim jobs (SKIP LOCKED)      |
                              Workers -- run LangGraph subgraphs +
                                 |       deterministic engines
                                 v
                          Model Gateway (priority queue, routing, telemetry)
                             |                         |
                     llama-server (chat)      llama-server (embeddings)
                     Llama 3.2 3B Q4_K_M      BGE-small / Nomic
                             |
                     Cloud fallback (opt-in, redacted)

Redis: wake-up pub/sub, SSE fan-out, cache, rate limits.   MinIO/S3: uploaded documents.
```

### 3.2 The learning loop (what owns what)

```
Session FSM (Postgres) --transition--> enqueue job
   job (worker) runs bounded LangGraph subgraph -> persists result -> emits event
   event router (same txn) -> deterministic handlers:
        Grader -> MasteryEngine.apply(evidence) -> ReplanCheck -> Planner.decide()
   Planner decision (validated by Policy) -> next Session FSM transition
```

- Mastery update and replan check are **synchronous and deterministic** and happen inside the answer-submission transaction whenever grading was deterministic (L0). Only LLM-dependent steps (L2/L3 grading, diagnosis of uncertain cases, content generation) are async jobs.
- Policy layer outcomes: `ALLOW`, `REQUIRE_CONFIRMATION`, `BLOCK` (Section 6.4).

### 3.3 State ownership

| State | Owner | Store |
|---|---|---|
| Curriculum, graph, plans, sessions, evidence, mastery | domain packages | Postgres |
| Jobs, events, checkpoints | worker/persistence | Postgres |
| Chunks + embeddings | retrieval | Postgres (pgvector) |
| Uploaded files, generated assets | api/worker | MinIO/S3 (metadata in Postgres) |
| Cache, pub/sub, rate limits | api/gateway | Redis (disposable) |

---

## 4. Repository layout and boundaries

```
aaa-v3/
  AGENTS.md  CLAUDE.md(@AGENTS.md)  Makefile  pyproject.toml  docker-compose.yml  .env.example
  apps/
    api/              # FastAPI routers, auth, SSE. HTTP only.
    worker/           # job loop, lease/heartbeat, handlers, LangGraph subgraphs
    model_gateway/    # priority admission, routing, telemetry (internal API)
    frontend/         # React + TypeScript + Vite + TanStack Query
  packages/
    domain/           # entities, enums, events, Pydantic schemas (no I/O)
    mastery/          # PURE: evidence -> mastery state
    planner/          # PURE: state -> PlannerDecision, replan triggers, policy
    curriculum/       # structure detection, draft model, graph validation (DAG checks)
    retrieval/        # chunking, Embedder interface, hybrid search, self-check
    agents/           # curriculum, tutor, assessment, diagnostic, resource (+ prompts/)
    model_client/     # gateway client, FakeProvider, TaskSpec registry
    persistence/      # SQLAlchemy models, repositories, alembic migrations
    evalkit/          # benchmarks, metrics, student simulator
  models/             # configs/, training/, adapters/, MODELS.lock (sha256 of every GGUF)
  data/               # datasets/, goldens/ (DVC or git-lfs)
  infra/              # docker/, compose/, k8s/base, k8s/overlays/{dev,staging,prod}
  tests/              # unit/ integration/ e2e/ ai_eval/ perf/
  docs/               # decisions/ (ADRs), STACK.md, runbooks/
```

Boundary rules (enforced with `import-linter`, run in `make check`):
- `domain` imports nothing internal. `mastery` and `planner` import only `domain`.
- `api` never imports `agents` or model clients; it enqueues jobs and reads state.
- `agents` never touch the DB directly; they receive typed input and return typed output; `worker` persists.
- Only `model_client` talks to the gateway; only `model_gateway` talks to llama-server or cloud providers.

Stack (pin exact versions in `docs/STACK.md` at Phase 1): Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + asyncpg, Alembic, PostgreSQL 16 + pgvector, Redis 7, MinIO, LangGraph + `langgraph-checkpoint-postgres`, httpx, structlog, OpenTelemetry, pytest + pytest-asyncio + testcontainers + hypothesis, ruff, mypy (strict for `packages/`), uv, import-linter. Frontend: React, TypeScript, Vite. Serving: llama.cpp pinned to a release tag. Training: HF transformers + peft + trl + bitsandbytes (or Unsloth).

---

## 5. Contracts (implement as Pydantic models in `packages/domain`)

### 5.1 Planner actions (consolidated; v3.0 had overlapping actions)

```python
class PlannerAction(StrEnum):
    DIAGNOSE = "DIAGNOSE"                       # initial/placement diagnostic
    TEACH_CURRENT_TOPIC = "TEACH_CURRENT_TOPIC"
    TEACH_PREREQUISITE = "TEACH_PREREQUISITE"   # pushes a remediation frame
    PRACTICE_CONCEPT = "PRACTICE_CONCEPT"
    GENERATE_MICRO_CHECK = "GENERATE_MICRO_CHECK"
    GENERATE_QUIZ = "GENERATE_QUIZ"
    REVIEW_DUE = "REVIEW_DUE"                   # spaced-review micro-quiz
    RETEACH_WITH_NEW_STRATEGY = "RETEACH_WITH_NEW_STRATEGY"
    ADVANCE_TOPIC = "ADVANCE_TOPIC"
    RETURN_TO_TARGET = "RETURN_TO_TARGET"       # pops a remediation frame
    SEARCH_MORE_CONTEXT = "SEARCH_MORE_CONTEXT"
    ESCALATE_MODEL = "ESCALATE_MODEL"
    ASK_USER = "ASK_USER"
    PAUSE = "PAUSE"
    COMPLETE = "COMPLETE"

class PlannerDecision(BaseModel):
    action: PlannerAction
    target_id: str                      # concept_id or topic_id
    reason_codes: list[ReasonCode]      # enum, e.g. LOW_PREREQ_MASTERY, REPEATED_FAILURE, GATE_SATISFIED,
                                        # REVIEW_DUE, USER_DIRECTIVE, NO_PROGRESS_LOOP, LOW_EVIDENCE,
                                        # RETRIEVAL_INSUFFICIENT, BUDGET_EXCEEDED, FRAME_COMPLETE
    evidence_ids: list[UUID]
    confidence: float                   # DERIVED from evidence confidence, never LLM self-report
    policy_outcome: Literal["ALLOW", "REQUIRE_CONFIRMATION", "BLOCK"]
    plan_version: int
    planner_policy_version: str
    explanation: str | None             # templated; LLM may polish, never decide
```

### 5.2 Events (append-only `learning_events`, unique `event_id`)

`SYLLABUS_UPLOADED, SYLLABUS_PARSED, CURRICULUM_EDITED, CURRICULUM_CONFIRMED, GRAPH_BUILT, DIAGNOSTIC_COMPLETED, SESSION_STARTED, LESSON_BLOCK_READY, LESSON_READY, CHECKPOINT_ANSWERED, QUIZ_READY, ANSWER_SUBMITTED, ANSWER_GRADED, MASTERY_UPDATED, MISCONCEPTION_DETECTED, PLAN_INVALIDATED, PLAN_REPLANNED, REMEDIATION_LOOP_BLOCKED, REVIEW_DUE, JOB_FAILED, MODEL_FALLBACK_USED`

Envelope: `event_id, type, student_id, course_id, session_id?, payload, causation_id, correlation_id, created_at, versions{...}`.

### 5.3 Lesson block

```python
class LessonBlock(BaseModel):
    block_type: Literal["OVERVIEW","EXPLANATION","INTUITION","EXAMPLE","ANALOGY","CODE","MATH","DIAGRAM",
                        "TABLE","WARNING","MISCONCEPTION","PRACTICE","CHECKPOINT","SUMMARY","RESOURCE"]
    concept_ids: list[str]
    content_md: str
    difficulty: Literal["easy","medium","hard"]
    source_chunk_ids: list[UUID]      # required unless grounded=False
    grounded: bool                    # False => UI shows "general knowledge, not from your material"
    validation: BlockValidation       # citation_ok, length_ok, reading_level, duplicate_of?
    versions: VersionStamp
```

### 5.4 Question

```python
class Question(BaseModel):
    question_id: UUID
    course_id: UUID; topic_id: str
    concept_ids: list[str]                 # primary concepts assessed (closed vocab: confirmed graph only)
    prerequisite_concept_ids: list[str]    # only confirmed/high-confidence edges
    learning_objective_ids: list[str]
    question_type: Literal["MCQ","TRUE_FALSE","NUMERIC","SHORT_TEXT","CODE"]
    cognitive_skill: Literal["remember","understand","apply","analyze"]
    difficulty: Literal[1,2,3,4,5]
    stem: str
    options: list[str] | None
    answer_key: AnswerKey                  # exact/numeric(tolerance)/regex/rubric
    rubric: list[RubricItem] | None        # per-criterion, boolean-gradable
    expected_misconception_ids: list[str]
    source_chunk_ids: list[UUID]
    lesson_block_ids: list[UUID]
    tag_confidence: float                  # from validator, see 6.6
    fingerprint_embedding_id: UUID         # near-duplicate detection
    status: Literal["ACTIVE","QUARANTINED","RETIRED"]
```

### 5.5 Evidence

```python
class AnswerEvidence(BaseModel):
    evidence_id: UUID                      # idempotency: unique
    student_id: UUID; question_id: UUID; attempt_id: UUID
    correct: float                         # 0.0 / 0.5 / 1.0 (partial allowed)
    grader_level: Literal["L0_RULE","L1_TESTS","L2_LLM_RUBRIC","L3_ESCALATED"]
    grader_confidence: float
    hints_used: int
    latency_ms: int | None
    kind: Literal["DIRECT","INFERRED"]     # INFERRED never counts toward MASTERED (6.1)
    concept_credit: dict[str, float]       # concept_id -> applied weight
    applied_at: datetime | None            # set when mastery update committed
```

---

## 6. Core algorithms (deterministic, versioned, unit + property tested)

### 6.1 Mastery engine (`packages/mastery`, policy `mastery_v1`)

State per (student, concept): `alpha, beta, updated_at, n_direct, review_successes`.
Prior `(alpha0, beta0) = (1, 1)`. `n_eff = alpha + beta - 2`.

Derived:
- `mastery = alpha / (alpha + beta)`
- `confidence = n_eff / (n_eff + 4)` (evidence mass, **not** LLM confidence)
- Status: `UNASSESSED` (n_eff < 1) -> `WEAK` (mastery < 0.5, conf >= 0.3) -> `DEVELOPING` -> `PROFICIENT` (mastery >= 0.75, n_direct >= 3 from >= 2 distinct questions, conf >= 0.5) -> `MASTERED` (PROFICIENT **and** >= 1 successful review answered >= 24 h after last learning event).

Update for one evidence item with base weight `w = w_diff * w_type * w_hint * w_tag`:

| Factor | Values |
|---|---|
| `w_diff` (correct) | difficulty 1-2: 0.7, 3: 1.0, 4-5: 1.3 |
| `w_diff` (incorrect) | inverse: difficulty 1-2: 1.3, 3: 1.0, 4-5: 0.7 (failing an easy item is stronger evidence) |
| `w_type` | MCQ 0.6 x (1 - 1/n_options) on correct; TRUE_FALSE 0.4; NUMERIC 1.0; SHORT_TEXT 0.9; CODE(tests) 1.2; L2 rubric x `grader_confidence` |
| `w_hint` | 1.0, 0.5 (1 hint), 0.25 (>= 2 hints) applies to correct evidence only |
| `w_tag` | `tag_confidence` clipped to [0.5, 1.0] |

Credit assignment (fixes v3.0's arbitrary "-5/-12/-18"):
- Role weights: primary concept 1.0, prerequisite concept 0.5.
- **Correct**: each tagged concept gets `alpha += w * role`.
- **Incorrect**: total negative mass `w` is split across tagged concepts proportional to `role * (1 - mastery_i)` (blame the weakest link), normalized to sum `w`; `beta += share_i`.
- Partial credit `c in (0,1)`: apply `c` as correct and `(1-c)` as incorrect.
- `INFERRED` evidence (e.g., a hard advanced item answered correctly implies its prerequisites are probably fine): `alpha += 0.3 * w * role`, flagged, excluded from `n_direct` and from MASTERED.

Forgetting (applied lazily on read/update): `alpha <- alpha0 + (alpha - alpha0) * 2^(-dt / H)` and same for `beta`, with half-life `H = 21 days * 1.6^review_successes`, capped at 180 days.

Topic aggregation: `topic_mastery` = weighted mean of concept masteries (default equal weights); **gating uses the minimum over core concepts**, not the mean.

Idempotency: an `evidence_id` is applied at most once (`applied_at` + unique constraint).

Required tests: monotonic (correct never lowers mastery; incorrect never raises), credit shares sum to `w`, decay is monotone toward prior, idempotent re-apply is a no-op, property tests via hypothesis, golden scenarios.

Later experiments (not v3.0): BKT, IRT difficulty calibration from logged data, FSRS scheduling - adopt only if simulation/pilot shows gain.

### 6.2 Spaced review

Per-concept interval ladder `[1, 3, 7, 14, 30, 60]` days (config). Pass at `review_successes` -> next rung; fail -> reset to rung 0 and apply normal negative evidence. Nightly job flags concepts whose decayed mastery falls below `review_threshold` (default 0.6) or whose due date passed; emits `REVIEW_DUE`. Planner inserts at most 3 review items at session start ("warm-up") and never during an active remediation frame.

### 6.3 Diagnostic (placement)

- Budget: <= 12 items total (config). Select the next concept maximizing `(descendant_count + 1) * (1 - confidence)` among unassessed concepts, 1-2 items each.
- User "I already know this" sets a **weak prior** (`alpha=2, beta=1`, flagged self-reported); it never satisfies a gate by itself.
- A correct answer on a deep concept yields `INFERRED` evidence on its confirmed prerequisites.

### 6.4 Planner + policy (`packages/planner`, policy `planner_v1`)

`PlannerPolicy.decide(state: PlanningState) -> PlannerDecision` evaluates rules **in order, first match wins**:

1. Hard stops: user PAUSE, session complete, budget exceeded (`BUDGET_EXCEEDED`).
2. Pending user directive (skip / explain simpler / more practice / I know this) -> mapped action; skipping mandatory topics returns `REQUIRE_CONFIRMATION`.
3. Review due and no active remediation frame -> `REVIEW_DUE`.
4. Active remediation frame not complete -> continue it (`PRACTICE_CONCEPT` / reassess); frame complete -> `RETURN_TO_TARGET`.
5. Latest assessment shows failing concept set `F` on target topic `T`: find weak prerequisites of `F` via **confirmed or high-confidence edges only**; choose the **deepest weak prerequisite** (topological depth) -> `TEACH_PREREQUISITE` and push a frame `{return_to: T, reason, attempts: 0}`. No weak prerequisite -> `RETEACH_WITH_NEW_STRATEGY` (change block mix/modality).
6. Topic not taught -> `TEACH_CURRENT_TOPIC`; taught, unchecked -> `GENERATE_MICRO_CHECK`; checked -> `GENERATE_QUIZ`.
7. Gate satisfied (default: min core-concept mastery >= 0.70, each with n_direct >= 3, latest quiz >= 0.6) -> `ADVANCE_TOPIC` respecting user order, priority, deadline.
8. Diagnostic pending -> `DIAGNOSE`.
9. Insufficient evidence or ambiguity -> `ASK_USER`.

Policy validation (after decide): never delete or silently skip user-confirmed content; never mark MASTERED without evidence; block unsafe/unknown actions; cap retries/cost; forbid executing code outside the sandbox.

**Loop guard** (per concept, config `max_remediation_attempts=3`, `min_progress_delta=0.05`): if attempts >= max with mastery delta < min -> escalation ladder, one rung per exhaustion:
`RETEACH_WITH_NEW_STRATEGY` -> deeper `TEACH_PREREQUISITE` -> `ASK_USER` -> `ESCALATE_MODEL` (stronger generation, if allowed by D-13) -> mark `BLOCKED_NEEDS_HUMAN` (emit `REMEDIATION_LOOP_BLOCKED`), continue with the next independent topic, surface in dashboard. Never loop forever.

### 6.5 Replan triggers (with hysteresis; v3.0 said "after every event")

| Trigger | Default condition | Effect |
|---|---|---|
| Single wrong answer | - | Record evidence only. No replan. |
| Repeated failure | >= 2 incorrect graded items (weight >= 0.5) on the same concept in the current topic window, or concept enters WEAK with conf >= 0.3 | Invalidate current plan segment; run planner |
| Quiz/check completed | always | Run planner on the batch |
| Strong performance | quiz >= 0.9 with >= 3 items and gate satisfied | Allow ADVANCE; later topics may be flagged `LIKELY_KNOWN` (needs confirmation) |
| Curriculum edited | any | Rebuild graph diff; invalidate plan |
| Mastery decay | nightly | `REVIEW_DUE` |
| User directive | immediate | Bypass cooldown |
| Deadline changed | any | Recompute pacing |

Cooldown: at most one new plan version per 60 s per student (directives excepted). Every plan version stores `plan_id, version, reason_codes, source_event_ids, diff(changes), planner_decision, created_at, versions`.

### 6.6 Assessment pipeline

**Question quality gate** (all must pass before `status=ACTIVE`; else regenerate <= 2x -> fallback (if allowed) -> drop):
1. Schema valid; `concept_ids` drawn from the **closed vocabulary** of confirmed graph concepts (constrained decoding, see 7.4).
2. Grounded: `source_chunk_ids` exist and belong to the course; answerability check - the model must answer the stem from the cited chunks only and match `answer_key`.
3. MCQ: exactly one key; distractor embedding similarity to key < 0.90; no duplicate options.
4. Tag validation: cosine(question, concept description) >= configured floor; `tag_confidence` recorded. Items below the floor are `QUARANTINED` (never update mastery, may be reviewed by a human).
5. Near-duplicate: cosine to any ACTIVE question in the course < 0.92.
6. Diversity in a quiz: coverage across target concepts and >= 2 cognitive skills.

**Grading pyramid** (D-06):
- **L0 rules**: MCQ/TF exact; numeric with tolerance; short text via normalized exact/regex/keyword sets. Deterministic, instant.
- **L1 tests**: code answers via sandboxed test runs (Phase 12).
- **L2 LLM rubric**: per-criterion boolean judgments with evidence quotes, temperature 0, constrained JSON. Run twice with shuffled criterion order; disagreement lowers confidence.
- **L3**: if `grader_confidence < tau` (config, default 0.7) -> stronger model (if allowed) else mark `UNCERTAIN`: apply evidence at weight x0.3, and show the student "AAA is unsure - flag this answer".
Track grader agreement vs human labels (Cohen's kappa) in evals.

---

## 7. Local AI stack

### 7.1 Model files and licensing
- Obtain Llama 3.2 3B Instruct by converting official HF weights (gated repo, accept license) or from a trusted GGUF publisher. Record sha256 of every model artifact in `models/MODELS.lock`; the Docker/K8s init step verifies it.
- Llama 3.2 Community License applies: keep "Built with Llama" attribution in product docs and follow the Acceptable Use Policy. If you distribute a fine-tuned derivative, its name must start with "Llama" per the license. **Re-read the current license text before distributing weights.**

### 7.2 Chat server (llama.cpp)

Generic profile (>= 8 GB GPU). **The 4 GB dev laptop uses the flags in 7.11 instead.**

```bash
llama-server \
  -m /models/Llama-3.2-3B-Instruct-Q4_K_M.gguf --alias aaa-slm \
  --host 0.0.0.0 --port 8080 \
  -c 16384 -np 4 -ngl 99 --metrics
# optional after benchmarking: --flash-attn --cache-type-k q8_0 --cache-type-v q8_0
```
Flags drift between llama.cpp releases: **verify against `llama-server --help` of the pinned build** and record the working command in `docs/runbooks/llama.md`.

Facts agents must respect:
- `-c` is the **total** context, divided across `-np` slots: `-c 16384 -np 4` = **4096 tokens per slot**. Prompts + output must fit a slot (budget below).
- Approx. memory (Llama 3.2 3B: 28 layers, 8 KV heads, head_dim 128): weights ~2 GB; fp16 KV ~112 KB/token => 16K total ctx ~ 1.9 GB. A 4 GB GPU works only with q8_0 KV cache and `-c 8192` (7.11); CPU-only works but is slow (CI uses `mock`).
- Parallel slots share one GPU's compute; concurrency improves aggregate throughput sub-linearly. Scaling worker pods does **not** scale generation. Capacity is `slots x GPUs`.
- Health: `/health` returns non-200 while loading. Metrics: `/metrics` (Prometheus).

Per-call token budget (4096/slot): system+task <= 400, student-state summary <= 300, retrieved evidence <= 1800 (<= 6 chunks x ~300), format/schema <= 200, output <= 1000, margin ~400. Context assembly code must enforce this and truncate by relevance rank.

Sampling defaults: extraction/classification/grading temp 0-0.1; lesson prose 0.3-0.5; question generation 0.5 with rotated cognitive-skill seeds.

### 7.3 Embedding server

```bash
llama-server -m /models/bge-small-en-v1.5-f16.gguf --embedding \
  -c 2048 -b 2048 -ub 2048 -np 1 --port 8081        # verify flags for pinned build
# BGE pooling = cls; Nomic = mean (normally read from GGUF metadata; set explicitly if wrong)
```
`Embedder` interface (`packages/retrieval`) hides model quirks:
- BGE-small: 512-token cap; optional query prefix `Represent this sentence for searching relevant passages: `.
- Nomic v1.5: **mandatory** prefixes `search_document: ` / `search_query: `; supports Matryoshka truncation (e.g., 256/512 dims) - decide dims once and store them.
- Always L2-normalize. Persist `embedding_model_id` and `dim` with every vector.
- Vector dimension is a **schema decision**. Switching model = new embeddings table (typed `vector(N)`) + re-embed job + flip `ACTIVE_EMBEDDING_MODEL`. Never mix models in one index.
- Chunk with the embedder's own tokenizer for token counts.
- Provide an in-process CPU fallback backend (sentence-transformers or fastembed) for environments without a second llama-server.

### 7.4 Structured output
- Generate JSON Schemas from Pydantic (`model_json_schema()`) and pass them to llama-server as `response_format: {"type":"json_schema", ...}` (or grammar). This guarantees syntactic validity, **not** semantic correctness - always re-validate with Pydantic.
- Keep schemas **flat**: enums, bounded arrays, no unions, no deep recursion, minimal `$ref`. llama.cpp supports only a subset of JSON Schema - test every schema in CI against the pinned build (`tests/ai_eval/test_schema_supported.py`).
- Closed vocabularies: inject concept ids as an `enum` per request. If the vocabulary exceeds ~200 ids, pre-filter candidates by embedding similarity (top 20) and use the shortlist as the enum.
- Retry policy: <= 2 retries on validation failure, then fallback (7.7).

### 7.5 Model Gateway and client

Interface (`packages/model_client`):
```python
class ModelGateway(Protocol):
    async def generate(self, task: str, prompt: PromptInput, *, ctx: CallContext) -> GenerateResult
    async def stream(self, task: str, prompt: PromptInput, *, ctx: CallContext) -> AsyncIterator[str]
    async def generate_structured(self, task: str, prompt: PromptInput, schema: type[T], *, ctx: CallContext) -> StructuredResult[T]
    async def classify(self, task: str, prompt: PromptInput, labels: Sequence[str], *, ctx: CallContext) -> ClassifyResult
    async def embed(self, texts: Sequence[str], kind: Literal["document","query"]) -> EmbedResult
```
Providers: `LlamaCppProvider` (OpenAI-compatible HTTP), `CloudProvider` (adapter per vendor), **`FakeProvider`** (deterministic canned/replay outputs; used by `mock` profile, CI, and all non-eval tests).

Gateway responsibilities: global priority lanes (`interactive` > `prefetch` > `batch`; caps e.g. 4/2/1 in-flight - config), timeouts, retry with jitter, circuit breaker, routing (7.7), telemetry row per call (`provider, model, task, prompt_version, adapter_version, in/out tokens, latency, success, fallback_used, cache_hit, validator_result`; **no raw student content by default**), response caching (Redis) with keys that include `course_version, topic_id, block_type, level_bucket, model_id, adapter_version, prompt_version, retrieval_version`. Never cache fully personalized output across users.

Task registry (`TaskSpec`: tier, schema, temperature, max_tokens, ctx budget, validator, fallback rule, lane, cache policy). Initial tasks:

| Task | Tier | Output | Notes |
|---|---|---|---|
| `syllabus_unit_extract` | SLM | JSON | one unit per call, temp 0 |
| `concept_extract`, `objective_extract` | SLM | JSON | closed schema |
| `prereq_propose` | SLM | JSON edges + confidence | edges start `PROPOSED` |
| `lesson_block_*` | SLM | Markdown stream | grounded, cited |
| `question_generate`, `question_tag` | SLM | JSON | closed concept enum |
| `answer_grade_rubric` | SLM | JSON booleans | temp 0, 2 passes |
| `misconception_classify` | SLM | enum | closed label set |
| `decision_explain` | SLM | text | templated first |
| `diagnose_uncertain`, `lesson_hard` | FALLBACK | JSON/MD | only on triggers |

### 7.6 Routing policies
`LOCAL_FIRST` (default), `LOCAL_ONLY` (when `allow_cloud_fallback=false`), `QUALITY_FALLBACK`, `COST_AWARE`, `LATENCY_AWARE`, `OFFLINE_ONLY`.

### 7.7 Fallback triggers
Fall back (only if `allow_cloud_fallback`) when: validator fails after retries; grader confidence < tau; retrieval insufficient and the task requires grounding; loop guard reaches `ESCALATE_MODEL`; two evaluators disagree. If cloud is not allowed: degrade gracefully (mark `LOW_CONFIDENCE`, ask the user, or queue for later) - never silently drop. Before any egress: PII redaction (emails, phones, names from profile, roll/USN patterns), emit `MODEL_FALLBACK_USED`.

### 7.8 Resilience
Retry local -> retry -> fallback (if allowed) -> job `FAILED reason=MODEL_UNAVAILABLE` with checkpoints intact and a resume endpoint.

### 7.9 Go/no-go gate for the 3B model (Phase 4, before building on it)
Run the benchmark harness on the golden sets with grammar-constrained decoding. If, **after** prompt iteration (before any fine-tuning), the model misses these floors, stop and choose: (a) fine-tune the failing task (Phase 12 pulled forward), (b) route that task to fallback, or (c) evaluate another model through the identical pipeline (an 8B Q4_K_M is ~5 GB and does **not** fit the 4 GB dev GPU; on dev hardware try a same-size challenger such as Qwen2.5-3B-Instruct or Phi-3.5-mini, or use cloud fallback). Floors (initial; re-baseline): syllabus topic-F1 >= 0.80, question-tag precision >= 0.85 (after validator), rubric-grader kappa >= 0.60 vs human, lesson grounding pass rate >= 0.85.

### 7.10 Fine-tuning (LoRA/QLoRA; Phase 12)

Fine-tune for **behavior/format/classification**, not for knowledge (RAG owns knowledge). Priority by expected ROI: (1) syllabus->structured extraction, (2) question tagging + misconception classification, (3) rubric grading, (4) lesson style. **Do not fine-tune the planner** (deterministic).

Data:
- `data/datasets/<task>/{train,val,test}.jsonl` in chat format with provenance (`source, teacher_model, teacher_license_ok, reviewer, course_id`).
- **Split by course, not by row.** Hold out unseen courses for test. Decontaminate against benchmarks.
- Teacher outputs: use a teacher whose license permits training on its outputs (open-weight teachers are safest); **verify provider terms before distilling from any API model.** Human-review >= 10% of samples; reject on schema/grounding failures.
- Start small (hundreds to low thousands of high-quality examples per task); scale only if the benchmark shows headroom. Production usage data becomes training data only via privacy filtering + human review + approved dataset.

Training (starting point, tune empirically): base = HF `Llama-3.2-3B-Instruct`; QLoRA NF4 + double quant; LoRA `r=16, alpha=32, dropout=0.05`, targets `q,k,v,o,gate,up,down`; lr `2e-4` cosine, warmup ~3%, 2-3 epochs, effective batch ~16, max seq 2048-4096; **exact Llama 3 chat template identical to serving**; loss on assistant tokens only; early stop on validation loss from unseen courses.

Export and ship:
```bash
# 1) merge adapter into bf16 base (NOT into the quantized GGUF)
# 2) convert + quantize with the pinned llama.cpp
python convert_hf_to_gguf.py merged/ --outtype bf16 --outfile aaa-slm-bf16.gguf
llama-quantize aaa-slm-bf16.gguf aaa-slm-Q4_K_M.gguf Q4_K_M
# optional, benchmark-gated: importance matrix from in-domain text (llama-imatrix) before quantizing
```
- Always benchmark the **quantized GGUF** (that is what ships) against the untuned baseline on: target-task metrics, all other tasks (regression), and a small general-instruction sanity set.
- Promote only if target metric improves >= configured margin **and** no critical task regresses > configured tolerance. Record `adapter_version` in `MODELS.lock`.
- Multiple task adapters can be loaded as GGUF LoRA adapters by llama-server; start with one merged model; consider adapter hot-swap later (requests with different adapter configs may not batch together - measure).

---

### 7.11 Dev-laptop profile (RTX 3050 4 GB VRAM, 16 GB RAM, i5-12500H) - the default target hardware

**VRAM budget (4 GB):** weights ~2.0 GB + CUDA context/compute buffers ~0.3-0.5 GB + KV cache. KV per token: fp16 ~112 KB, q8_0 ~60 KB. At `-c 8192`: fp16 ~0.9 GB (too tight), **q8_0 ~0.5 GB (use this)**. Total ~2.9-3.0 GB, leaving ~1 GB headroom for the driver/display.

```bash
# run NATIVELY on the host (not in Docker) - verify flags against `llama-server --help` of the pinned build
llama-server -m Llama-3.2-3B-Instruct-Q4_K_M.gguf --alias aaa-slm \
  --host 127.0.0.1 --port 8080 \
  -c 8192 -np 2 -ngl 99 -b 512 -ub 512 \
  -fa on --cache-type-k q8_0 --cache-type-v q8_0 --metrics
# -fa (flash attention) is required for a quantized V cache; syntax differs by build (bare -fa vs on|off|auto)
```
- `-c 8192 -np 2` = **4096 tokens per slot** (the Section 7.2 per-call budget still holds).
- OOM ladder, in order: `-ub 256` -> `-np 1 -c 6144` -> `-ngl 24` (partial CPU offload, slower). Record the final working command in `docs/runbooks/llama.md`.
- Keep the system/task prefix first and byte-identical across calls so llama-server's prompt cache is reused.
- **Embeddings run on CPU, never on the 4 GB GPU:** BGE-small (or Nomic) via `llama-server --embedding -ngl 0 -t 4 -np 1 --port 8081`, or in-process `fastembed`/ONNX. Both are ~100-140M params and fast enough on 12 threads.

**Expected performance (estimates - measure in Phase 4 and overwrite):** decode ~30-60 tok/s single stream; prompt processing ~500-1500 tok/s; a 3K-token prompt gives ~2-5 s to first token; a full lesson (~800 output tokens) takes ~15-30 s. Two concurrent slots raise aggregate throughput sub-linearly and slow each stream. Laptop GPUs throttle: plug in, use performance mode, warm up before benchmarks, log clocks/temps in benchmark reports.

**Capacity:** 2 slots x 1 GPU = one active student plus background work. Gateway lane caps for this profile (total in-flight <= 2): `interactive` up to 2; `prefetch` max 1 and only when no interactive request waits; `batch` only when idle. Consequences: prefetch of the next lesson matters more than parallel block generation (set intra-lesson concurrency to 1 here); multi-student load tests need a larger/cloud GPU or `FakeProvider` with simulated latency.

**RAM budget (16 GB):** host OS + browser 4-5 GB; Docker/WSL2 capped at ~6 GB (`.wslconfig`: `memory=6GB`, `processors=8`); llama-server + embedder ~1-1.5 GB. Postgres `shared_buffers` 256 MB, Redis `maxmemory 128mb`. Run the stack in `mock` profile for day-to-day work; start the real model only for evals, perf, and demos.

**Docker/OS:** a compose stack reaches the host model via `MODEL_BASE_URL=http://host.docker.internal:8080` (Windows/macOS Docker Desktop; on Linux add `extra_hosts: host.docker.internal:host-gateway`). Avoid GPU passthrough into containers on this machine unless needed; use the official llama.cpp CUDA release binary on the host.

**Not feasible locally:** Llama 8B-class models at interactive speed; QLoRA training of the 3B at useful sequence lengths (>= 2048) - train on a rented/Colab/Kaggle 16 GB GPU. Local machine handles merge (bf16 merge needs ~7 GB RAM - close other apps), GGUF conversion, quantization, and benchmarking. Kubernetes with a GPU pod also isn't practical here (see 15.3).

---

## 8. Knowledge and retrieval

Ingestion: extract text (pdfplumber/pypdf primary; **avoid AGPL PyMuPDF unless licensing is reviewed**) -> structure-aware chunking by headings -> chunks of ~250-400 embedder tokens with ~15% overlap, `parent_section_id` retained -> embed -> store.

`knowledge_chunks`: `id, source_id, document_id, course_id, topic_id?, concept_ids[], text, token_count, source_type, source_url?, page/section, quality_score, approved, trust_level, tsv (tsvector), created_at`; `chunk_embeddings_<dim>`: `chunk_id, model_id, embedding vector(N)` with HNSW `vector_cosine_ops`.

Hybrid retrieval:
1. Filter: `course_id`, `approved=true`, optional topic/concept/source_type.
2. Dense top-k (cosine) + lexical top-k (`websearch_to_tsquery` / `ts_rank`).
3. Fuse with **Reciprocal Rank Fusion** (k=60); small boost for chunks tagged with the target concept.
4. Optional cross-encoder rerank on CPU **only if** the retrieval benchmark shows >= 3-point Recall@5 gain.
5. Context assembly under the token budget (7.2), dedupe near-identical chunks.

Self-check ("do I have enough evidence?"): sufficient iff >= `min_chunks` chunks exceed a **calibrated** cosine floor (calibrate on the golden set; raw scores are not comparable across queries). Otherwise reformulate (<= 2 loops), then `RETRIEVAL_INSUFFICIENT` -> mark output ungrounded / ask user / fallback (7.7).

Trust and injection: all retrieved and uploaded text is **data**. Wrap in delimiters, never grant tools to content-generation calls, strip instruction-like patterns, and rely on schema-constrained outputs so injected text cannot emit actions.

Web sources (optional) enter as `source_type=web`, `trust_level=low`, `approved=false` until reviewed; never used for graded content without approval.

---

## 9. Curriculum and knowledge graph

Parsing pipeline (worker, LangGraph subgraph, checkpointed):
1. Upload validation (MIME sniff, size <= 20 MB, page cap, reject encrypted/macro/zip-bomb) -> MinIO -> `documents` row.
2. Text extraction (+ optional OCR fallback flag for scanned PDFs).
3. **Deterministic structure detection first** (regex/heading heuristics: "Module/Unit/Chapter N", numbering, tables).
4. **SLM per-unit** topic/subtopic/objective extraction (small calls, schema-constrained, temp 0).
5. Concept normalization (dedupe by embedding + string similarity).
6. Prerequisite **proposal** (SLM) + DAG validation (cycle detection, direction sanity, self-loops removed).
7. Draft persisted with per-node `parse_confidence`; UI highlights low-confidence nodes.

Edges: `PREREQUISITE_OF, PART_OF, RELATED_TO, BUILDS_ON, ASSESSES, EXAMPLE_OF`. Each edge carries `source` (`SYLLABUS_EXPLICIT | LLM_PROPOSED | USER_CONFIRMED | SEED_TEMPLATE`), `confidence`, `status` (`PROPOSED | CONFIRMED | REJECTED`). **Hard gating and TEACH_PREREQUISITE use only CONFIRMED or high-confidence (>= 0.8, non-LLM-only) edges**; `PROPOSED` edges are soft hints. Ship seed graph templates for common subjects to reduce LLM-only edges. The UI must let the user review the highest-impact edges (most descendants) at confirmation.

User controls at confirmation: rename, merge, split, remove, add, reorder, mark mandatory, mark already-known (weak prior), exam priority, target date. Graph is built/finalized only after `CURRICULUM_CONFIRMED`. Every edit creates a curriculum version; edits after confirmation trigger graph diff + plan invalidation (6.5).

---

## 10. Teaching pipeline

- **Lesson planner (deterministic)** picks the block list from topic type, mastery, failure history, preferences, and the current remediation strategy (`RETEACH_WITH_NEW_STRATEGY` changes block mix/modality).
- **Generation**: one LangGraph subgraph per lesson job. Order: retrieve -> overview (stream) -> explanation -> example -> misconception -> checkpoint -> summary. Independent blocks may run concurrently up to available lane capacity (default 2 per lesson); dependent ones stay ordered. Persist after each block and emit `LESSON_BLOCK_READY` (SSE renders progressively).
- **Prefetch**: when a topic is likely next, enqueue `prefetch` lane jobs; cache by the key in 7.5.
- **Block validation** (cheap, mostly non-LLM; a 3B model does not judge itself): cited chunk ids exist; each factual paragraph has lexical/embedding support >= floor in cited chunks; numbers/equations appear in sources or are checked with sympy/python where possible; length and reading-level bounds; no duplicate of earlier blocks. Fail -> regenerate <= 2 -> fallback (if allowed) -> emit as `grounded=false`.
- Personalization is applied via a compact student-state summary (<= 300 tokens), never raw history.

---

## 11. Data model (PostgreSQL; Alembic migrations)

Core tables (behavior-driven; add columns as needed): `users, courses, course_members, documents, document_versions, curricula, curriculum_versions, curriculum_nodes, curriculum_edges, concepts, concept_relationships, learning_objectives, knowledge_sources, knowledge_chunks, chunk_embeddings_<dim>, student_profiles, student_concept_state, student_topic_state, misconceptions, learning_sessions, lessons, lesson_blocks, quizzes, questions, question_concepts, question_prerequisites, question_sources, attempts, answer_evidence, learning_plans, learning_plan_versions, plan_items, plan_frames, learning_events, jobs, model_requests, resources, review_schedule, idempotency_keys`.

Required constraints and indexes:
- `learning_events.event_id` unique; `answer_evidence.evidence_id` unique; `attempts (student_id, idempotency_key)` unique; `jobs.idempotency_key` unique.
- `jobs (status, priority DESC, run_after, created_at)` index for claiming; partial index on pending.
- `student_concept_state (student_id, concept_id)` PK; `student_concept_state` updated only via the mastery repository.
- HNSW index per embeddings table; GIN on `knowledge_chunks.tsv`.
- Row-level scoping: every student-owned row carries `student_id`; API enforces ownership + RBAC (`student`, `instructor`, `admin`).

`jobs`: `id, type, payload jsonb, status (PENDING|RUNNING|PARTIAL|SUCCEEDED|FAILED|CANCELLED|RETRYING), priority, lane, attempts, max_attempts, run_after, locked_by, lease_expires_at, heartbeat_at, idempotency_key, parent_job_id, result_ref, error_code, created_at, updated_at`.

---

## 12. Jobs, events, sessions

### 12.1 Job claiming
```sql
UPDATE jobs SET status='RUNNING', locked_by=:worker, lease_expires_at=now()+interval '60 seconds', attempts=attempts+1
WHERE id = (SELECT id FROM jobs
            WHERE status IN ('PENDING','RETRYING') AND run_after <= now()
            ORDER BY priority DESC, created_at
            FOR UPDATE SKIP LOCKED LIMIT 1)
RETURNING *;
```
Workers heartbeat every ~15 s. A reaper returns expired-lease jobs to `RETRYING` (respecting `max_attempts`). Redis publishes a wake-up on insert; workers also poll every few seconds so Redis loss is harmless.

### 12.2 Transactional creation
Domain write + `learning_events` row + follow-up `jobs` rows (from a static event->job routing table) commit in **one transaction**. No separate outbox needed.

### 12.3 Session FSM
`CREATED -> PLANNING -> RETRIEVING -> TEACHING -> CHECKPOINT -> ASSESSING -> DIAGNOSING -> REPLANNING -> (TEACHING | ADVANCE | PAUSED | COMPLETE)`. Transitions are a table in code; each transition is persisted with `event_id`; illegal transitions raise. Any state is resumable after worker restart.

### 12.4 Idempotency
`POST /attempts` requires `Idempotency-Key`. Mastery application, plan-version creation, and attempt recording are safe to retry via unique constraints + `applied_at` + event ids. Replaying the same event twice must produce identical DB state (tested).

### 12.5 Failure recovery
Kill a worker mid-job -> lease expires -> another worker resumes from the last LangGraph/Postgres checkpoint; no duplicate evidence, no duplicate plan versions.

---

## 13. API (`/api/v3`)

Groups: `auth, users, courses, documents, curriculum, learning-graphs, sessions, lessons, quizzes, attempts, mastery, plans, jobs, analytics, resources`.

Key endpoints:
```
POST   /courses
POST   /courses/{id}/syllabus                 -> 202 + job_id
POST   /curriculum/{id}/parse                 -> 202 + job_id
GET    /curriculum/{id}/draft
PATCH  /curriculum/{id}/draft                 (edit ops: rename/merge/split/remove/add/reorder/mark)
GET    /curriculum/{id}/graph                 (nodes, edges with status/confidence)
PATCH  /curriculum/{id}/edges/{edge_id}       (confirm/reject)
POST   /curriculum/{id}/confirm
POST   /sessions                              GET /sessions/{id}
GET    /sessions/{id}/lesson                  (blocks so far + job status)
GET    /sessions/{id}/events                  (SSE: progress, LESSON_BLOCK_READY, PLAN_REPLANNED ...)
POST   /sessions/{id}/checkpoint
GET    /sessions/{id}/quiz
POST   /attempts                              (Idempotency-Key; returns grading result + next action when L0)
GET    /students/me/mastery
GET    /students/me/plan                      GET /students/me/plan/why  (decision + evidence + reason codes)
POST   /students/me/directives                (skip / simpler / more practice / I know this)
GET    /jobs/{id}                             GET /jobs/{id}/events (SSE)      POST /jobs/{id}/resume
GET    /students/me/export                    DELETE /users/me   (privacy)
GET    /healthz  /readyz  /metrics
```
Rules: API never blocks on LLM work (returns 202 + job); SSE for progress; consistent error envelope; OpenAPI is generated and diffed in CI (breaking changes need an ADR).

---

## 14. Security and privacy

- Auth: JWT (short-lived access + refresh), Argon2/bcrypt hashing, RBAC, rate limiting (Redis), request size limits, input validation everywhere.
- Uploads: MIME sniffing, size/page limits, parse in worker with CPU/memory/time limits, never execute embedded content.
- AI: prompt-injection defense (Section 8), tool allowlists per agent (Curriculum: parser + draft write; Retrieval: vector search + approved web; Tutor: retrieval + model; Planner: read state + write proposal), output validation, no tools for content-generation calls, provider secrets never in prompts/logs.
- Privacy: PII minimization; logs and telemetry store hashes/ids, not raw student answers, unless debug sampling is explicitly enabled with a TTL; cloud egress only under D-13 with redaction; `GET /students/me/export` and `DELETE /users/me` (cascade + vector/object cleanup). Consider India's DPDP Act obligations if deployed beyond a controlled pilot.
- Secrets: env/Secrets manager only; never in Git; `.env.example` has placeholders.
- Code execution (Phase 12): sandbox job, CPU/mem/time limits, network off, isolated FS.
- Supply chain: pin dependencies and container digests; verify model sha256.
- Audit log for curriculum edits, confirmations, deletions, and policy `REQUIRE_CONFIRMATION`/`BLOCK` outcomes.

---

## 15. Observability and deployment

### 15.1 Observability
- OpenTelemetry traces with one `trace_id` from API -> job -> planner -> gateway -> DB; structured logs with `request_id, session_id, run_id, node_id, agent, task`.
- Prometheus metrics: API latency, job latency/queue wait, per-task model latency/tokens/tok-s, gateway lane depth, cache hit rate, retrieval latency, validator failure rate, fallback rate, planner action counts, invalid-action count, loop-guard trips, GPU utilization (scrape llama-server `/metrics`).
- "Why" trace: `GET /students/me/plan/why` reconstructs decision <- evidence <- questions <- concepts from stored ids.

### 15.2 Compose (P0)
Profiles via `AAA_PROFILE`: `mock` (FakeProvider, no model; CI default), `cpu` (llama-server CPU), `gpu` (llama-server CUDA). Services: `api, worker, model_gateway, frontend, postgres(+pgvector), redis, minio, llama-chat, llama-embed`. Model files mounted from a volume, never baked into images. Dev laptop: run llama-server natively on the host and point `MODEL_BASE_URL` at it (7.11).

### 15.3 Kubernetes (P2, Phase 11)
- Dev laptop (4 GB GPU, 16 GB RAM): validate manifests on kind/k3d with the `mock` profile only; validate the GPU model pod later on a cloud GPU node.
- Namespaces: `aaa`, `data` (or managed services), `observability`. Kustomize `base` + `overlays/{dev,staging,prod}`.
- Workloads: Deployments for `frontend, api, worker, model-gateway`; **model server** (llama.cpp official CUDA image pinned by digest) as a Deployment/StatefulSet with `nvidia.com/gpu: 1`, node selector + tolerations, PVC for model files, init container that downloads and **verifies sha256** from object storage, `startupProbe` generous for model load, `readinessProbe` on `/health`. **Replicas = number of GPUs; no CPU-based HPA on the model server.**
- Jobs/CronJobs: syllabus ingestion (or worker-handled), knowledge indexing, nightly mastery-decay/review-due, cleanup.
- Worker autoscaling with KEDA on pending-jobs count (Postgres query or Prometheus metric) - note this scales CPU-side work, not generation throughput.
- ConfigMaps for non-secret config, Secrets for credentials, Ingress (SSE-friendly timeouts), PodDisruptionBudgets, resource requests/limits, NetworkPolicies (model server reachable only from gateway; cloud egress only from gateway).
- Postgres/Redis/MinIO: managed services or operator (e.g., CloudNativePG) - do not hand-roll HA.
- Acceptance: kill a worker pod mid-job -> job resumes; scale workers 1->3 under load; rolling update without dropping SSE clients beyond reconnect.

---

## 16. Evaluation

### 16.1 Principles
- Evaluate **decisions**, not just text. Benchmark gates model/prompt promotion. Report unseen-course results only.
- Never let the 3B model be the sole judge of its own output. Use human goldens + a stronger judge model (offline, allowed data) with periodic human spot checks; report judge-human agreement.

### 16.2 Golden sets (MVP sizes; grow over time)
~20 syllabi (with gold topic/concept/edge annotations), ~60 tutoring cases, ~150 questions (with concept tags), ~100 student answers (human-graded), ~50 diagnosis cases, ~50 planning cases, retrieval QA pairs per course. Layout: `data/goldens/<suite>/`.

### 16.3 Student simulator (`packages/evalkit`)
`SimStudent`: hidden true mastery vector per concept, guess/slip rates, learning gain per lesson, forgetting. Scenarios: fast learner; **hidden weak prerequisite**; noisy guesser; **plateau (stuck concept)** must trigger the loop guard; forgetter must trigger reviews. Metrics: mastery-estimate MAE vs truth after N items; steps-to-gate vs baselines (fixed linear order; simple threshold rule); loop rate; premature-advance rate; unnecessary-remediation rate; invalid-action rate. Simulation is the primary evidence for planner value until a real pilot exists. Run in `make sim` and CI (fast subset).

### 16.4 Initial targets (re-baseline after first measurements; changing a target needs an ADR)

| Area | Metric | Initial target |
|---|---|---|
| Structured output | schema validity with constrained decoding | >= 99% |
| Syllabus | topic-level F1 vs gold (pre-user-edit) | >= 0.80 |
| Retrieval | Recall@5 on golden QA | >= 0.85 |
| Questions | pass quality gate on first try | >= 70%; final ACTIVE tag precision >= 0.85 |
| Grading | L0 exactness | 100%; L2 kappa vs human >= 0.60 |
| Lessons | grounding validator pass rate | >= 0.85 |
| Planner | action accuracy on planning goldens | >= 0.90; **invalid action rate 0** |
| Simulation | loop rate | 0 infinite loops; premature advance <= 5% |
| Latency (>= 8 GB GPU) | lesson time-to-first-block, cache miss, p50 | <= 4 s |
| Latency (dev laptop, 7.11) | same | <= 8 s (re-baseline in Phase 4); prefetch-hit path <= 1 s |
| Reliability | job resume after worker kill | 100% no duplicate evidence |

### 16.5 End-to-end acceptance (mandatory regression, runs on `mock` profile)
```
register -> upload syllabus -> parse -> user edits (remove 1, add 1) -> confirm -> graph built
-> diagnostic -> plan v1 -> lesson (blocks stream) -> checkpoint -> quiz
-> student fails on a concept whose prerequisite is weak -> evidence recorded (traceable)
-> mastery updated -> plan v2 (TEACH_PREREQUISITE, frame pushed) -> practice -> reassess passes
-> RETURN_TO_TARGET -> original topic passes -> ADVANCE_TOPIC -> /plan/why explains every step
```
Plus: ablation runs (fixed-order baseline vs AAA planner) recorded in `docs/eval/`.

### 16.6 Experiment tracking
Each experiment (`SLM choice, prompts, retrieval, mastery formula, planner policy, lesson composition, fine-tune`) records: hypothesis, baseline, dataset, metrics, result, decision, in `docs/experiments/NNNN.md` (or MLflow/W&B if adopted).

---

## 17. Delivery phases (agent task lists with acceptance)

The v3.0 order built the differentiator (mastery/planner) late. Revised order builds the **deterministic core and simulator early** (no model needed), then integrates AI.

**Phase 0 - Contract lock (P0).** Create repo skeleton, this spec as `AGENTS.md`, ADR folder with D-01..D-15, Pydantic schemas (Section 5), event/enum definitions, import-linter contracts, `docs/STACK.md`. *Accept:* `make check` passes on empty scaffolding; schemas round-trip JSON.

**Phase 1 - Foundation (P0).** FastAPI app, async SQLAlchemy, Alembic, Redis, MinIO, config, structured logging, health/ready endpoints, Docker Compose (`mock` profile), Makefile targets, CI workflow; port audited v2 modules (auth/JWT, hashing, Alembic env, MinIO client, observability wiring, test fixtures). *Accept:* `make up && make migrate && make test` green; `/readyz` verifies DB+Redis+MinIO.

**Phase 2 - Curriculum ingestion (P0).** Upload -> validation -> extraction -> structure detection -> (FakeProvider-backed) unit extraction -> draft -> edit ops -> confirm -> versioning; jobs table + worker loop (claim/lease/heartbeat/reaper) + SSE progress. *Accept:* PDF -> draft -> edits -> confirmed curriculum in integration test; worker kill test passes.

**Phase 3 - Graph + deterministic core (P0).** Graph model with edge status/confidence, DAG validation, seed templates; **mastery engine, replan triggers, planner policy, plan stack, loop guard, spaced review, diagnostic selection**; student simulator + scenarios. *Accept:* property tests green; `make sim` shows loop rate 0, hidden-weak-prerequisite scenario reaches `TEACH_PREREQUISITE` then `RETURN_TO_TARGET`; planner beats fixed-order baseline on steps-to-gate.

**Phase 4 - Model layer + benchmarks (P0).** llama.cpp runbook + Compose profiles `cpu|gpu`, `LlamaCppProvider`, `FakeProvider`, gateway service (lanes, retries, breaker, telemetry, cache), TaskSpec registry, structured-output plumbing + schema-support tests, benchmark harness v0, **go/no-go gate (7.9)** and embedder comparison scaffolding. *Accept:* same app code runs on `mock` and `gpu/cpu` by config; benchmark report committed; go/no-go decision recorded as ADR.

**Phase 5 - Retrieval (P0).** Chunking, `Embedder` (BGE default, Nomic switchable, prefixes handled), pgvector tables + HNSW, FTS, RRF, self-check, provenance, calibrated floors, retrieval golden set. *Accept:* query -> ranked cited context; Recall@5 measured; embedder decision recorded (D-03 rule).

**Phase 6 - Teaching (P0).** Lesson planner, block generators, staged SSE streaming, cache, block validators, prefetch. *Accept:* student opens a lesson and sees blocks progressively; cache hit path measured; validators reject synthetic bad blocks in tests.

**Phase 7 - Assessment (P0).** Question generation + quality gate, closed-vocab tagging, quarantine, grading pyramid (L0 + L2 + escalation), misconception mapping, evidence records, near-duplicate check. *Accept:* one wrong answer yields traceable evidence (question -> concepts -> mastery delta); UNCERTAIN path works; grader kappa measured.

**Phase 8 - Closed loop (P0).** Session FSM, event router, synchronous L0 path (answer -> evidence -> mastery -> replan check -> planner -> next action in one transaction), plan versions + `/plan/why`, user directives, frontend flows (upload/confirm, lesson, quiz, dashboard with "why", learning-map diff). *Accept:* Section 16.5 e2e green; demo scenario reproducible.

**Phase 9 - Async performance + reliability (P1).** Priority lanes end-to-end, parallel block generation within lane caps, prefetch, checkpoint/resume on every pipeline, retries/fallback/circuit breaker, idempotency test suite. *Accept:* no LLM workflow blocks an API request; replaying events yields identical state; fallback path tested with fault injection.

**Phase 10 - Observability + security hardening (P1).** OTel traces, Prometheus/Grafana dashboards, alert rules, PII redaction tests, upload fuzzing, injection test corpus, export/delete endpoints. *Accept:* one student action traceable API -> worker -> planner -> gateway -> DB; injection corpus cannot cause invalid actions.

**Phase 11 - Kubernetes (P2).** Manifests per Section 15.3, local cluster (kind/k3d/minikube) first, then small cloud cluster; GPU model deployment; KEDA worker scaling; probes; NetworkPolicies. *Accept:* chaos tests from 15.3 pass.

**Phase 12 - Fine-tuning + optimization (P2).** (Train on a rented/Colab/Kaggle 16 GB GPU; the 4 GB laptop only merges, quantizes, and evaluates.) Dataset build, QLoRA experiments per 7.10, quantized-GGUF evaluation, optional imatrix/KV-cache quantization experiments, adapter promotion gate, cost/latency tuning. *Accept:* a promoted adapter (or a documented decision not to promote) backed by benchmark reports; only now make claims about SLM improvement.

Per-feature implementation order (kept): domain schema -> API contract -> service logic -> agent logic -> persistence -> tests -> observability -> performance benchmark -> UI -> docs.

---

## 18. Definition of done (v3.0)

- [ ] Curriculum: upload, parse, interactive edit, confirm, graph (edges with status/confidence)
- [ ] AI: llama.cpp SLM + embedding path + optional fallback + gateway + benchmark harness + recorded go/no-go
- [ ] Retrieval: hybrid search, provenance, calibrated self-check
- [ ] Teaching: block composition, progressive streaming, validation, caching
- [ ] Assessment: quality gate, closed-vocab tagging, grading pyramid, misconception mapping
- [ ] Adaptation: mastery_v1, diagnosis, replan triggers with hysteresis, plan stack/versions, loop guard, spaced review
- [ ] Reliability: idempotency, lease-based recovery, fallback, checkpoint resume
- [ ] Evidence: simulator results vs baselines, benchmark reports on unseen courses, e2e demo green
- [ ] Ops: Compose (P0); observability + security (P1); Kubernetes + fine-tuning (P2, if reached)
- [ ] Docs: ADRs, runbooks (llama.cpp, model artifacts, eval), API OpenAPI snapshot

---

## 19. Risks and open questions

1. **3B capability ceiling** - mitigated by constrained decoding, deterministic grading/planning, go/no-go gate, task-level fallback, upgrade path to a larger GGUF via the same pipeline.
2. **Single-GPU concurrency** - capacity is slots x GPUs; document expected concurrent students per profile after Phase 4 measurements.
3. **No human study yet** - until a pilot with consent/ethics review exists, claim architecture + simulation results only.
4. **Prerequisite graph quality** - LLM-proposed edges are noisy; keep status/confidence, seed templates, user review of high-impact edges.
5. **Scope/schedule** - P0 is the deliverable; P2 items are explicitly optional. Cut from the bottom.
6. **English-only** - swap embedder (and re-index) for multilingual courses.
7. **Tight hardware (4 GB VRAM, 16 GB RAM)** - measure tok/s and record final `-c/-np`/KV type in `docs/runbooks/llama.md`; single-user capacity only; multi-student load tests need a bigger or cloud GPU.

---

## Appendix A - Review log (v3.0 -> v3.1)

| # | Fault in v3.0 | Fix |
|---|---|---|
| A1 | Mastery formula deferred ("should be versioned") though it is the core differentiator; example deltas (-5/-12/-18) had no mechanism | Concrete Beta-posterior model, weights, credit assignment, decay, status rules (6.1) |
| A2 | Planner was an LLM proposing actions with self-reported confidence (uncalibrated, esp. at 3B) | Deterministic rule engine + policy; confidence derived from evidence (D-05, 6.4) |
| A3 | Overlapping/missing actions (REVIEW_TOPIC vs REVISIT_FOUNDATION; no return-to-target though the demo needs it) | Consolidated enum + plan-frame stack + RETURN_TO_TARGET (5.1, 6.4) |
| A4 | "Replan after every event" causes thrash and cost | Trigger table with hysteresis, cooldown, single-answer no-replan (6.5) |
| A5 | Differentiator built in sprints 7-8, after infra/model work | Reordered: deterministic core + simulator in Phase 3 (17) |
| A6 | LLM graded and tagged everything; a 3B model mis-tags and mis-grades | Grading pyramid; closed-vocab constrained tagging; quality gate; quarantine (6.6) |
| A7 | Structured output asserted without a mechanism | llama.cpp JSON-schema/grammar constraints + Pydantic revalidation + schema-support CI test (7.4) |
| A8 | Prose lessons + JSON wrapping would break streaming and stress a 3B model | Markdown-per-block generation (D-12) |
| A9 | Four overlapping state mechanisms (LangGraph, job checkpoints, session FSM, planner queue) and Redis checkpointing | One macro FSM in Postgres; LangGraph bounded per job with Postgres checkpointer (D-09) |
| A10 | Redis queue + Postgres truth => dual-write inconsistency; idempotency listed but no mechanism | Postgres jobs with SKIP LOCKED + transactional job creation; Redis disposable (D-08, 12) |
| A11 | Vector DB "Chroma/future" separate from Postgres; "hybrid" retrieval had no lexical leg | pgvector + FTS + RRF (D-04, 8) |
| A12 | Embedding choice unresolved; prefix requirements, dimensions, 512-token cap, English-only never mentioned | Decision rule, Embedder abstraction, model-id/dim schema rule (D-03, 7.3) |
| A13 | llama.cpp context-per-slot and memory not addressed; "parallel blocks" and worker autoscaling implied linear speedup | Slot math, token budget, capacity = slots x GPUs, priority lanes (7.2, 7.5, 15.3) |
| A14 | No global priority control across worker replicas | Gateway as single admission point (D-11) |
| A15 | Fine-tuning plan lacked pipeline specifics and pitfalls | QLoRA on HF base -> bf16 merge -> GGUF -> Q4_K_M; evaluate quantized artifact; split by course; teacher-license check; gates (7.10, D-14) |
| A16 | Llama license obligations unmentioned | Attribution/naming/AUP notes (7.1) |
| A17 | Confidence-aware evaluation relied on model self-confidence | Evidence-mass confidence; grader agreement + escalation; UNCERTAIN path (6.1, 6.6) |
| A18 | Prerequisite edges from an LLM treated as facts (cycles, wrong direction) | Edge status/confidence/source, DAG validation, hard-gate only on confirmed edges, seed templates (9) |
| A19 | Sync/async split unclear; async everywhere hurts responsiveness | Deterministic mastery/planner path runs synchronously in the answer transaction (3.2) |
| A20 | Golden set sizes (100 syllabi, 500 questions...) unrealistic; no offline test of the loop | MVP sizes + student simulator with baselines (16.2-16.3) |
| A21 | Success metrics had no numbers | Initial targets table (16.4) |
| A22 | Greenfield with no reuse guidance; risk of rewriting solved problems | Port audited v2 modules; MVP tiering P0/P1/P2 (D-01, 1) |
| A23 | Cloud fallback ignored data egress/consent | Opt-in flag, redaction, degrade path (D-13, 7.7) |
| A24 | No answer-quality controls for questions (duplicates, unanswerable items, guessable MCQs) | Answerability check, dedupe, distractor checks, guess-corrected weights (6.1, 6.6) |
| A25 | Cold-start diagnostic could be endless; self-reported knowledge unmodeled | Budgeted diagnostic, information-based selection, weak self-report prior, INFERRED evidence (6.3) |
| A26 | Self-evaluating lesson quality with the same 3B model | Non-LLM-first validators (citations, lexical/embedding support, sympy) (10) |
| A27 | WebSocket assumed | SSE (D-10) |
| A28 | Package boundaries stated but unenforced | import-linter contracts in `make check` (4) |
| A29 | Model-serving readiness/artifact handling for K8s unspecified | PVC + init container + sha256 verify, probes, replicas=GPUs, KEDA for workers (15.3) |
| A30 | Privacy: no export/delete, no PII redaction, no DPDP note | Export/delete endpoints, redaction, log policy (14) |
| A31 | Generic `-c 16384 -np 4` config does not fit a 4 GB GPU with fp16 KV | 4 GB profile: `-c 8192 -np 2`, q8_0 KV + flash-attn, OOM ladder (7.11) |
| A32 | Embedder would compete with the SLM for VRAM | Embeddings on CPU only (7.11) |
| A33 | Lane caps and parallel block generation assumed spare GPU capacity | 2-slot lane caps, prefetch over parallelism, single-user capacity stated (7.11) |
| A34 | 8B fallback option and local QLoRA/K8s-GPU plans infeasible on this laptop | Same-size challengers/cloud; train on Colab/Kaggle; K8s validated on `mock` only (7.9, 7.11, 15.3) |
| A35 | 4 s time-to-first-block target unrealistic on a 3050 | Separate <= 8 s dev-laptop target, re-baseline in Phase 4 (16.4) |
