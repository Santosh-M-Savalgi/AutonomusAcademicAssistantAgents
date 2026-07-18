# AAA v2 — Agent Architecture & Data Flow

Generated 2026-07-18 from live code inspection. Every file path and line number is verified against the current working tree.

---

## 1. Full Data Flow: `POST /api/v2/learning/goal`

### 1.1 Entry Point

**File:** `backend/app/api/v2/learning.py:130`

```python
@router.post("/goal", response_model=LearningGoalResponse, status_code=201)
async def create_learning_goal(request: LearningGoalRequest, ...)
```

**Request body:**
```json
{ "goal": "I want to learn linear regression" }
```

### 1.2 Step 1 — Syllabus Parsing (via DeepSeek LLM)

**File:** `backend/app/api/v2/learning.py:148-151`

```python
parser = SyllabusParser()
parsed = await parser.parse(request.goal)
```

**`SyllabusParser` implementation:** `backend/app/agents/syllabus_parser.py:78-127`

- Instantiates provider via `ProviderFactory.from_settings().get_provider()` (line 86)
- Reads `LLM_PROVIDER` env var — defaults to `"mock"`, production uses `"deepseek"`
- Sends a system prompt + user goal to the LLM (lines 101-107)
- System prompt directs the LLM to output JSON: `{ "title": "...", "topics": [{ "name": "...", "slug": "...", "description": "...", "difficulty": "...", "prerequisites": [...] }] }`
- On `ProviderError`: re-raises (no silent fallback — line 111)
- On malformed JSON: falls back to `_mock_syllabus()` (line 126-127) which has hardcoded topics for common keywords (python, java, react, ml, sql, system design) and a generic 4-topic fallback

### 1.3 Step 2 — Persist to Database

**File:** `backend/app/api/v2/learning.py:162-293`

- Creates a `Syllabus` row (line 162-168)
- Batch-looks up existing `Topic` rows by slug to avoid duplicates (lines 170-186)
- Creates missing `Topic` rows (lines 192-215)
- Creates `TopicEdge` rows for prerequisite relationships (lines 219-293)
- Uses `db.flush()` to get IDs without committing; `db.commit()` at line 313

### 1.4 Step 3 — Create Session

**File:** `backend/app/api/v2/learning.py:295-310`

```python
manager = SessionManager()
session: SessionData = await manager.create_session(
    student_id=str(current_user.id),
    syllabus_id=str(syllabus.id),
)
```

**`SessionManager`:** `backend/app/session/session_manager.py:62` — manages Redis hot storage + Postgres durable storage for session state.

### 1.5 Step 4 — Build KnowledgeGraph & Roadmap

**File:** `backend/app/api/v2/learning.py:320-339`

- Loads `Topic` + `TopicEdge` rows from the DB
- Calls `build_graph_from_models()` to create an in-memory `KnowledgeGraph`
- Calls `LearningPathService().generate()` with `mode=STANDARD` and empty mastery scores (all 0.0)
- Returns a `LearningPath` with ordered steps, blocked/unblocked flags

### 1.6 Step 5 — Seed Checkpoint & Return

**File:** `backend/app/api/v2/learning.py:342-383`

- Stores roadmap via `CheckpointStore.save_checkpoint()`
- Returns `LearningGoalResponse` with `syllabus_id`, `session_id`, `topics[]`, `roadmap[]`, `roadmap_mode`

---

## 2. DeepSeek Provider Implementation

### 2.1 Provider Registration

**File:** `backend/app/llm/provider_router.py:26-30`

```python
PROVIDER_REGISTRY = {
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
    "mock": MockProvider,
}
```

Selection: `ProviderFactory.from_settings()` reads `LLM_PROVIDER` env var (default `"mock"`). Production `.env` sets `LLM_PROVIDER=deepseek`.

### 2.2 Hard Block at Startup

**File:** `backend/app/llm/provider_router.py:50-58`

If `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY` is empty, `get_provider()` raises `ProviderError` immediately — refuses to instantiate.

**File:** `backend/app/llm/provider_router.py:105-134` (`validate_provider_startup()`)

Called from `backend/app/core/config.py:170` during `validate_configuration()` at app startup. Returns error messages if key is missing or too short.

### 2.3 DeepSeekProvider Class

**File:** `backend/app/llm/providers/deepseek.py:40-203`

**Transport:** `httpx.AsyncClient` (already a project dependency — no `openai` package needed).

**Endpoint:** `POST https://api.deepseek.com/v1/chat/completions`

**Auth:** `Authorization: Bearer {DEEPSEEK_API_KEY}` (line 96)

**Model:** `deepseek-v4-flash` (line 37). Legacy names `deepseek-chat` and `deepseek-reasoner` are silently upgraded to `deepseek-v4-flash` (lines 50-55).

**Request shape** (lines 118-123):
```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.3,
  "max_tokens": 2048
}
```

**Error handling** (lines 133-170):
- HTTP 401 → `ProviderError("DeepSeek authentication failed")`
- HTTP 429 → `ProviderRateLimitError`
- HTTP 5xx → `ProviderError`
- `httpx.TimeoutException` → `ProviderTimeoutError`
- Retry with exponential backoff: 2s, 4s, 8s (up to `config.retry_count=2` retries = 3 total attempts)

**Response** (lines 150-161):
```python
ProviderResponse(
    content=choice["message"]["content"],
    model_used=data["model"],
    finish_reason=choice["finish_reason"],
    usage=data["usage"],
    raw=data,
)
```

### 2.4 All 4 LLM Call Sites Use the Same Provider

| Call site | File | Line | Service | Temperature |
|---|---|---|---|---|
| Syllabus parsing | `app/agents/syllabus_parser.py` | 104 | `SyllabusParser.parse()` | default (0.7) |
| Lesson generation | `app/llm/tutor_service.py` | 177 | `TutorService.generate_lesson()` | 0.3 |
| Quiz generation | `app/llm/quiz_service.py` | 181 | `QuizService.generate_quiz()` | 0.4 |
| Evaluation feedback | `app/llm/evaluation_service.py` | 186 | `EvaluationService.evaluate()` | 0.3 |

All call `ProviderFactory.from_settings().get_provider()` which returns the same `DeepSeekProvider` instance.

---

## 3. Tavily Web Retrieval Implementation

### 3.1 Graph Node: `retrieve_web`

**File:** `backend/app/graph/nodes/retrieve_web.py`

**Position in graph:** `parse → retrieve → retrieve_web → tutor` (`graph_builder.py:99-101`)

### 3.2 Client Initialization

**File:** `retrieve_web.py:29-47`

```python
def _get_tavily():
    from tavily import TavilyClient
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        logger.warning("TAVILY_API_KEY not set — web retrieval disabled")
        return None
    return TavilyClient(api_key=key)
```

Lazy import — `tavily-python` is only imported when the node runs, not at module load time. If `TAVILY_API_KEY` is missing, returns `None` and the node silently passes through.

### 3.3 Domain Filtering

**File:** `retrieve_web.py:55-98`

**Include domains** (25 educational/docs sites): `wikipedia.org`, `docs.python.org`, `developer.mozilla.org`, `realpython.com`, `geeksforgeeks.org`, `w3schools.com`, `tutorialspoint.com`, `freecodecamp.org`, `kaggle.com`, `towardsdatascience.com`, `medium.com`, `stackoverflow.com`, `github.com`, `pytorch.org`, `tensorflow.org`, `numpy.org`, `pandas.pydata.org`, `scikit-learn.org`, `learn.microsoft.com`, `docs.oracle.com`, `cpython.org`, `python.org`, `java.com`, `oracle.com`

**Exclude domains** (forums/UGC): `reddit.com`, `quora.com`, `twitter.com`, `x.com`, `facebook.com`, `instagram.com`, `tiktok.com`, `pinterest.com`, `youtube.com`

YouTube is excluded from general web search and queried separately (below).

### 3.4 Web Search Query

**File:** `retrieve_web.py:125-146`

```python
response = tavily.search(
    query=f"{topic_name} {topic_description}",
    search_depth="basic",
    max_results=5,
    include_domains=_INCLUDE_DOMAINS,
    exclude_domains=_EXCLUDE_DOMAINS,
)
```

Returns up to 5 results, each with `{title, url, content}`. Stored in `state["retrieval_web"]["web_results"]`.

### 3.5 YouTube Search Query

**File:** `retrieve_web.py:148-177`

```python
yt_response = tavily.search(
    query=f"site:youtube.com {topic_name} tutorial",
    search_depth="basic",
    max_results=2,
    include_domains=["youtube.com"],
)
```

Returns up to 2 results. Video IDs extracted from URL (`watch?v=` or `youtu.be/`). Stored in `state["retrieval_web"]["youtube_results"]` as `{title, url, video_id}`.

Titles and URLs come directly from Tavily — no LLM paraphrasing, no fabricated links.

### 3.6 Failure Isolation

**File:** `retrieve_web.py:117-119, 145-146, 173-174`

All Tavily calls are wrapped in `try/except`. On any failure (timeout, error, empty results, missing API key):
- `state["retrieval_web"] = None`
- Node returns unchanged
- Graph proceeds to `tutor` node regardless

The tutor node (`teach.py:40-58`) reads both `state["retrieval_context"]` (ChromaDB local) and `state["retrieval_web"]` (Tavily web), merging them into a single prerequisite context string. If either is `None`, only the available sources are used.

### 3.7 API Exposure

YouTube suggestions are exposed in two endpoints:

- **`POST /api/v2/lessons/lesson`** — field `youtube_suggestions: [{title, url, video_id}]` (file: `lessons.py:112-122`)
- **`POST /api/v2/learning/study`** — field `youtube_suggestions: [{title, url, video_id}]` (file: `learning.py:507-512`)

Web search results (`state["retrieval_web"]["web_results"]`) are consumed by the tutor node to build better prompts but are not directly exposed to the frontend.

---

## 4. LangGraph Runtime

### 4.1 Graph Structure

**File:** `backend/app/graph/graph_builder.py:82-122`

```
parse → retrieve → retrieve_web → tutor → quiz → evaluate
                                          ↑___________|
                                    (conditional edge)
```

**Nodes (6):**

| Node | File | Wraps |
|---|---|---|
| `parse` | `nodes/parse.py` | `SyllabusParser` |
| `retrieve` | `nodes/retrieve.py` | `RetrievalService` + `ContextBuilder` (ChromaDB) |
| `retrieve_web` | `nodes/retrieve_web.py` | Tavily API |
| `tutor` | `nodes/teach.py` | `TutorService` (DeepSeek) |
| `quiz` | `nodes/quiz.py` | `QuizService` (DeepSeek) |
| `evaluate` | `nodes/evaluate.py` | `EvaluationService` + `AdaptiveRouter` |

**Conditional routing** (`graph_builder.py:42-77`):

| Decision | Next node |
|---|---|
| `NEXT_TOPIC` | END |
| `REVIEW_TOPIC`, `REVISIT_PREREQUISITE` | tutor (loop back) |
| `REPEAT_TOPIC`, `READY_FOR_QUIZ` | quiz (loop back) |

### 4.2 Checkpointer

**File:** `backend/app/graph/checkpointer.py:33` — `AAACheckpointSaver`

Two-tier: Redis (hot, sub-millisecond reads) + Postgres (durable). Every `graph.ainvoke()` call checkpoints state at each node boundary.

### 4.3 State Schema

**File:** `backend/app/graph/state.py`

Dict-based `AAAState` with keys: `messages`, `session_id`, `syllabus_id`, `learning_goal`, `topics[]`, `current_topic_id`, `current_topic_name`, `current_topic_description`, `current_topic_difficulty`, `mastery_scores`, `retrieval_context`, `retrieval_web`, `lesson`, `quiz`, `evaluation`, `routing_decision`, `routing_reason`, `next_topic_id`, `phase`, `phase_completed`, `error`, `attempts_on_current`, `learning_mode`.

---

## 5. API Endpoints That Invoke the Graph

| Endpoint | File | Line | Graph entry phase |
|---|---|---|---|
| `POST /api/v2/lessons/lesson` | `lessons.py:97` | starts at `"retrieve"` | runs retrieve→retrieve_web→tutor→quiz→evaluate(passthrough) |
| `POST /api/v2/quiz/evaluate` | `quiz.py:151` | starts at `"evaluate"` | runs evaluate→route |
| `POST /api/v2/learning/study` | `learning.py:476` | caller-specified | runs from given phase through to route |

---

## 6. Environment Configuration

**File:** `docker-compose.yml:8-9` — `env_file: ./backend/.env` loads all variables into the container.

**File:** `backend/.env` — required variables:

| Variable | Purpose | Example |
|---|---|---|
| `LLM_PROVIDER` | Selects provider (deepseek/gemini/mock) | `deepseek` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | `sk-...` |
| `TAVILY_API_KEY` | Tavily search API key | `tvly-...` |
| `GEMINI_API_KEY` | Gemini API key (fallback) | `AIza...` |

**Startup validation:** `backend/app/llm/provider_router.py:105-134` — if `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY` is empty, app logs an error at startup. `validate_provider_startup()` is called from `config.py:170`.
