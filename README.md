# Autonomous Academic Agent (AAA) v2

A multi-agent AI tutoring system that turns any learning goal — a topic, a course outline, or a syllabus PDF — into a personalized, adaptive curriculum. AAA researches each topic, teaches it, quizzes the student, and reroutes the learning path in real time based on quiz performance: mastering a topic advances the student, struggling triggers a re-teach, and persistent failure triggers automatic insertion of a prerequisite topic.

Built with **LangGraph**, **FastAPI**, **DeepSeek**, **ChromaDB**, **PostgreSQL**, **Redis**, and **React + TypeScript**.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Adaptive Routing Logic](#adaptive-routing-logic)
- [Testing](#testing)
- [Configuration](#configuration)
- [Roadmap](#roadmap)
- [Contributors](#contributors)

---

## How It Works

A student describes what they want to learn (free text or an uploaded syllabus PDF). AAA then:

1. **Decomposes** the request into an ordered list of topics, each tagged with difficulty and prerequisites.
2. **Researches** the current topic via live web search (Tavily), summarizing and embedding sources into a per-student vector store (ChromaDB).
3. **Teaches** the topic as a structured lesson (concept → worked example → real-world analogy), grounded in the retrieved sources.
4. **Quizzes** the student with generated comprehension questions.
5. **Evaluates** answers for conceptual correctness (not exact wording) and routes the student:
   - **Score ≥ 70** → advance to the next topic (`NEXT_TOPIC`).
   - **Score ≥ 50, < 70** → re-teach the same topic (`REVIEW_TOPIC`).
   - **Score < 50**, not stuck → repeat quiz (`REPEAT_TOPIC`).
   - **Stuck** (3+ failed attempts, score < 50) → infer and insert a prerequisite topic (`REVISIT_PREREQUISITE`).

This loop repeats until the curriculum is complete, with full progress persisted across PostgreSQL + Redis so a session can be resumed at any time.

## Architecture

AAA v2 is a multi-agent system orchestrated by a LangGraph state machine with durable checkpointing. Agents don't call each other directly — they read and write to a shared, typed state object (`AAAState`), and the graph decides what runs next.

```
                         ┌──────────────────────────┐
                         │  Node: parse_syllabus     │
   Student request  ───► │  (DeepSeek LLM via        │
   (text or PDF)         │   ProviderFactory)        │
                         └──────────┬───────────────┘
                                    │ ordered topic queue
                                    ▼
                         ┌──────────────────────────┐
                         │  Node: retrieve_context   │
                         │  (ChromaDB vector search) │
                         └──────────┬───────────────┘
                                    │
                                    ▼
                         ┌──────────────────────────┐
                         │  Node: retrieve_web       │
                         │  (Tavily search + embed)  │
                         └──────────┬───────────────┘
                                    │
                                    ▼
                         ┌──────────────────────────┐
                         │  Node: generate_lesson    │
                         │  (DeepSeek LLM, temp 0.3) │
                         └──────────┬───────────────┘
                                    │
                                    ▼
                         ┌──────────────────────────┐
                         │  Node: generate_quiz      │
                         │  (DeepSeek LLM, temp 0.4) │
                         └──────────┬───────────────┘
                                    │
                                    ▼
                         ┌──────────────────────────┐
                         │  Node: evaluate_quiz      │
                         │  (DeepSeek LLM, temp 0.3) │
                         └──────────┬───────────────┘
                                    │ routing decision
                                    ▼
                          ┌──────────────────────┐
                          │    Routing Node       │
                          │ NEXT_TOPIC  ──────────► END (advance)
                          │ REVIEW_TOPIC ────────► back to teach
                          │ REPEAT_TOPIC ────────► back to quiz
                          │ REVISIT_PREREQUISITE ► back to teach
                          └──────────────────────┘
```

- **Syllabus Parser** (`app/agents/syllabus_parser.py`): Converts a free-text goal into a prerequisite-ordered list of topics using the LLM via `ProviderFactory` (supports DeepSeek, Gemini, or mock providers).
- **Retrieval** (`app/graph/nodes/retrieve.py`, `retrieve_web.py`): Hybrid retrieval — local ChromaDB vector search + Tavily web search with domain filtering. Falls back gracefully if Tavily is unavailable.
- **Tutor Service** (`app/llm/tutor_service.py`): Generates structured lessons grounded in retrieved context.
- **Quiz Service** (`app/llm/quiz_service.py`): Generates comprehension questions with distractor analysis.
- **Evaluation Service** (`app/llm/evaluation_service.py`): Scores answers conceptually and provides detailed feedback.
- **Orchestration** (`app/graph/`): LangGraph `StateGraph` with 7 nodes, conditional routing, and durable checkpointing (Redis hot storage + PostgreSQL durable storage). `state.py` defines the shared `AAAState` contract; `graph_builder.py` wires nodes and compiles the graph; `checkpointer.py` implements `AAACheckpointSaver`.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`, conditional routing, durable checkpoints) |
| LLM (primary) | **DeepSeek** (`deepseek-v4-flash`) via `ProviderFactory` — also supports Gemini and mock |
| LLM SDK | `httpx` (no OpenAI client dependency) |
| Web search | [Tavily](https://tavily.com/) with domain filtering (25 edu/docs domains, 9 social-media exclusions) |
| Vector store | [ChromaDB](https://www.trychroma.com/) (persistent, per-student collections, cosine distance) |
| Relational DB | **PostgreSQL** via SQLAlchemy 2.0 + asyncpg (schema managed by Alembic) |
| Cache / sessions | **Redis** (session hot storage, rate limiting, checkpoint cache) |
| Object storage | MinIO / S3-compatible (document uploads, PDF storage) |
| Backend API | [FastAPI](https://fastapi.tiangolo.com/) |
| Auth | JWT (access + refresh tokens), bcrypt password hashing |
| PDF parsing | [pypdf](https://pypdf.readthedocs.io/) |
| Observability | Prometheus metrics, OpenTelemetry tracing, structlog JSON logging |
| Resilience | tenacity (LLM retries with exponential backoff) |
| Frontend | React 19 + TypeScript + Vite |
| Icons | [lucide-react](https://lucide.dev/) |
| Testing | pytest, pytest-asyncio |
| Linting | ruff |

## Project Structure

```
AAA-v2/
├── backend/
│   ├── app/
│   │   ├── agents/              # Syllabus parser agent (ProviderFactory-based)
│   │   ├── adaptive/            # Adaptive routing engine, diagnostics, planner, recommendations
│   │   ├── analytics/           # Learning analytics, mastery calculations, dashboard data
│   │   ├── api/                 # FastAPI health endpoint + v2 router
│   │   │   └── v2/              # REST API v2 (learning, quiz, lessons, analytics, auth, etc.)
│   │   ├── auth/                # JWT handler, password hashing, auth dependencies, service
│   │   ├── core/                # Settings (Pydantic), exceptions, logging, rate limiting, security
│   │   ├── db/                  # PostgreSQL (SQLAlchemy), ChromaDB client, Redis, object storage
│   │   │   ├── models/          # SQLAlchemy ORM models (session, quiz, learning, user)
│   │   │   └── migrations/      # Alembic migration scripts
│   │   ├── graph/               # LangGraph orchestration
│   │   │   ├── nodes/           # Graph nodes (parse, retrieve, retrieve_web, teach, quiz, evaluate)
│   │   │   ├── state.py         # AAAState TypedDict
│   │   │   ├── graph_builder.py # StateGraph wiring + routing
│   │   │   └── checkpointer.py  # AAACheckpointSaver (Redis + Postgres)
│   │   ├── ingestion/           # Document processing, chunking, embedding, vector store
│   │   ├── jobs/                # Background job queue, scheduler, worker, task definitions
│   │   ├── llm/                 # LLM provider abstraction
│   │   │   ├── providers/       # DeepSeekProvider, GeminiProvider, MockProvider
│   │   │   ├── provider_router.py    # ProviderFactory + registry
│   │   │   ├── tutor_service.py      # Lesson generation
│   │   │   ├── quiz_service.py       # Quiz generation
│   │   │   └── evaluation_service.py # Answer evaluation
│   │   ├── middleware/           # Rate limiting, request context, security headers
│   │   ├── monitoring/           # Prometheus metrics, OpenTelemetry tracing
│   │   ├── services/             # Adaptive routing, context building, knowledge graph, mastery
│   │   ├── session/              # Session management (Redis + Postgres)
│   │   ├── workers/              # Background worker processes
│   │   └── main.py               # FastAPI app factory
│   ├── tests/                    # pytest suite
│   │   ├── unit/                 # Unit tests (adaptive_routing, checkpointer, chunking, etc.)
│   │   ├── integration/          # Integration tests (quiz scoring, etc.)
│   │   ├── adaptive/             # Adaptive engine tests
│   │   ├── analytics/            # Analytics tests
│   │   ├── auth/                 # Auth tests (API, JWT, password, service)
│   │   ├── e2e/                  # End-to-end tests
│   │   ├── jobs/                 # Job queue tests
│   │   └── session/              # Session management tests
│   ├── pyproject.toml            # Project metadata + build config
│   ├── requirements.txt          # pip-compatible dependency list
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   ├── alembic.ini
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── api/                  # Typed fetch clients for backend
│   │   ├── components/           # Reusable UI components
│   │   ├── pages/                # Route-level pages (learning, auth, dashboard)
│   │   ├── services/             # Business logic services (learning API, etc.)
│   │   ├── hooks/                # Custom React hooks
│   │   ├── contexts/             # React context providers
│   │   ├── types/                # TypeScript type definitions
│   │   ├── utils/                # Utility functions
│   │   ├── constants/            # App constants
│   │   ├── routes/               # Route configuration
│   │   ├── layouts/              # Page layouts
│   │   ├── theme/                # MUI / custom theme
│   │   └── main.tsx              # React entry point
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── architecture/                 # Architecture docs, roadmap, decisions, progress
├── docker/                       # Docker config directory
├── infra/                        # CI + Kubernetes configs
├── docker-compose.yml            # Full stack orchestration
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16+
- Redis 7+
- A [DeepSeek API key](https://platform.deepseek.com/) (primary LLM)
- A [Tavily API key](https://tavily.com/) (optional — web search falls back gracefully if omitted)
- (Optional) A [Google Gemini API key](https://ai.google.dev/) for Gemini provider support

### Quick start with Docker

```bash
# Start all services (PostgreSQL, Redis, ChromaDB, MinIO, backend, frontend)
docker compose up -d
```

The API will be available at `http://127.0.0.1:8000`, with interactive docs at `http://127.0.0.1:8000/docs`. The frontend runs at `http://localhost:5173`.

### Backend setup (manual)

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env — set at minimum:
#   DEEPSEEK_API_KEY=sk-...
#   LLM_PROVIDER=deepseek
#   (Optionally: TAVILY_API_KEY=tvly-...)

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload --port 8000
```

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173` by default and talks to the backend at `http://127.0.0.1:8000/api/v2` (override with `VITE_API_BASE_URL`).

## API Reference

All v2 endpoints are prefixed with `/api/v2`. Authentication uses JWT Bearer tokens.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v2/auth/register` | Register a new user account. |
| `POST` | `/api/v2/auth/login` | Login and receive access + refresh tokens. |
| `POST` | `/api/v2/auth/refresh` | Refresh an expired access token. |
| `POST` | `/api/v2/learning/goal` | Create a learning goal → returns syllabus + session + roadmap. |
| `GET` | `/api/v2/learning/sessions` | List all learning sessions for the authenticated user. |
| `GET` | `/api/v2/learning/sessions/{id}` | Get session status and progress. |
| `GET` | `/api/v2/lessons/{session_id}` | Get the current lesson for a session. |
| `GET` | `/api/v2/quiz/{session_id}` | Get the current quiz questions. |
| `POST` | `/api/v2/quiz/{session_id}/submit` | Submit quiz answers → triggers evaluation and adaptive routing. |
| `GET` | `/api/v2/analytics/dashboard` | Dashboard with learning stats and mastery overview. |
| `GET` | `/api/v2/analytics/topics/{session_id}` | Topic-level progress with scores and attempts. |
| `GET` | `/api/v2/jobs/{job_id}` | Check status of a background job. |
| `GET` | `/health` | Health check (includes DB, Redis, ChromaDB dependency checks). |
| `GET` | `/metrics` | Prometheus metrics endpoint. |

Errors follow a consistent shape:

```json
{
  "error": {
    "code": "session_not_found",
    "message": "No session found with the given ID",
    "details": {}
  }
}
```

## Adaptive Routing Logic

The routing decision in `app/graph/graph_builder.py` after quiz evaluation:

```python
def _route_after_evaluate(state: AAAState) -> str:
    score = state.get("quiz_score", 0)
    attempts = state.get("quiz_attempts", 0)

    if score >= 70:
        return "NEXT_TOPIC"          # Mastered → advance
    if score >= 50:
        return "REVIEW_TOPIC"        # Close → re-teach with better content
    if attempts >= 3:
        return "REVISIT_PREREQUISITE" # Stuck → insert prerequisite
    return "REPEAT_TOPIC"            # Try again → new quiz on same topic
```

- **Mastery (≥ 70):** topic marked complete, student advances to next topic.
- **Close (50–69):** topic re-taught with refreshed content and different examples.
- **Needs practice (< 50, < 3 attempts):** new quiz generated on same topic.
- **Stuck (≥ 3 attempts, score < 50):** a prerequisite topic is synthesized and inserted — student backfills the gap before retrying.

## Testing

```bash
cd backend

# Run all tests
pytest

# Run specific suites
pytest tests/unit/
pytest tests/integration/
pytest tests/auth/
pytest tests/adaptive/

# With coverage
pytest --cov=app --cov-report=term-missing
```

The suite covers: unit tests (adaptive routing, checkpointer, chunking, embedding abstraction, evaluation), integration tests (quiz scoring), auth tests (JWT, password, API), session tests, job queue tests, adaptive engine tests, and e2e tests.

## Configuration

All configuration is environment-driven via `backend/app/core/config.py` / `.env`:

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Yes | LLM provider: `deepseek`, `gemini`, or `mock`. Defaults to `mock` for dev safety. |
| `DEEPSEEK_API_KEY` | If `LLM_PROVIDER=deepseek` | DeepSeek API key. App refuses to start if missing. |
| `GEMINI_API_KEY` | If `LLM_PROVIDER=gemini` | Google Gemini API key. |
| `TAVILY_API_KEY` | No | Web search API key. Falls back gracefully if omitted. |
| `POSTGRES_DSN` | Yes | PostgreSQL connection string (asyncpg). Default: `postgresql+asyncpg://aaa:aaa_password@postgres:5432/aaa` |
| `REDIS_URL` | Yes | Redis connection URL. Default: `redis://redis:6379/0` |
| `CHROMA_HOST` | No | ChromaDB host. Default: `chroma` |
| `CHROMA_PORT` | No | ChromaDB port. Default: `8000` |
| `CORS_ORIGINS` | No | Comma-separated CORS origins. Default: `http://localhost:5173` |
| `ENABLE_RATE_LIMIT` | No | Enable rate limiting middleware. Default: `true` |
| `LOG_LEVEL` | No | Logging level. Default: `INFO` |

LLM model configuration:

| Purpose | Model | Temperature |
|---|---|---|
| Syllabus parsing | `deepseek-v4-flash` | default (0.7) |
| Lesson generation | `deepseek-v4-flash` | 0.3 |
| Quiz generation | `deepseek-v4-flash` | 0.4 |
| Evaluation feedback | `deepseek-v4-flash` | 0.3 |

## Roadmap

- [x] Multi-provider LLM abstraction (DeepSeek, Gemini, mock)
- [x] JWT authentication with refresh tokens
- [x] PostgreSQL + Redis persistence
- [x] Durable LangGraph checkpointing (Redis hot + Postgres durable)
- [x] Background job queue with worker pool
- [x] Prometheus metrics + OpenTelemetry tracing
- [x] Structured JSON logging (structlog)
- [x] Rate limiting middleware
- [x] Docker Compose full-stack deployment
- [ ] Streaming lesson generation (SSE)
- [ ] Spaced-repetition review scheduling
- [ ] Multi-tenant / organization support
- [ ] Admin dashboard with usage analytics
- [ ] Kubernetes Helm chart for production deployment

## Contributors

- [Santosh M Savalgi](https://github.com/Santosh-M-Savalgi)
- S Dileep
- Sumant Rangappa Kovalli

---

*Have ideas or found a bug? Open an issue or submit a pull request.*
