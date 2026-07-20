"""Learning API endpoints.

POST /api/v2/learning/goal — create a learning goal, persist, return roadmap.
POST /api/v2/learning/study — invoke the LangGraph for a full study cycle.

Flow (goal):
  1. SyllabusParser agent breaks free text into topics with prerequisites
  2. Syllabus + Topic + TopicEdge records created in database
  3. Learning session created via SessionManager
  4. KnowledgeGraph built from persisted models
  5. LearningPath generated via LearningPathService (roadmap)
  6. Session checkpoint seeded with initial workflow state
  7. Returns syllabus_id + session_id + roadmap so frontend can navigate

Flow (study):
  1. Builds initial graph state from the session + topic data
  2. Invokes the LangGraph StateGraph: parse → retrieve → tutor → quiz → evaluate → route
  3. If answers provided, the graph runs through evaluate and route
  4. Returns the complete graph state (lesson, quiz, evaluation, routing)
"""

from __future__ import annotations

import uuid
from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.agents.syllabus_parser import ParsedTopic as ParsedTopicData, SyllabusParser

_log = logging.getLogger(__name__)
from app.auth.dependencies import get_current_student
from app.graph import get_graph, initial_state
from app.db.models import ConceptMastery, Syllabus, Topic, TopicEdge, User
from app.db.models.enums import (
    DifficultyLevel,
    EdgeCreatedBy,
    EdgeRelationshipType,
    SyllabusStatus,
)
from app.core.exceptions import (
    BackendError,
    DatabaseConflictError,
    InvalidInputError,
    RoadmapGenerationError,
    SyllabusParseError,
)
from app.db.postgres import get_db
from app.services.knowledge_graph_service import (
    build_graph_from_models,
)
from app.services.learning_path_service import (
    LearningMode,
    LearningPath,
    LearningPathService,
)
from app.session.checkpoint_store import CheckpointStore
from app.session.session_manager import SessionManager
from app.session.session_models import SessionData

router = APIRouter(prefix="/learning", tags=["learning"])


# ── Request / Response schemas ──────────────────────────────────────────────


class LearningGoalRequest(BaseModel):
    goal: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Free-text learning goal, e.g. 'I want to learn Python'",
    )


class TopicInfo(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    difficulty: str
    prerequisites: list[str] = []


class RoadmapStepResponse(BaseModel):
    topic_id: str
    topic_name: str
    topic_slug: str
    difficulty: str
    depth: int
    mastery_score: float
    is_completed: bool
    is_blocked: bool
    unmet_prerequisites: list[str]


class LearningGoalResponse(BaseModel):
    syllabus_id: str
    session_id: str
    title: str
    topics: list[TopicInfo]
    roadmap: list[RoadmapStepResponse]
    roadmap_mode: str


# ── GET response schemas ──────────────────────────────────────────────────────


class ProgressInfo(BaseModel):
    """Per-topic progress summary for the Learning / Roadmap page."""
    topic_id: str
    topic_name: str
    topic_slug: str
    difficulty: str
    mastery_score: float
    is_completed: bool
    quiz_attempts: int


class RoadmapResponse(BaseModel):
    """Complete learning journey state returned by GET /learning/{syllabus_id}."""
    syllabus_id: str
    session_id: str
    learning_goal: str
    title: str
    topics: list[TopicInfo]
    roadmap: list[RoadmapStepResponse]
    roadmap_mode: str
    progress: list[ProgressInfo]
    overall_progress_pct: float
    completed_count: int
    total_count: int
    current_topic_id: str | None
    current_topic_name: str | None
    next_topic_id: str | None
    next_topic_name: str | None


# ── Helper: create slugs that avoid DB constraint collisions ────────────────


def _make_slug(name: str) -> str:
    """Generate a URL-safe slug from a topic name."""
    slug = name.lower().strip()
    slug = slug.replace(" ", "-")
    slug = slug.replace("/", "-")
    slug = slug.replace("&", "and")
    # Remove non-alphanumeric (keep hyphens)
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:290]


# ── Endpoint ────────────────────────────────────────────────────────────────


@router.post("/goal", response_model=LearningGoalResponse, status_code=201)
async def create_learning_goal(
    request: LearningGoalRequest,
    current_user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
) -> LearningGoalResponse:
    """Accept a learning goal, parse it into curriculum, persist everything,
    generate a roadmap, and seed the session checkpoint with initial state.

    Flow:
    1. SyllabusParser agent breaks free text into topics with prerequisites
    2. Syllabus + Topic + TopicEdge records created in database
    3. Learning session created via SessionManager
    4. KnowledgeGraph built from persisted models
    5. LearningPath generated via LearningPathService (roadmap)
    6. Session checkpoint seeded with initial workflow state
    7. Returns syllabus_id + session_id + roadmap so frontend can navigate
    """
    parser = SyllabusParser()

    try:
        parsed = await parser.parse(request.goal)
    except Exception as exc:
        _log.exception("Syllabus parsing failed: %s", repr(exc))
        raise SyllabusParseError(cause=exc) from exc

    if not parsed.topics:
        raise InvalidInputError(
            message="Could not extract any topics from your learning goal. Try being more specific."
        )

    # ── Create Syllabus record ──────────────────────────────────────────
    syllabus = Syllabus(
        user_id=current_user.id,
        title=parsed.title,
        status=SyllabusStatus.ready,
    )
    db.add(syllabus)
    await db.flush()  # Get syllabus.id

    # ── Create / reuse Topic records ────────────────────────────────────
    # Topics are global reusable entities (architecture Section 7.2):
    # the same slug ("python-basics") must point to the same Topic row
    # regardless of which syllabus references it.  SELECT before INSERT.
    slug_to_parsed: dict[str, Any] = {}
    for t in parsed.topics:
        slug = _make_slug(t.slug)
        slug_to_parsed[slug] = t

    # Batch-lookup all slugs that already exist in the database
    all_slugs = [_make_slug(t.slug) for t in parsed.topics]
    existing_result = await db.execute(
        select(Topic).where(Topic.slug.in_(all_slugs))
    )
    existing_topics = list(existing_result.scalars().all())
    slug_to_db_topic: dict[str, Topic] = {
        et.slug: et for et in existing_topics
    }
    created_topic_ids: list[str] = []
    topic_info_list: list[TopicInfo] = []

    # First pass: create missing Topic rows; reuse existing ones
    for t in parsed.topics:
        slug = _make_slug(t.slug)
        existing = slug_to_db_topic.get(slug)

        if existing is not None:
            # Reuse the global topic row; leave existing syllabus_id intact.
            # The topic is linked to this syllabus via TopicEdge records
            # created in the second pass below.
            topic = existing
        else:
            difficulty = t.difficulty.lower()
            if difficulty not in ("beginner", "intermediate", "advanced"):
                difficulty = "beginner"

            topic = Topic(
                name=t.name,
                slug=slug,
                description=t.description or f"Learn about {t.name}",
                difficulty=DifficultyLevel(difficulty),
                syllabus_id=syllabus.id,
                mastery_threshold=0.75,
            )
            db.add(topic)
            slug_to_db_topic[slug] = topic

    await db.flush()  # Get all topic IDs (newly inserted rows)

    # Second pass: create TopicEdge records
    # ── Pre-check: load any TopicEdge pairs that already exist in the DB ──
    # so we skip re-inserting them.
    slug_to_parsed_with_slug: dict[str, ParsedTopicData] = {}
    for t in parsed.topics:
        slug = _make_slug(t.slug)
        slug_to_parsed_with_slug[slug] = t

    # Collect all candidate (parent_id, child_id) pairs first,
    # then batch-query which ones already exist in the DB.
    candidate_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for parsed_topic in parsed.topics:
        slug = _make_slug(parsed_topic.slug)
        current_topic = slug_to_db_topic.get(slug)
        if not current_topic:
            continue
        for prereq_slug in parsed_topic.prerequisites:
            prereq_slug_clean = _make_slug(prereq_slug)
            prereq_topic = slug_to_db_topic.get(prereq_slug_clean)
            if prereq_topic is not None and prereq_topic.id != current_topic.id:
                candidate_pairs.add((current_topic.id, prereq_topic.id))

    # Batch-query existing edges for exact candidate pairs
    if candidate_pairs:
        existing_edges_result = await db.execute(
            select(TopicEdge).where(
                or_(
                    *[
                        (TopicEdge.parent_topic_id == p[0])
                        & (TopicEdge.child_topic_id == p[1])
                        for p in candidate_pairs
                    ]
                )
            )
        )
        existing_db_edges = list(existing_edges_result.scalars().all())
    else:
        existing_db_edges = []
    existing_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]] = {
        (e.parent_topic_id, e.child_topic_id, e.relationship_type)
        for e in existing_db_edges
    }

    # ── Insert only truly new edges ─────────────────────────────────────
    seen_edge_keys: set[tuple[uuid.UUID, uuid.UUID, str]] = set()

    for parsed_topic in parsed.topics:
        slug = _make_slug(parsed_topic.slug)
        current_topic = slug_to_db_topic.get(slug)
        if not current_topic:
            continue

        for prereq_slug in parsed_topic.prerequisites:
            prereq_slug_clean = _make_slug(prereq_slug)
            prereq_topic = slug_to_db_topic.get(prereq_slug_clean)
            if prereq_topic is not None and prereq_topic.id != current_topic.id:
                edge_key = (
                    current_topic.id,
                    prereq_topic.id,
                    EdgeRelationshipType.direct_prerequisite.value,
                )
                if edge_key in seen_edge_keys:
                    continue
                if edge_key in existing_edge_keys:
                    continue

                seen_edge_keys.add(edge_key)
                edge = TopicEdge(
                    parent_topic_id=current_topic.id,
                    child_topic_id=prereq_topic.id,
                    relationship_type=EdgeRelationshipType.direct_prerequisite,
                    weight=1.0,
                    created_by=EdgeCreatedBy.llm_inferred,
                )
                db.add(edge)

        topic_info_list.append(TopicInfo(
            id=str(current_topic.id),
            name=current_topic.name,
            slug=current_topic.slug,
            description=current_topic.description or "",
            difficulty=str(current_topic.difficulty),
            prerequisites=parsed_topic.prerequisites,
        ))
        created_topic_ids.append(str(current_topic.id))

    # ── Create learning session ────────────────────────────────────────
    # Persist to both Redis (hot) and Postgres (durable) so the
    # LangGraph checkpointer can find the session in Postgres later.
    manager = SessionManager()
    try:
        session: SessionData = await manager.create_session(
            student_id=str(current_user.id),
            syllabus_id=str(syllabus.id),
        )
        # Also persist to Postgres for durable checkpoint storage
        from app.db.models import Session as SessionModel
        session_pg = SessionModel(
            id=uuid.UUID(session.session_id),
            user_id=current_user.id,
            status="active",
        )
        db.add(session_pg)
        await db.flush()
    except Exception as exc:
        # Session creation failed, but syllabus/topics are already persisted
        raise BackendError(
            error_code="SESSION_CREATION_FAILED",
            message="Your learning plan was created but the session could not be started. Please try again.",
            http_status=503,
            retryable=True,
            cause=exc,
        ) from exc

    try:
        await db.commit()
    except Exception as exc:
        raise DatabaseConflictError(cause=exc) from exc

    # ── Phase 2: Build KnowledgeGraph & generate roadmap ──────────────────
    # Build the graph from all topics in this syllabus (including reused
    # global topics that may have a different original syllabus_id).
    db_topics = list(slug_to_db_topic.values())

    edges_result = await db.execute(
        select(TopicEdge).where(
            TopicEdge.parent_topic_id.in_([t.id for t in db_topics])
        )
    )
    db_edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(db_topics, db_edges)

    # All topics start with mastery = 0 (no quiz taken yet)
    empty_mastery: dict[uuid.UUID, float] = {}
    path_service = LearningPathService()
    roadmap: LearningPath = path_service.generate(
        graph=kg,
        syllabus_topic_ids=[t.id for t in db_topics],
        mastery_scores=empty_mastery,
        mode=LearningMode.STANDARD,
    )

    # ── Phase 3: Seed session checkpoint with initial workflow state ────────
    # Store the roadmap and current topic index so the lesson/workflow
    # endpoints can resume where the student left off.
    first_topic_step = None
    if roadmap.steps:
        first_topic_step = roadmap.steps[0]

    checkpoint_store = CheckpointStore()
    await checkpoint_store.save_checkpoint(session)  # re-save with latest state

    logger = __import__("logging").getLogger(__name__)
    logger.info(
        "Learning goal committed: syllabus=%s session=%s topics=%d "
        "roadmap_steps=%d first_topic=%s",
        syllabus.id,
        session.session_id,
        len(db_topics),
        len(roadmap.steps),
        first_topic_step.topic_name if first_topic_step else "none",
    )

    # ── Phase 4: Return with roadmap ───────────────────────────────────────
    return LearningGoalResponse(
        syllabus_id=str(syllabus.id),
        session_id=session.session_id,
        title=syllabus.title,
        topics=topic_info_list,
        roadmap=[
            RoadmapStepResponse(
                topic_id=str(step.topic_id),
                topic_name=step.topic_name,
                topic_slug=step.topic_slug,
                difficulty=step.difficulty,
                depth=step.depth,
                mastery_score=step.mastery_score,
                is_completed=step.is_completed,
                is_blocked=step.is_blocked,
                unmet_prerequisites=[str(p) for p in step.unmet_prerequisites],
            )
            for step in roadmap.steps
        ],
        roadmap_mode=roadmap.mode.value,
    )


# ── Study endpoint schemas ───────────────────────────────────────────────────


class StudyRequest(BaseModel):
    """Request to run a study cycle through the LangGraph."""

    session_id: str = Field(..., description="Session UUID from POST /learning/goal")
    syllabus_id: str = Field(..., description="Syllabus UUID")
    learning_goal: str = Field("", description="Original learning goal")
    current_topic_id: str = Field(..., description="Topic UUID to study")
    current_topic_name: str = Field(..., description="Topic name")
    current_topic_description: str = Field("", description="Topic description")
    current_topic_difficulty: str = Field("beginner", description="Difficulty")
    learning_mode: str = Field("journey", description="sprint | journey | mastery")
    topics: list[dict] = Field(default_factory=list, description="Parsed topic list")
    phase: str = Field("parse", description="Starting phase: parse|retrieve|tutor|quiz|evaluate")
    answers: list[dict] | None = Field(None, description="Quiz answers for evaluation phase")


class StudyResponse(BaseModel):
    """Complete study cycle result from the LangGraph."""

    session_id: str
    phase: str
    phase_completed: str
    error: str | None = None
    # Lesson output
    lesson: dict | None = None
    # Quiz output (without correct answers in production)
    quiz: dict | None = None
    # Evaluation output
    evaluation: dict | None = None
    # Routing
    routing_decision: str = ""
    routing_reason: str = ""
    next_topic_id: str | None = None
    attempts_on_current: int = 0
    mastery_scores: dict = {}
    # Retrieval
    youtube_suggestions: list[dict] | None = None


# ── Study endpoint ───────────────────────────────────────────────────────────


@router.post("/study", response_model=StudyResponse)
async def study_topic(
    request: StudyRequest,
    current_user: User = Depends(get_current_student),
) -> StudyResponse:
    """Run a full or partial study cycle through the LangGraph.

    Invokes the StateGraph with the given state. Depending on ``phase``:
      - parse: runs parse→retrieve→tutor→quiz and checkpoints before evaluate
      - tutor: runs retrieve→tutor→quiz and checkpoints before evaluate
      - quiz: runs quiz and checkpoints before evaluate
      - evaluate: requires ``answers``, runs evaluate→route

    The graph is checkpointed between phases. The same session_id can
    be used across multiple calls to progress through the workflow.

    This endpoint demonstrates the full automatic cycle:
      goal → parse → retrieval → lesson → quiz → evaluate → route
    without requiring separate frontend button clicks between phases.
    """
    # Build state from the request
    state = initial_state(
        session_id=request.session_id,
        syllabus_id=request.syllabus_id,
        learning_goal=request.learning_goal,
        topics=request.topics,
        current_topic_id=request.current_topic_id,
        current_topic_name=request.current_topic_name,
        current_topic_description=request.current_topic_description,
        current_topic_difficulty=request.current_topic_difficulty,
        learning_mode=request.learning_mode,
    )
    state["phase"] = request.phase

    if request.answers:
        state["answers"] = request.answers

    # Invoke the graph
    graph = get_graph()
    config = {"configurable": {"thread_id": request.session_id}}

    try:
        result = await graph.ainvoke(state, config)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Graph invocation failed: {exc}",
        ) from exc

    # Strip correct answers from quiz before returning to the frontend
    quiz_safe = None
    if result.get("quiz"):
        quiz_safe = {
            "topic_id": result["quiz"].get("topic_id", ""),
            "topic_name": result["quiz"].get("topic_name", ""),
            "questions": [
                {
                    "id": q.get("id", ""),
                    "question": q.get("question", ""),
                    "options": q.get("options", []),
                    "difficulty": q.get("difficulty", "medium"),
                    "concept_tag": q.get("concept_tag", "general"),
                    "bloom_level": q.get("bloom_level", "understand"),
                    "estimated_time_seconds": q.get("estimated_time_seconds", 60),
                }
                for q in result["quiz"].get("questions", [])
            ],
            "total_questions": result["quiz"].get("total_questions", 0),
            "difficulty_breakdown": result["quiz"].get("difficulty_breakdown", {}),
        }

    # YouTube suggestions from retrieval state
    yt_suggestions = None
    retrieval_web = result.get("retrieval_web")
    if retrieval_web and isinstance(retrieval_web, dict):
        yt = retrieval_web.get("youtube_results", [])
        if yt:
            yt_suggestions = yt

    return StudyResponse(
        session_id=request.session_id,
        phase=result.get("phase", ""),
        phase_completed=result.get("phase_completed", ""),
        error=result.get("error"),
        lesson=result.get("lesson"),
        quiz=quiz_safe,
        evaluation=result.get("evaluation"),
        routing_decision=result.get("routing_decision", ""),
        routing_reason=result.get("routing_reason", ""),
        next_topic_id=result.get("next_topic_id"),
        attempts_on_current=result.get("attempts_on_current", 0),
        mastery_scores=result.get("mastery_scores", {}),
        youtube_suggestions=yt_suggestions,
    )


# ── GET Endpoint: Retrieve the full learning journey ──────────────────────────


@router.get("/{syllabus_id}", response_model=RoadmapResponse)
async def get_learning_roadmap(
    syllabus_id: str,
    current_user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
) -> RoadmapResponse:
    """Retrieve the complete learning journey for a syllabus.

    Returns the syllabus metadata, topic list, roadmap with mastery scores,
    and progress summary. This endpoint allows the frontend to restore the
    full roadmap state after navigation or page refresh — no more dependency
    on ephemeral React Router location.state.

    The roadmap is rebuilt deterministically from the database, so it always
    reflects the current state: mastery scores from quizzes, completion status,
    and the correct next topic.
    """
    # ── Resolve syllabus ──────────────────────────────────────────────────
    sid: uuid.UUID
    try:
        sid = uuid.UUID(syllabus_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid syllabus ID format")

    syllabus_result = await db.execute(
        select(Syllabus).where(Syllabus.id == sid)
    )
    syllabus = syllabus_result.scalar_one_or_none()
    if syllabus is None:
        raise HTTPException(status_code=404, detail="Syllabus not found")

    # ── Get topics for this syllabus ──────────────────────────────────────
    topics_result = await db.execute(
        select(Topic).where(Topic.syllabus_id == sid)
    )
    db_topics = list(topics_result.scalars().all())

    if not db_topics:
        raise HTTPException(status_code=404, detail="No topics found for this syllabus")

    # ── Get topic edges ───────────────────────────────────────────────────
    topic_ids = [t.id for t in db_topics]
    edges_result = await db.execute(
        select(TopicEdge).where(
            TopicEdge.parent_topic_id.in_(topic_ids)
        )
    )
    db_edges = list(edges_result.scalars().all())

    # ── Get mastery scores for this user ──────────────────────────────────
    mastery_result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == current_user.id,
            ConceptMastery.topic_id.in_(topic_ids),
        )
    )
    mastery_rows = list(mastery_result.scalars().all())
    mastery_map: dict[uuid.UUID, float] = {
        m.topic_id: m.score for m in mastery_rows
    }

    # ── Get the user's current session ────────────────────────────────────
    from app.db.models import Session as SessionModel
    session_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .order_by(SessionModel.last_active_at.desc())
        .limit(1)
    )
    session = session_result.scalar_one_or_none()

    # ── Create a session if none exists ──────────────────────────────────
    # Ensures session_id is always populated for checkpointing, even when
    # the user navigates directly to the roadmap without creating a goal.
    if session is None:
        manager = SessionManager()
        try:
            session_data: SessionData = await manager.create_session(
                student_id=str(current_user.id),
                syllabus_id=str(syllabus.id),
            )
            session = SessionModel(
                id=uuid.UUID(session_data.session_id),
                user_id=current_user.id,
                status="active",
            )
            db.add(session)
        except Exception:
            _log.warning("Failed to create session for roadmap — proceeding without")

    # ── Build knowledge graph and learning path ───────────────────────────
    kg = build_graph_from_models(db_topics, db_edges)
    path_service = LearningPathService()
    try:
        path: LearningPath = path_service.generate(
            graph=kg,
            syllabus_topic_ids=topic_ids,
            mastery_scores=mastery_map,
            mode=LearningMode.STANDARD,
        )
    except Exception as exc:
        _log.exception("Failed to generate learning path for syllabus %s", syllabus_id)
        raise RoadmapGenerationError(cause=exc) from exc

    # ── Build response ────────────────────────────────────────────────────
    topic_info_list: list[TopicInfo] = []
    for t in db_topics:
        prereqs: list[str] = []
        for edge in db_edges:
            if edge.parent_topic_id == t.id:
                # Find child topic name as prerequisite
                for ct in db_topics:
                    if ct.id == edge.child_topic_id:
                        prereqs.append(ct.slug)
                        break
        topic_info_list.append(TopicInfo(
            id=str(t.id),
            name=t.name,
            slug=t.slug,
            description=t.description or "",
            difficulty=str(t.difficulty),
            prerequisites=prereqs,
        ))

    progress_list: list[ProgressInfo] = []
    for step in path.steps:
        tid = uuid.UUID(step.topic_id) if isinstance(step.topic_id, str) else step.topic_id
        progress_list.append(ProgressInfo(
            topic_id=str(step.topic_id),
            topic_name=step.topic_name,
            topic_slug=step.topic_slug,
            difficulty=step.difficulty,
            mastery_score=step.mastery_score,
            is_completed=step.is_completed,
            quiz_attempts=0,  # TODO: fetch from DB if needed
        ))

    # Current topic from session
    current_topic_id = str(session.current_topic_id) if session and session.current_topic_id else None
    current_topic_name: str | None = None
    if current_topic_id:
        for t in db_topics:
            if str(t.id) == current_topic_id:
                current_topic_name = t.name
                break

    session_id_str = str(session.id) if session else ""

    return RoadmapResponse(
        syllabus_id=str(syllabus.id),
        session_id=session_id_str,
        learning_goal=syllabus.title,  # title is the learning goal
        title=syllabus.title,
        topics=topic_info_list,
        roadmap=[
            RoadmapStepResponse(
                topic_id=str(s.topic_id),
                topic_name=s.topic_name,
                topic_slug=s.topic_slug,
                difficulty=s.difficulty,
                depth=s.depth,
                mastery_score=s.mastery_score,
                is_completed=s.is_completed,
                is_blocked=s.is_blocked,
                unmet_prerequisites=[str(p) for p in s.unmet_prerequisites],
            )
            for s in path.steps
        ],
        roadmap_mode=path.mode.value,
        progress=progress_list,
        overall_progress_pct=(
            (path.completed_topics / path.total_topics * 100)
            if path.total_topics > 0
            else 0.0
        ),
        completed_count=path.completed_topics,
        total_count=path.total_topics,
        current_topic_id=current_topic_id,
        current_topic_name=current_topic_name,
        next_topic_id=str(path.next_topic_id) if path.next_topic_id else None,
        next_topic_name=(
            next((s.topic_name for s in path.steps if str(s.topic_id) == str(path.next_topic_id)), None)
            if path.next_topic_id
            else None
        ),
    )
