# Autonomous Academic Agent (AAA) — System Design v2.0
**Gemini API Migration | Build-Ready Specification**

---

## 0. What Changed From v1.0

| Area | v1.0 (Claude) | v2.0 (Gemini) |
|---|---|---|
| LLM provider | Anthropic Claude API | Google Gemini API (`google-genai` SDK) |
| Agent 1 (Parser) model | Haiku 4.5 | `gemini-2.5-flash-lite` |
| Agent 2 (Search) model | Haiku 4.5 | `gemini-2.5-flash-lite` |
| Agent 3 (Tutor/Quiz) model | Sonnet 4.6 | `gemini-2.5-flash` |
| Embeddings | (unspecified) | `gemini-embedding-001` (3072-dim, truncatable) |
| Structured output | Prompted JSON | Native `response_schema` (Gemini JSON mode) |
| SDK | `anthropic` | `google-genai` |
| Env vars | `ANTHROPIC_API_KEY` | `GEMINI_API_KEY` |

**Why this matters technically, not just cosmetically:**
- Gemini's `response_schema` config gives you *guaranteed* schema-conformant JSON — no more regex-parsing LLM output or retry-on-malformed-JSON logic. This removes an entire class of bugs from Agent 1 and Agent 3's quiz generation.
- `gemini-embedding-001` replaces the now-retired `text-embedding-004`. It supports configurable output dimensionality (we use 768 to keep ChromaDB lean and fast) via the `output_dimensionality` config param.
- Flash-Lite is roughly 3-4x cheaper than Flash for the same token volume — correct for high-frequency, low-reasoning calls (parsing, search-summarization) vs. the teaching/evaluation calls that actually need reasoning depth.

---

## 1. Architecture Overview

```
                         ┌─────────────────────────────────────────┐
                         │              FRONTEND (SPA)              │
                         │     React/Vite — talks only to REST      │
                         └───────────────────┬───────────────────────┘
                                              │ HTTPS / JSON
                         ┌───────────────────▼───────────────────────┐
                         │           FastAPI Application Layer        │
                         │  /api/v1/* endpoints (see Section 4)       │
                         └───────────────────┬───────────────────────┘
                                              │
                         ┌───────────────────▼───────────────────────┐
                         │         LangGraph Orchestrator             │
                         │   StateGraph: parse → search → teach →     │
                         │   quiz → evaluate → route(advance|reteach  │
                         │   |insert_prerequisite)                    │
                         └──────┬──────────┬──────────┬───────────────┘
                                │          │          │
                    ┌───────────▼──┐ ┌─────▼──────┐ ┌─▼────────────────┐
                    │   AGENT 1     │ │  AGENT 2   │ │     AGENT 3       │
                    │ Syllabus      │ │  Search    │ │  Tutor + Quiz     │
                    │ Parser        │ │  Agent     │ │  Agent            │
                    │ gemini-2.5-   │ │ gemini-2.5-│ │  gemini-2.5-flash │
                    │ flash-lite    │ │ flash-lite │ │                   │
                    └───────┬───────┘ └─────┬──────┘ └─────────┬─────────┘
                            │               │                   │
                            │         ┌─────▼──────┐             │
                            │         │  Tavily    │             │
                            │         │  Web Search│             │
                            │         └─────┬──────┘             │
                            │               │                   │
                    ┌───────▼───────────────▼───────────────────▼─────┐
                    │              PERSISTENCE LAYER                   │
                    │  ┌────────────────────┐  ┌─────────────────────┐ │
                    │  │  SQLite             │  │  ChromaDB           │ │
                    │  │  student_profile     │  │  per-student        │ │
                    │  │  topic_record        │  │  collection,         │ │
                    │  │  session_history      │  │  gemini-embedding-   │ │
                    │  │                       │  │  001 vectors         │ │
                    │  └────────────────────┘  └─────────────────────┘ │
                    └───────────────────────────────────────────────────┘
```

**Design principle applied:** each agent is a *pure function over state* — given the same `AAAState` input, it returns deterministic-shape output. This is what makes LangGraph's conditional routing reliable and what makes the system testable agent-by-agent before wiring the graph.

---

## 2. LangGraph State Schema

This is the single most important artifact in the system — every node reads from and writes to this shape. Get this right first; everything else follows from it.

```python
from typing import TypedDict, Literal, Optional
from langgraph.graph import StateGraph

class TopicState(TypedDict):
    topic_id: str
    topic_name: str
    subtopics: list[str]
    difficulty: Literal["beginner", "intermediate", "advanced"]
    prerequisite: Optional[str]
    status: Literal["pending", "in_progress", "taught", "weak", "strong", "critical"]
    quiz_score: float
    attempts: int
    inferred_gap: Optional[str]

class AAAState(TypedDict):
    student_id: str
    raw_input: str                      # original student request
    syllabus: list[TopicState]          # ordered topic queue (Agent 1 output)
    current_topic_index: int
    retrieved_context: list[dict]       # Agent 2 output: [{source_url, summary, score}]
    lesson_content: Optional[str]       # Agent 3 (tutor phase) output
    quiz_questions: list[dict]          # [{question, expected_concept}]
    quiz_answers: list[str]             # student responses, appended per question
    evaluation_result: Optional[dict]   # {score, per_question_feedback, verdict}
    next_action: Literal["advance", "reteach", "insert_prerequisite", "complete"]
    error_log: list[str]                # accumulated non-fatal errors for NFR-06 fallback tracking
```

**Routing logic (the conditional edges that make this "smart" rather than linear):**

```python
def route_after_evaluation(state: AAAState) -> str:
    current = state["syllabus"][state["current_topic_index"]]
    if current["quiz_score"] >= 70:
        return "advance_topic"
    if current["attempts"] >= 3 and current["quiz_score"] < 50:
        return "infer_prerequisite"   # FR-08: weak cluster / gap detection
    return "reteach_topic"            # FR-07: different analogy, same topic
```

This single function implements FR-07 and FR-08 together — the mastery threshold and the prerequisite-inference trigger share one decision point, which is the correct place for it since both depend on the same `quiz_score` + `attempts` pair.

---

## 3. Agent Specifications

### Agent 1 — Syllabus Parser (`gemini-2.5-flash-lite`)

**Input:** raw student string (e.g. "I want to learn machine learning")
**Output:** ordered `list[TopicState]`, JSON-schema-enforced

```python
from google import genai
from google.genai import types

client = genai.Client()  # reads GEMINI_API_KEY from env

SYLLABUS_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_name": {"type": "string"},
                    "subtopics": {"type": "array", "items": {"type": "string"}},
                    "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                    "prerequisite": {"type": ["string", "null"]},
                },
                "required": ["topic_name", "subtopics", "difficulty", "prerequisite"]
            }
        }
    },
    "required": ["topics"]
}
from pypdf import PdfReader

def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def parse_syllabus(raw_input: str = "", pdf_path: str | None = None) -> list[dict]:
    if pdf_path:
        pdf_text = extract_text_from_pdf(pdf_path)
        raw_input = f"{raw_input}\n\nSyllabus document content:\n{pdf_text}".strip()
    
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=f"""Decompose this learning request into an ordered curriculum.
Order topics so every prerequisite appears before what depends on it.
Student request: "{raw_input}\"""",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SYLLABUS_SCHEMA,
            temperature=0.3,
        ),
    )
    import json
    return json.loads(response.text)["topics"]
```

Implements FR-01 and FR-02. Native schema enforcement means you never need a JSON-repair fallback here.

### Agent 2 — Search Agent (`gemini-2.5-flash-lite` + Tavily + ChromaDB)

**Input:** `topic_name`
**Output:** stored ChromaDB entries + summary list for Agent 3

```python
import chromadb
from tavily import TavilyClient

_chroma_client = chromadb.PersistentClient(path="./chroma_store")  # singleton per process
tavily_client = TavilyClient()  # reads TAVILY_API_KEY from env

def get_student_collection(student_id: str):
    return _chroma_client.get_or_create_collection(name=f"student_{student_id}")

def embed_text(text: str) -> list[float]:
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768),
    )
    return result.embeddings[0].values

def search_and_store_topic(student_id: str, topic_name: str) -> list[dict]:
    try:
        results = tavily_client.search(query=f"{topic_name} tutorial explanation", max_results=5)
    except Exception as e:
        # NFR-06: graceful fallback to Gemini's internal knowledge
        return fallback_to_model_knowledge(topic_name, error=str(e))

    collection = get_student_collection(student_id)
    stored = []
    for r in results.get("results", []):
        summary = summarize_with_gemini(r["content"], topic_name)  # flash-lite call
        vector = embed_text(summary)
        entry_id = f"{topic_name}_{r['url']}"
        collection.add(
            ids=[entry_id],
            embeddings=[vector],
            metadatas=[{"topic_name": topic_name, "source_url": r["url"]}],
            documents=[summary],
        )
        stored.append({"source_url": r["url"], "summary": summary})
    return stored

def fallback_to_model_knowledge(topic_name: str, error: str) -> list[dict]:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=f"Summarize key concepts for teaching '{topic_name}' to a student, as if briefing a tutor.",
    )
    return [{"source_url": "model_internal_knowledge", "summary": response.text}]
```

Implements FR-03, FR-04, NFR-06. **Critical fix carried over from your earlier production-readiness work on this exact agent:** `_chroma_client` is instantiated once at module scope, not per-call — this was one of the bugs already fixed in your prior session and must not regress here.

### Agent 3 — Tutor + Quiz Agent (`gemini-2.5-flash`)

**Tutor phase** implements FR-05 (RAG retrieval → concept/example/analogy lesson):

```python
def retrieve_context(student_id: str, topic_name: str, threshold: float = 0.75) -> list[str]:
    collection = get_student_collection(student_id)
    query_vector = embed_text(topic_name)
    results = collection.query(query_embeddings=[query_vector], n_results=5)
    # NFR-03: cosine similarity threshold filter
    docs = [
        doc for doc, dist in zip(results["documents"][0], results["distances"][0])
        if (1 - dist) > threshold
    ]
    return docs

def teach_topic(topic_name: str, context_docs: list[str], student_level: str) -> str:
    context = "\n\n".join(context_docs)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""You are tutoring a {student_level} student on "{topic_name}".
Use this retrieved context:
{context}

Structure the lesson as: Concept -> Worked Example -> Real-world Analogy.
Be concrete, avoid filler, match the {student_level} depth.""",
    )
    return response.text
```

**Quiz + evaluation phase** implements FR-06, FR-07:

```python
QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "expected_concept": {"type": "string"},
                },
                "required": ["question", "expected_concept"]
            }
        }
    },
    "required": ["questions"]
}

def generate_quiz(lesson_content: str) -> list[dict]:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Generate 3 quiz questions testing comprehension of this lesson:\n{lesson_content}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=QUIZ_SCHEMA,
        ),
    )
    import json
    return json.loads(response.text)["questions"]

EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "per_question_feedback": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
    },
    "required": ["score", "per_question_feedback", "verdict"]
}

def evaluate_answers(questions: list[dict], answers: list[str]) -> dict:
    pairs = "\n".join(
        f"Q: {q['question']}\nExpected concept: {q['expected_concept']}\nStudent answer: {a}"
        for q, a in zip(questions, answers)
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""Evaluate these answers for conceptual correctness (not exact wording).
{pairs}
Score as a percentage 0-100. Pass threshold is 70.""",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EVAL_SCHEMA,
        ),
    )
    import json
    return json.loads(response.text)
```

---

## 4. FastAPI Endpoints (Frontend Contract)

This is what your frontend developer builds against. Treat this as a frozen contract once Codex implements it — changing field names later breaks the UI silently.

### Base URL
```
/api/v1
```

### Endpoints

| Method | Path | Purpose | Request Body | Response Body |
|---|---|---|---|---|
| `POST` | `/students` | Create a new student profile | `{ "name": str, "raw_input": str }` | `{ "student_id": str, "syllabus": TopicState[] }` |
|`POST `  |   `/students/upload-syllabus`|upload-syllabusCreate a student from an uploaded syllabus PDF|`multipart/form-data: name (str), file (PDF)`|`{ "student_id": str, "syllabus": TopicState[] }` 
| `GET` | `/students/{student_id}` | Get full profile (session resume) | — | `StudentProfile` (see below) |
| `POST` | `/students/{student_id}/start` | Kick off the LangGraph pipeline for current/next topic | — | `{ "status": str, "current_topic": str }` |
| `GET` | `/students/{student_id}/lesson` | Get the current lesson content | — | `{ "topic_name": str, "lesson_content": str, "sources": [{source_url, summary}] }` |
| `GET` | `/students/{student_id}/quiz` | Get quiz questions for current topic | — | `{ "topic_name": str, "questions": [{question_id, question}] }` |
| `POST` | `/students/{student_id}/answer` | Submit one or all quiz answers | `{ "answers": [{question_id, answer_text}] }` | `{ "score": float, "verdict": "pass"\|"fail", "feedback": str[], "next_action": str }` |
| `GET` | `/students/{student_id}/profile` | Dashboard data: progress overview | — | `StudentProfile` |
| `GET` | `/students/{student_id}/topics` | Full topic list with statuses | — | `TopicState[]` |
| `GET` | `/health` | Liveness check | — | `{ "status": "ok" }` |

### Shared Response Shape: `StudentProfile`
```json
{
  "student_id": "uuid",
  "name": "string",
  "wants_to_read": ["topic1", "topic2"],
  "was_taught": ["topic1"],
  "currently_on": "topic2",
  "pending": ["topic3"],
  "weak_topics": ["topic1"],
  "session_count": 4,
  "last_active": "2026-06-21T10:00:00Z"
}
```

### Error Contract
All errors return:
```json
{ "error": { "code": "string", "message": "string" } }
```
with appropriate HTTP status (404 for missing student, 422 for validation, 502 for upstream Gemini/Tavily failure after fallback exhausted).

### CORS
Enable for your frontend's dev origin (`http://localhost:5173` for Vite default) and your eventual deployed origin. Codex should make this configurable via an env var, not hardcoded.

---

## 5. Project Structure (what Codex should produce)

```
aaa-backend/
├── .env.example                 # GEMINI_API_KEY, TAVILY_API_KEY, DB paths
├── requirements.txt
├── main.py                      # FastAPI app entrypoint
├── config.py                    # env loading, model name constants
├── agents/
│   ├── __init__.py
│   ├──syllabus_parser.py       # Agent 1 — now also: extract_text_from_pdf()
│   ├── search_agent.py          # Agent 2
│   └── tutor_quiz_agent.py      # Agent 3
├── orchestration/
│   ├── __init__.py
│   ├── state.py                 # AAAState, TopicState TypedDicts
│   ├── graph.py                 # LangGraph StateGraph construction + routing
│   └── nodes.py                 # node functions wrapping each agent for graph use
├── persistence/
│   ├── __init__.py
│   ├── db.py                    # SQLite connection + schema init
│   ├── models.py                # student_profile, topic_record table ops
│   └── vector_store.py          # ChromaDB client + embed_text wrapper
├── api/
│   ├── __init__.py
│   ├── routes.py                # all /api/v1/* endpoints
│   └── schemas.py                # Pydantic request/response models
└── tests/
    ├── test_agent1.py
    ├── test_agent2.py
    ├── test_agent3.py
    └── test_graph_routing.py
```

---

## 6. The Codex Build Prompt

Copy everything in the box below directly into Codex as your task prompt. It is self-contained and references the design above by section so Codex has full context without you re-explaining anything.

```
ROLE: You are building the backend for "Autonomous Academic Agent" (AAA), a
multi-agent AI tutoring system. Work like a senior backend engineer: correct,
defensive, and consistent with the contracts below — not exploratory.

GOAL: Implement a complete, runnable FastAPI backend implementing 3 LLM agents
orchestrated by LangGraph, backed by SQLite (structured state) and ChromaDB
(vector retrieval), using Google's Gemini API as the only LLM provider.

NON-NEGOTIABLE CONSTRAINTS:
1. LLM provider is Gemini ONLY, via the `google-genai` SDK (`from google import genai`).
   Do not use `google-generativeai` (legacy SDK) or any Anthropic/OpenAI code.
2. Models: `gemini-2.5-flash-lite` for Agent 1 (Syllabus Parser) and Agent 2
   (Search Agent summarization). `gemini-2.5-flash` for Agent 3 (Tutor + Quiz).
   Embeddings: `gemini-embedding-001` with output_dimensionality=768.
3. All structured LLM outputs (syllabus JSON, quiz JSON, evaluation JSON) MUST
   use Gemini's native `response_schema` + `response_mime_type="application/json"`
   config — do not hand-roll JSON parsing with regex or prompt-only JSON requests.
4. ChromaDB client must be a module-level singleton (instantiated once, reused
   across requests) — never instantiate `chromadb.PersistentClient` inside a
   per-request function. One collection per student, named `student_{student_id}`.
5. All API keys load from environment variables via python-dotenv. Never hardcode
   keys. Produce a `.env.example` with GEMINI_API_KEY and TAVILY_API_KEY placeholders.
6. Tavily API failures must NOT crash the pipeline — catch the exception and fall
   back to a direct Gemini call asking it to summarize the topic from its own
   knowledge (label the source as "model_internal_knowledge" in the result).
7. Use Python type hints and TypedDict for all state objects. No bare dicts passed
   between functions without a defined shape.
8. Follow the exact project structure, file layout, and endpoint contract specified
   in the attached design doc sections 4 and 5 — do not improvise different route
   paths, field names, or folder names.

BUILD ORDER (build and verify in this sequence, do not skip ahead):
1. Project scaffolding: requirements.txt, .env.example, config.py, persistence/db.py
   (SQLite schema for student_profile and topic_record tables per the data_models
   in the design doc), persistence/vector_store.py (ChromaDB singleton + embed_text).
2. Agent 1 (agents/syllabus_parser.py) — implement parse_syllabus() exactly as
   specified, with the SYLLABUS_SCHEMA. Write a standalone test that parses
   3 sample inputs ("I want to learn machine learning", "teach me web development",
   "I want to learn data structures and algorithms") and prints the ordered topic list.
   Agent 1 must also accept an optional PDF path. If provided, extract its text
    with pypdf (agents/syllabus_parser.py: extract_text_from_pdf()) and feed that
    extracted text into the same parse_syllabus() flow used for raw text input —
do not create a separate parsing path for PDFs.
3. Agent 2 (agents/search_agent.py) — implement search_and_store_topic() with
   Tavily integration, ChromaDB storage, and the fallback_to_model_knowledge()
   path. Test retrieval afterward with a cosine similarity query.
4. Agent 3 (agents/tutor_quiz_agent.py) — implement retrieve_context(),
   teach_topic(), generate_quiz(), evaluate_answers() exactly as specified.
   Test on 2-3 topics end to end (teach -> quiz -> mock-evaluate).
5. Orchestration (orchestration/state.py, graph.py, nodes.py) — build the
   LangGraph StateGraph with nodes parse_syllabus -> search_topic -> teach_topic
   -> quiz_topic -> evaluate_answers -> route(advance|reteach|insert_prerequisite).
   Implement route_after_evaluation() exactly as specified (score >= 70 advances,
   attempts >= 3 and score < 50 triggers prerequisite inference, otherwise reteach).
6. API layer (api/schemas.py, api/routes.py, main.py) — implement every endpoint
   in section 4's table with the exact paths, request/response shapes, and error
   contract specified. Wire CORS via an env-configurable allowed origin list.
7. Write tests/test_graph_routing.py covering all three routing branches
   (advance, reteach, insert_prerequisite) with mocked agent outputs so the test
   suite doesn't require live API keys to run.

DELIVERABLE: A runnable backend such that `uvicorn main:app --reload` starts
the server, `POST /api/v1/students` with a raw_input string returns a parsed
syllabus and student_id, and the full pipeline can be driven end-to-end through
the documented endpoints using only a GEMINI_API_KEY and TAVILY_API_KEY in .env.

When finished, output:
- A summary of every file created
- Any deviation you made from this spec and why
- The exact curl commands to test the full flow end-to-end (create student ->
  start -> get lesson -> get quiz -> submit answers -> check profile)
```

---

## 7. What To Tell Your Frontend Dev (Today)

Hand them Section 4 verbatim. The contract is frozen at that table — they can build the UI against mocked responses matching those shapes while Codex builds the real backend in parallel. The two halves only need to agree on:
- Base URL + the 8 routes
- The `StudentProfile` and `TopicState` JSON shapes
- The error envelope shape

That's the entire integration surface. Nothing else needs to be discussed between backend and frontend today.

---

## 8. Known Risk Points (so today's build doesn't stall)

1. **`gemini-embedding-001` rate limits** — embedding calls happen once per search result (5 per topic). If you hit rate limits during testing, batch the Tavily results and call `embed_content` with a list input rather than one call per document.
2. **LangGraph state mutation** — TypedDict state in LangGraph is replaced, not mutated, between nodes. Make sure each node function returns a *new* dict with only the keys it changes, not the full state re-written from scratch (LangGraph merges these).
3. **ChromaDB collection-per-student** means a brand-new student has an empty collection until Agent 2 runs at least once — Agent 3's `retrieve_context()` will return an empty list on a fresh topic with no stored content yet. Make sure `search_topic` always runs before `teach_topic` in the graph, never in parallel.
4. **`response_schema` strictness** — Gemini will reject schemas with unsupported keywords (e.g., no `additionalProperties`, limited `format` support). Keep schemas as plain as the ones above; don't add JSON Schema features Codex might be tempted to use from OpenAI-schema habits.
