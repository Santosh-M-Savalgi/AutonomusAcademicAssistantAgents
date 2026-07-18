"""Knowledge Graph + Adaptive Learning API endpoints (Sprint 2).

Read-only endpoints exposing the Knowledge Graph Service, Learning Path
Engine, Mastery Engine, and Adaptive Router.

Architecture reference: Section 16 (REST API Design — Knowledge Graph routes).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.db.repository import (
    get_direct_prerequisites,
    get_topic_by_id,
    get_topic_by_slug,
    get_topic_context,
    get_transitive_prerequisites,
)
from app.db.models import Topic, TopicEdge
from app.services.adaptive_routing import AdaptiveRouter, RoutingDecision, RoutingResult
from app.services.knowledge_graph_service import (
    KnowledgeGraph,
    build_graph_from_models,
)
from app.services.learning_path_service import (
    LearningMode,
    LearningPath,
    LearningPathService,
)
from app.services.mastery_service import MasteryEngine, WeakConceptReport

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])

# ── singleton services ──────────────────────────────────────────────────────

_kg_cache: KnowledgeGraph | None = None  # Simple in-memory graph cache
_mastery_engine = MasteryEngine()
_path_service = LearningPathService()
_adaptive_router = AdaptiveRouter(
    mastery_engine=_mastery_engine,
    path_service=_path_service,
)


# ── request / response schemas ─────────────────────────────────────────────


class TopicNodeResponse(BaseModel):
    id: str
    name: str
    slug: str
    difficulty: str
    learning_depth: int
    mastery_threshold: float

    model_config = {"from_attributes": True}


class TopicEdgeResponse(BaseModel):
    id: str
    parent_topic_id: str
    child_topic_id: str
    relationship_type: str
    weight: float

    model_config = {"from_attributes": True}


class GraphStatsResponse(BaseModel):
    node_count: int
    edge_count: int
    has_cycle: bool
    cycle_path: list[str] | None
    topological_order: list[str] | None


class LearningPathStepResponse(BaseModel):
    topic_id: str
    topic_name: str
    topic_slug: str
    difficulty: str
    depth: int
    mastery_score: float
    is_completed: bool
    is_blocked: bool
    unmet_prerequisites: list[str]


class LearningPathResponse(BaseModel):
    mode: str
    total_topics: int
    completed_topics: int
    remaining_topics: int
    next_topic_id: str | None
    is_complete: bool
    steps: list[LearningPathStepResponse]


class MasteryEntryResponse(BaseModel):
    topic_id: str
    topic_name: str
    score: float
    confidence: float
    attempts_count: int
    threshold: float
    is_mastered: bool
    is_weak: bool


class WeakConceptResponse(BaseModel):
    weak_concepts: list[MasteryEntryResponse]
    prerequisite_deficiencies: list[MasteryEntryResponse]
    strongest_concepts: list[MasteryEntryResponse]
    has_deficiencies: bool
    root_cause_topic_id: str | None
    root_cause_topic_name: str | None


class RoutingResponse(BaseModel):
    decision: str
    current_topic_id: str | None
    next_topic_id: str | None
    reason: str
    weak_concepts: list[MasteryEntryResponse]


class MasteryInput(BaseModel):
    """Per-topic mastery input for path/routing endpoints."""
    topic_id: str
    score: float = Field(ge=0.0, le=1.0)


# ── helpers ─────────────────────────────────────────────────────────────────


def _uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {s}")


def _serialize_uuid(obj: object) -> str:
    """Recursively serialize UUIDs in dicts/lists to strings."""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _serialize_uuid(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_uuid(v) for v in obj]
    return obj


# ── endpoints ───────────────────────────────────────────────────────────────


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_graph_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GraphStatsResponse:
    """Graph-level statistics: size, cycles, topological ordering."""
    from sqlalchemy import select

    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())

    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(topics, edges)
    topo = kg.topological_sort()

    return GraphStatsResponse(
        node_count=kg.node_count,
        edge_count=kg.edge_count,
        has_cycle=kg.has_cycle(),
        cycle_path=[str(nid) for nid in kg.find_cycle_path()]
        if kg.find_cycle_path()
        else None,
        topological_order=[str(nid) for nid in topo] if topo else None,
    )


@router.get("/{syllabus_id}")
async def get_syllabus_graph(
    syllabus_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Full topic tree for a syllabus (Section 16: Knowledge Graph)."""
    sid = _uuid(syllabus_id)

    from sqlalchemy import select

    result = await db.execute(
        select(Topic).where(Topic.syllabus_id == sid)
    )
    topics = list(result.scalars().all())

    edges_result = await db.execute(
        select(TopicEdge).where(
            TopicEdge.parent_topic_id.in_([t.id for t in topics])
        )
    )
    edges = list(edges_result.scalars().all())

    return {
        "syllabus_id": str(sid),
        "topics": [
            TopicNodeResponse.model_validate(t).model_dump()
            for t in topics
        ],
        "edges": [
            TopicEdgeResponse.model_validate(e).model_dump()
            for e in edges
        ],
    }


@router.get("/topic/{topic_id}/context")
async def get_topic_prerequisites(
    topic_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Direct + transitive prerequisites for a topic (Section 16)."""
    tid = _uuid(topic_id)
    topic = await get_topic_by_id(db, tid)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    direct = await get_direct_prerequisites(db, tid)
    transitive = await get_transitive_prerequisites(db, tid)

    return {
        "topic": TopicNodeResponse.model_validate(topic).model_dump(),
        "direct_prerequisites": [
            TopicNodeResponse.model_validate(t).model_dump() for t in direct
        ],
        "transitive_prerequisites": [
            {"topic_id": str(t[0]), "depth": t[1]} for t in transitive
        ],
    }


@router.get("/topic/{topic_id}/children")
async def get_topic_children(
    topic_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Topics that build on this one (dependents)."""
    tid = _uuid(topic_id)
    topic = await get_topic_by_id(db, tid)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    from sqlalchemy import select

    result = await db.execute(
        select(Topic)
        .join(TopicEdge, TopicEdge.parent_topic_id == Topic.id)
        .where(TopicEdge.child_topic_id == tid)
    )
    children = list(result.scalars().all())

    return {
        "topic": TopicNodeResponse.model_validate(topic).model_dump(),
        "children": [
            TopicNodeResponse.model_validate(c).model_dump() for c in children
        ],
    }


@router.post("/learning-path")
async def get_learning_path(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LearningPathResponse:
    """Generate a deterministic learning path.

    Request body:
        {
            "syllabus_topic_ids": ["uuid1", "uuid2", ...],
            "mastery_scores": {"uuid1": 0.85, "uuid2": 0.3, ...},
            "mode": "standard" | "beginner" | "fast_track"
        }
    """
    topic_ids_raw: list[str] = body.get("syllabus_topic_ids", [])
    mastery_raw: dict[str, float] = body.get("mastery_scores", {})
    mode_raw: str = body.get("mode", "standard")

    syllabus_ids = [_uuid(tid) for tid in topic_ids_raw]
    mastery_scores = {_uuid(k): v for k, v in mastery_raw.items()}

    try:
        mode = LearningMode(mode_raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{mode_raw}'. Use: beginner, standard, fast_track",
        )

    # Build graph from all topics/edges in DB
    from sqlalchemy import select

    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())
    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(topics, edges)

    path = _path_service.generate(kg, syllabus_ids, mastery_scores, mode)

    return LearningPathResponse(
        mode=path.mode.value,
        total_topics=path.total_topics,
        completed_topics=path.completed_topics,
        remaining_topics=path.remaining_topics,
        next_topic_id=str(path.next_topic_id) if path.next_topic_id else None,
        is_complete=path.is_complete,
        steps=[
            LearningPathStepResponse(
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
    )


@router.post("/next-topic")
async def get_next_topic(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Get the next ready topic in the learning path.

    Request body:
        {
            "syllabus_topic_ids": ["uuid1", "uuid2", ...],
            "mastery_scores": {"uuid1": 0.85, ...},
            "mode": "standard"
        }
    """
    topic_ids_raw: list[str] = body.get("syllabus_topic_ids", [])
    mastery_raw: dict[str, float] = body.get("mastery_scores", {})
    mode_raw: str = body.get("mode", "standard")

    syllabus_ids = [_uuid(tid) for tid in topic_ids_raw]
    mastery_scores = {_uuid(k): v for k, v in mastery_raw.items()}

    try:
        mode = LearningMode(mode_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode_raw}")

    from sqlalchemy import select

    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())
    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(topics, edges)
    next_id = _path_service.get_next_topic(kg, syllabus_ids, mastery_scores, mode)

    return {
        "next_topic_id": str(next_id) if next_id else None,
        "mode": mode.value,
    }


@router.post("/weak-concepts")
async def get_weak_concepts(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WeakConceptResponse:
    """Analyze mastery and produce a weak concept report.

    Request body:
        {
            "mastery_scores": {"topic_id": score, ...},
            "current_topic_id": "uuid" (optional, for prerequisite deficiency focus)
        }
    """
    mastery_raw: dict[str, float] = body.get("mastery_scores", {})
    current_raw: str | None = body.get("current_topic_id")

    mastery_scores = {_uuid(k): v for k, v in mastery_raw.items()}
    current_topic_id = _uuid(current_raw) if current_raw else None

    from sqlalchemy import select

    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())
    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(topics, edges)

    # Build fake mastery rows for analysis
    class FakeRow:
        def __init__(self, tid, score, confidence, attempts):
            self.topic_id = tid
            self.score = score
            self.confidence = confidence
            self.attempts_count = attempts

    rows = [FakeRow(tid, score, 0.0, 0) for tid, score in mastery_scores.items()]
    report = _mastery_engine.analyze(kg, rows, current_topic_id)
    root = report.root_cause(current_topic_id)

    return WeakConceptResponse(
        weak_concepts=[
            MasteryEntryResponse(
                topic_id=str(e.topic_id),
                topic_name=e.topic_name,
                score=e.score,
                confidence=e.confidence,
                attempts_count=e.attempts_count,
                threshold=e.threshold,
                is_mastered=e.is_mastered,
                is_weak=e.is_weak,
            )
            for e in report.weak_concepts
        ],
        prerequisite_deficiencies=[
            MasteryEntryResponse(
                topic_id=str(e.topic_id),
                topic_name=e.topic_name,
                score=e.score,
                confidence=e.confidence,
                attempts_count=e.attempts_count,
                threshold=e.threshold,
                is_mastered=e.is_mastered,
                is_weak=e.is_weak,
            )
            for e in report.prerequisite_deficiencies
        ],
        strongest_concepts=[
            MasteryEntryResponse(
                topic_id=str(e.topic_id),
                topic_name=e.topic_name,
                score=e.score,
                confidence=e.confidence,
                attempts_count=e.attempts_count,
                threshold=e.threshold,
                is_mastered=e.is_mastered,
                is_weak=e.is_weak,
            )
            for e in report.strongest_concepts
        ],
        has_deficiencies=report.has_deficiencies,
        root_cause_topic_id=str(root.topic_id) if root else None,
        root_cause_topic_name=root.topic_name if root else None,
    )


@router.post("/route")
async def compute_route(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoutingResponse:
    """Compute adaptive routing decision.

    Request body:
        {
            "current_topic_id": "uuid",
            "syllabus_topic_ids": ["uuid1", "uuid2", ...],
            "mastery_scores": {"uuid1": 0.85, ...},
            "quiz_score": 0.65 (optional),
            "attempts_on_current": 2 (optional)
        }
    """
    current_raw: str = body.get("current_topic_id", "")
    topic_ids_raw: list[str] = body.get("syllabus_topic_ids", [])
    mastery_raw: dict[str, float] = body.get("mastery_scores", {})
    quiz_score: float | None = body.get("quiz_score")
    attempts: int = body.get("attempts_on_current", 0)

    if not current_raw:
        raise HTTPException(status_code=400, detail="current_topic_id required")

    current_topic_id = _uuid(current_raw)
    syllabus_ids = [_uuid(tid) for tid in topic_ids_raw]
    mastery_scores = {_uuid(k): v for k, v in mastery_raw.items()}

    from sqlalchemy import select

    topics_result = await db.execute(select(Topic))
    topics = list(topics_result.scalars().all())
    edges_result = await db.execute(select(TopicEdge))
    edges = list(edges_result.scalars().all())

    kg = build_graph_from_models(topics, edges)

    result = _adaptive_router.route(
        graph=kg,
        mastery_scores=mastery_scores,
        current_topic_id=current_topic_id,
        syllabus_topic_ids=syllabus_ids,
        quiz_score=quiz_score,
        attempts_on_current=attempts,
    )

    weak_entries: list[MasteryEntryResponse] = []
    if result.weak_concept_report:
        weak_entries = [
            MasteryEntryResponse(
                topic_id=str(e.topic_id),
                topic_name=e.topic_name,
                score=e.score,
                confidence=e.confidence,
                attempts_count=e.attempts_count,
                threshold=e.threshold,
                is_mastered=e.is_mastered,
                is_weak=e.is_weak,
            )
            for e in result.weak_concept_report.weak_concepts
        ]

    return RoutingResponse(
        decision=result.decision.value,
        current_topic_id=str(result.current_topic_id)
        if result.current_topic_id else None,
        next_topic_id=str(result.next_topic_id)
        if result.next_topic_id else None,
        reason=result.reason,
        weak_concepts=weak_entries,
    )
