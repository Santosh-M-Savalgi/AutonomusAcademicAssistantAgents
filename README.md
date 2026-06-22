# Autonomous Academic Agent (AAA)

A multi-agent AI tutoring system that turns any learning goal — a topic, a course outline, or a syllabus PDF — into a personalized, adaptive curriculum. AAA researches each topic, teaches it, quizzes the student, and reroutes the learning path in real time based on quiz performance: mastering a topic advances the student, struggling triggers a re-teach, and persistent failure triggers automatic insertion of a prerequisite topic.

Built with **LangGraph**, **FastAPI**, **Google Gemini**, **ChromaDB**, and **React**.

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
2. **Researches** the current topic via live web search, summarizing and embedding sources into a per-student vector store.
3. **Teaches** the topic as a structured lesson (concept → worked example → real-world analogy), grounded in the retrieved sources.
4. **Quizzes** the student with generated comprehension questions.
5. **Evaluates** answers for conceptual correctness (not exact wording) and routes the student:
   - **Score ≥ 70** → advance to the next topic.
   - **Score < 70** → re-teach the same topic.
   - **3 failed attempts with score < 50** → infer and insert a prerequisite topic before continuing.

This loop repeats until the curriculum is complete, with full progress persisted so a session can be resumed at any time.

## Architecture

AAA is a three-agent system orchestrated by a LangGraph state machine. Agents don't call each other directly — they read and write to a shared, typed state object (`AAAState`), and the graph decides what runs next.

```
                         ┌─────────────────────┐
                         │   Agent 1: Syllabus  │
   Student request  ───► │       Parser         │
   (text or PDF)         │  (Gemini structured  │
                         │      output)         │
                         └──────────┬───────────┘
                                    │ ordered topic queue
                                    ▼
                         ┌─────────────────────┐
                  ┌─────►│   Agent 2: Search    │
                  │      │   & Retrieval        │
                  │      │  (Tavily + Gemini    │
                  │      │  summarize + embed)  │
                  │      └──────────┬───────────┘
                  │                 │ context stored in ChromaDB
                  │                 ▼
                  │      ┌─────────────────────┐
                  │      │  Agent 3: Tutor/Quiz │
                  │      │  teach → quiz →      │
                  │      │  evaluate (Gemini)   │
                  │      └──────────┬───────────┘
                  │                 │ quiz score
                  │                 ▼
                  │        ┌─────────────────┐
                  │        │  Routing Node    │
                  │        │ (score-based)    │
                  │        └───┬─────┬────┬───┘
                  │   advance  │     │    │ insert prerequisite
                  └────────────┘  reteach └──────────────────────►(back to search)
                       (next topic)  │
                                     └──────────► (back to teach)
```

- **Agent 1 — Syllabus Parser** (`agents/syllabus_parser.py`): Converts a free-text goal or PDF into a prerequisite-ordered list of topics using Gemini's structured JSON output.
- **Agent 2 — Search & Retrieval** (`agents/search_agent.py`): Runs a Tavily web search per topic, summarizes each result with Gemini (grounded, no hallucinated claims), embeds the summaries, and upserts them into a student-scoped ChromaDB collection. Falls back to Gemini's own knowledge if the search provider is unavailable.
- **Agent 3 — Tutor & Quiz** (`agents/tutor_quiz_agent.py`): Retrieves the most relevant stored context above a cosine-similarity threshold, generates a structured lesson, produces comprehension questions, and scores student answers conceptually.
- **Orchestration** (`orchestration/`): A `StateGraph` (LangGraph) wires the agents into nodes with conditional edges. `state.py` defines the shared `AAAState`/`TopicState` contracts; `nodes.py` wraps each agent call as a graph node; `graph.py` defines the routing logic and compiles the graph.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) (`StateGraph`, conditional routing) |
| LLM | Google **Gemini** (`google-genai`) — structured JSON output via response schemas |
| Web search | [Tavily](https://tavily.com/) |
| Vector store | [ChromaDB](https://www.trychroma.com/) (persistent, per-student collections, cosine distance) |
| Relational persistence | SQLite (WAL mode, foreign keys, CHECK constraints) |
| Backend API | [FastAPI](https://fastapi.tiangolo.com/) |
| PDF parsing | [pypdf](https://pypdf.readthedocs.io/) |
| Frontend | React 19 + Vite |
| Icons | [lucide-react](https://lucide.dev/) |
| Testing | pytest, httpx |

## Project Structure

```
AutonomusAcademicAssistantAgents/
├── backend/
│   ├── agents/
│   │   ├── syllabus_parser.py     # Agent 1: text/PDF → ordered topic list
│   │   ├── search_agent.py        # Agent 2: search, summarize, embed, store
│   │   └── tutor_quiz_agent.py    # Agent 3: teach, quiz, evaluate
│   ├── orchestration/
│   │   ├── state.py               # AAAState / TopicState TypedDicts
│   │   ├── nodes.py                # Graph nodes wrapping each agent
│   │   └── graph.py                 # StateGraph wiring + routing functions
│   ├── persistence/
│   │   ├── db.py                  # SQLite schema + connection management
│   │   └── vector_store.py        # ChromaDB client + Gemini embeddings
│   ├── api/
│   │   ├── routes.py              # REST endpoints (/api/v1/...)
│   │   └── schemas.py             # Pydantic request/response models
│   ├── tests/                     # pytest suite (agents, graph, API)
│   ├── config.py                  # Environment-driven settings
│   ├── main.py                    # FastAPI app + exception handlers
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── Onboarding.jsx       # Text or PDF syllabus input
    │   │   ├── SyllabusOverview.jsx # Curriculum roadmap / topic timeline
    │   │   ├── LessonView.jsx       # Lesson content + cited sources
    │   │   ├── QuizView.jsx         # Quiz questions + answer submission
    │   │   ├── ProfileView.jsx      # Progress log / weak topics
    │   │   ├── CurriculumPath.jsx   # Visual topic path
    │   │   └── ProgressBar.jsx
    │   ├── api.js                  # Typed fetch client for the backend API
    │   └── App.jsx                  # Screen router + session state
    ├── package.json
    └── vite.config.js
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- A [Google Gemini API key](https://ai.google.dev/)
- A [Tavily API key](https://tavily.com/) (optional — the search agent falls back to Gemini's own knowledge if omitted, with reduced grounding)

### Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env and set GEMINI_API_KEY (and optionally TAVILY_API_KEY)

uvicorn main:app --reload --port 8000
```

The API will be available at `http://127.0.0.1:8000`, with interactive docs at `http://127.0.0.1:8000/docs`.

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173` by default and talks to the backend at `http://127.0.0.1:8000/api/v1` (override with a `VITE_API_BASE_URL` environment variable).

## API Reference

All endpoints are prefixed with `/api/v1`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/students` | Create a student from a free-text learning goal. Returns `student_id` and the generated syllabus. |
| `POST` | `/students/upload-syllabus` | Create a student from an uploaded PDF syllabus (`multipart/form-data`). |
| `GET` | `/students/{student_id}` | Fetch a student's profile. |
| `POST` | `/students/{student_id}/start` | Run the search → teach → quiz pipeline for the current topic. |
| `GET` | `/students/{student_id}/lesson` | Get the generated lesson content and source citations for the active topic. |
| `GET` | `/students/{student_id}/quiz` | Get the generated quiz questions for the active topic. |
| `POST` | `/students/{student_id}/answer` | Submit quiz answers; triggers evaluation and adaptive routing. |
| `GET` | `/students/{student_id}/profile` | Get a dashboard-style view: taught, pending, and weak topics. |
| `GET` | `/students/{student_id}/topics` | Get the full topic list with statuses, scores, and attempts. |
| `GET` | `/health` | Health check. |

Errors follow a consistent shape:

```json
{ "error": { "code": "student_not_found", "message": "Student not found" } }
```

## Adaptive Routing Logic

The core decision after every quiz lives in `orchestration/graph.py`:

```python
def route_after_evaluation(state):
    current = state["syllabus"][state["current_topic_index"]]
    if current["quiz_score"] >= 70:
        return "advance_topic"
    if current["attempts"] >= 3 and current["quiz_score"] < 50:
        return "infer_prerequisite"
    return "reteach_topic"
```

- **Mastery (≥ 70):** topic marked `taught`, student advances.
- **Struggling (< 70, < 3 attempts or score ≥ 50):** topic is re-taught with freshly generated content.
- **Stuck (≥ 3 attempts, score < 50):** the topic is marked `critical`, and a beginner-level prerequisite topic is synthesized and inserted directly before it in the syllabus — the student detours through the gap before retrying.

Each topic tracks its own `status`, `quiz_score`, `attempts`, and `inferred_gap`, so the full learning history per topic is auditable from the `topics` endpoint.

## Testing

```bash
cd backend
pytest
```

The suite covers each agent in isolation, the LangGraph routing/state contracts, and the API layer (`tests/test_agent1.py`, `test_agent2.py`, `test_agent3.py`, `test_graph_routing.py`, `test_api.py`).

## Configuration

All configuration is environment-driven via `backend/config.py` / `.env`:

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Used for syllabus parsing, summarization, teaching, quizzing, evaluation, and embeddings. |
| `TAVILY_API_KEY` | No | Used for live web search. Falls back to Gemini's internal knowledge if missing or if a search call fails. |
| `SQLITE_DB_PATH` | No | Path to the SQLite database file. Defaults to `./data/aaa.db`. |
| `CHROMA_DB_PATH` | No | Path to the persistent ChromaDB store. Defaults to `./chroma_store`. |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins. Defaults to `http://localhost:5173`. |

Model selection (also in `config.py`):

| Purpose | Model |
|---|---|
| Syllabus parsing | `gemini-2.5-flash-lite` |
| Search summarization | `gemini-2.5-flash-lite` |
| Teaching / quiz / evaluation | `gemini-2.5-flash` |
| Embeddings | `gemini-embedding-001` (768 dimensions) |

## Roadmap

- [ ] Multi-student authentication (currently identified by opaque `student_id`)
- [ ] Streaming lesson generation
- [ ] Spaced-repetition review scheduling for `weak`/`strong` topics
- [ ] Deployment guide (Docker / cloud)

## Contributors

- [Santosh M Savalgi](https://github.com/Santosh-M-Savalgi)
- S Dileep
- Sumant Rangappa Kovalli

---

*Have ideas or found a bug? Open an issue or submit a pull request.*
