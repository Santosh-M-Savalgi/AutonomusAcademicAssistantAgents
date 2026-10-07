"""Transactional PostgreSQL graph publication and immutable edge-review versions."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.curriculum.graph import validate_dag
from packages.domain.enums import JobStatus, LearningEventType
from packages.domain.events import LearningEventInput, LearningEventPayload
from packages.domain.extraction import DocumentSource
from packages.domain.graph import (
    Concept,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphBuildJobPayload,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    GraphPublicationStatus,
    GraphSnapshot,
    GraphSource,
    MappingKind,
    TopicConceptMapping,
)
from packages.domain.graph_publication import GraphPublication
from packages.domain.jobs import ClaimedJob
from packages.domain.review import ReviewElement
from packages.persistence.artifacts import persist_json
from packages.persistence.learning_events import insert_learning_event
from packages.persistence.models import (
    CurriculumGraphConcept,
    CurriculumGraphEdge,
    CurriculumGraphMapping,
    CurriculumGraphNode,
    CurriculumGraphVersion,
    CurriculumReview,
    Job,
)
from packages.persistence.object_storage import ObjectStorage
from packages.persistence.worker_storage import storage_call

GRAPH_JOB_NAMESPACE = uuid5(NAMESPACE_URL, "aaa-v3:graph-build-jobs:v1")


def graph_build_job_identity(review_id: UUID, revision_id: UUID) -> UUID:
    return uuid5(GRAPH_JOB_NAMESPACE, f"{review_id}:{revision_id}")


class GraphPublicationConflictError(ValueError):
    """An immutable graph identity was requested with different content."""


class GraphReviewConflictError(ValueError):
    """A graph edge review was stale or already reviewed."""


class GraphLeaseExpiredError(ValueError):
    """The attempt lost its lease before publication finished."""


def graph_artifact_key(snapshot: GraphSnapshot) -> str:
    digest = sha256(snapshot.canonical_bytes()).hexdigest()
    return (f"courses/{snapshot.course_id}/graphs/{snapshot.curriculum_revision_id}/"
            f"v{snapshot.graph_version}/{digest}.json")


async def _owned_job(session: AsyncSession, job: ClaimedJob) -> Job | None:
    return (await session.scalars(
        select(Job).where(
            Job.id == job.id,
            Job.locked_by == job.worker_id,
            Job.attempts == job.attempts,
            Job.status == JobStatus.RUNNING,
            Job.lease_expires_at > func.clock_timestamp(),
        ).with_for_update()
    )).one_or_none()


async def _graph_rows(
    session: AsyncSession, graph: CurriculumGraphVersion,
) -> tuple[list[CurriculumGraphNode], list[CurriculumGraphConcept],
           list[CurriculumGraphMapping], list[CurriculumGraphEdge]]:
    nodes = list((await session.scalars(select(CurriculumGraphNode).where(
        CurriculumGraphNode.graph_id == graph.id,
    ).order_by(CurriculumGraphNode.stable_node_id))).all())
    concepts = list((await session.scalars(select(CurriculumGraphConcept).where(
        CurriculumGraphConcept.graph_id == graph.id,
    ).order_by(CurriculumGraphConcept.stable_concept_id))).all())
    mappings = list((await session.scalars(select(CurriculumGraphMapping).where(
        CurriculumGraphMapping.graph_id == graph.id,
    ).order_by(CurriculumGraphMapping.mapping_id))).all())
    edges = list((await session.scalars(select(CurriculumGraphEdge).where(
        CurriculumGraphEdge.graph_id == graph.id,
    ).order_by(CurriculumGraphEdge.edge_id))).all())
    return nodes, concepts, mappings, edges


def _snapshot_from_rows(
    graph: CurriculumGraphVersion,
    nodes: list[CurriculumGraphNode],
    concepts: list[CurriculumGraphConcept],
    mappings: list[CurriculumGraphMapping],
    edges: list[CurriculumGraphEdge],
) -> GraphSnapshot:
    return GraphSnapshot(
        graph_version=graph.version_number,
        course_id=graph.course_id,
        curriculum_revision_id=graph.curriculum_revision_id,
        curriculum_source=(
            None if graph.curriculum_source is None
            else DocumentSource.model_validate(graph.curriculum_source)
        ),
        nodes=tuple(GraphNode(
            id=row.stable_node_id,
            node_type=GraphNodeType(row.node_type),
            label=row.label,
            parent_id=row.parent_stable_node_id,
            curriculum_element_id=row.curriculum_element_id,
            curriculum_element=(
                None if row.curriculum_element is None
                else ReviewElement.model_validate(row.curriculum_element)
            ),
            source=GraphSource(row.source),
            confidence=row.confidence,
        ) for row in nodes),
        concepts=tuple(Concept(
            id=row.stable_concept_id,
            key=row.key,
            title=row.title,
            description=row.description,
            source=GraphSource(row.source),
            confidence=row.confidence,
            verified=row.verified,
            derived_from_topic_id=row.derived_from_topic_id,
        ) for row in concepts),
        mappings=tuple(TopicConceptMapping(
            mapping_id=row.mapping_id,
            topic_id=row.topic_id,
            concept_id=row.concept_id,
            mapping_kind=MappingKind(row.mapping_kind),
            source=GraphSource(row.source),
            confidence=row.confidence,
            verified=row.verified,
        ) for row in mappings),
        edges=tuple(GraphEdge(
            edge_id=row.edge_id,
            edge_type=EdgeType(row.edge_type),
            source_node_id=row.source_node_id,
            target_node_id=row.target_node_id,
            source=EdgeSource(row.source),
            confidence=row.confidence,
            status=EdgeStatus(row.status),
        ) for row in edges),
    )


def _add_snapshot_rows(
    session: AsyncSession,
    graph_id: UUID,
    snapshot: GraphSnapshot,
    *,
    reviewed_edge_id: UUID | None = None,
    reviewed_by_identity_id: UUID | None = None,
    reviewed_at: datetime | None = None,
    previous_edges: list[CurriculumGraphEdge] | None = None,
) -> None:
    audits = {edge.edge_id: (edge.reviewed_by_identity_id, edge.reviewed_at)
              for edge in previous_edges or []}
    if reviewed_edge_id is not None:
        audits[reviewed_edge_id] = (reviewed_by_identity_id, reviewed_at)
    session.add_all([
        CurriculumGraphNode(
            id=uuid4(), graph_id=graph_id, stable_node_id=node.id,
            node_type=node.node_type.value, label=node.label,
            parent_stable_node_id=node.parent_id,
            curriculum_element_id=node.curriculum_element_id,
            curriculum_element=(
                None if node.curriculum_element is None
                else node.curriculum_element.model_dump(mode="json")
            ),
            source=node.source.value, confidence=node.confidence,
        ) for node in snapshot.nodes
    ])
    session.add_all([
        CurriculumGraphConcept(
            id=uuid4(), graph_id=graph_id, stable_concept_id=concept.id,
            key=concept.key, title=concept.title, description=concept.description,
            source=concept.source.value, confidence=concept.confidence,
            verified=concept.verified, derived_from_topic_id=concept.derived_from_topic_id,
        ) for concept in snapshot.concepts
    ])
    session.add_all([
        CurriculumGraphMapping(
            id=uuid4(), graph_id=graph_id, mapping_id=mapping.mapping_id,
            topic_id=mapping.topic_id, concept_id=mapping.concept_id,
            mapping_kind=mapping.mapping_kind.value, source=mapping.source.value,
            confidence=mapping.confidence, verified=mapping.verified,
        ) for mapping in snapshot.mappings
    ])
    session.add_all([
        CurriculumGraphEdge(
            id=uuid4(), graph_id=graph_id, edge_id=edge.edge_id,
            edge_type=edge.edge_type.value, source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id, source=edge.source.value,
            confidence=edge.confidence, status=edge.status.value,
            reviewed_by_identity_id=(
                audits.get(edge.edge_id, (None, None))[0]
            ),
            reviewed_at=audits.get(edge.edge_id, (None, None))[1],
        ) for edge in snapshot.edges
    ])


async def publish_graph_for_job(
    session: AsyncSession,
    job: ClaimedJob,
    snapshot: GraphSnapshot,
    *,
    artifact_ref: str,
    artifact_sha256: str,
    artifact_bytes: int,
    actor_identity_id: UUID,
    actor_subject: str,
) -> bool:
    """Publish only while the worker attempt still owns its lease."""

    owned = await _owned_job(session, job)
    if owned is None:
        return False
    payload = GraphBuildJobPayload.model_validate(owned.payload)
    review = await session.get(CurriculumReview, payload.review_id)
    if (
        owned.job_type != "graph_build"
        or snapshot.course_id != payload.course_id
        or snapshot.curriculum_revision_id != payload.curriculum_revision_id
        or snapshot.graph_version != payload.graph_version
        or actor_identity_id != payload.actor_identity_id
        or actor_subject != payload.actor_subject
        or review is None or review.status != "CONFIRMED"
        or review.course_id != snapshot.course_id
        or review.confirmed_revision_id != snapshot.curriculum_revision_id
    ):
        raise GraphPublicationConflictError("Graph does not match its confirmed build request")
    snapshot = GraphSnapshot.model_validate(snapshot.model_dump())
    content = snapshot.canonical_bytes()
    if sha256(content).hexdigest() != artifact_sha256 or len(content) != artifact_bytes:
        raise GraphPublicationConflictError("Graph artifact checksum or byte count conflicts")
    validate_dag(snapshot)
    existing = await session.scalar(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.curriculum_revision_id == snapshot.curriculum_revision_id,
        CurriculumGraphVersion.version_number == snapshot.graph_version,
    ).with_for_update())
    if existing is not None:
        if existing.artifact_sha256 != artifact_sha256:
            raise GraphPublicationConflictError("Graph version checksum conflicts")
        return True
    graph_id = uuid5(
        GRAPH_JOB_NAMESPACE,
        f"published:{snapshot.curriculum_revision_id}:{snapshot.graph_version}:{artifact_sha256}",
    )
    now = datetime.now(UTC)
    graph = CurriculumGraphVersion(
        id=graph_id,
        course_id=snapshot.course_id,
        curriculum_revision_id=snapshot.curriculum_revision_id,
        build_job_id=job.id,
        version_number=snapshot.graph_version,
        status=GraphPublicationStatus.PUBLISHED.value,
        graph_source="CONFIRMED_REVISION",
        artifact_ref=artifact_ref,
        artifact_sha256=artifact_sha256,
        artifact_bytes=artifact_bytes,
        curriculum_source=(
            None if snapshot.curriculum_source is None
            else snapshot.curriculum_source.model_dump(mode="json")
        ),
        created_by_identity_id=actor_identity_id,
        created_at=now,
        published_at=now,
    )
    session.add(graph)
    await session.flush()
    _add_snapshot_rows(session, graph_id, snapshot)
    await session.flush()
    await insert_learning_event(session, LearningEventInput(
        event_id=uuid5(graph_id, "learning-event:graph-built"),
        type=LearningEventType.GRAPH_BUILT,
        actor_id=actor_identity_id,
        actor_subject=actor_subject,
        course_id=snapshot.course_id,
        occurred_at=now,
        payload=LearningEventPayload(
            kind="graph_built",
            data={
                "graph_id": str(graph_id),
                "curriculum_revision_id": str(snapshot.curriculum_revision_id),
                "graph_version": snapshot.graph_version,
                "artifact_sha256": artifact_sha256,
            },
        ),
        correlation_id=job.id,
        causation_id=job.id,
        idempotency_key=f"graph-built:{graph_id}",
    ))
    if await _owned_job(session, job) is None:
        raise GraphLeaseExpiredError("Graph build lease expired during publication")
    return True


async def _publication_domain(
    session: AsyncSession, graph: CurriculumGraphVersion,
) -> GraphPublication:
    rows = await _graph_rows(session, graph)
    snapshot = _snapshot_from_rows(graph, *rows)
    if sha256(snapshot.canonical_bytes()).hexdigest() != graph.artifact_sha256:
        raise GraphPublicationConflictError("Stored graph checksum mismatch")
    if graph.published_at is None or graph.artifact_sha256 is None:
        raise GraphPublicationConflictError("Published graph metadata is incomplete")
    return GraphPublication(
        graph_id=graph.id,
        course_id=graph.course_id,
        curriculum_revision_id=graph.curriculum_revision_id,
        parent_graph_id=graph.parent_graph_id,
        graph_version=graph.version_number,
        status=GraphPublicationStatus(graph.status),
        graph_source=graph.graph_source,
        artifact_sha256=graph.artifact_sha256,
        created_at=graph.created_at,
        published_at=graph.published_at,
        snapshot=snapshot,
    )


async def get_graph_version(
    session: AsyncSession, graph_id: UUID, course_id: UUID,
) -> GraphPublication | None:
    graph = await session.scalar(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.id == graph_id,
        CurriculumGraphVersion.course_id == course_id,
    ))
    return None if graph is None else await _publication_domain(session, graph)


async def list_graph_versions(
    session: AsyncSession, course_id: UUID, revision_id: UUID | None = None,
) -> list[GraphPublication]:
    query = select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.course_id == course_id,
    )
    if revision_id is not None:
        query = query.where(CurriculumGraphVersion.curriculum_revision_id == revision_id)
    rows = (await session.scalars(query.order_by(
        CurriculumGraphVersion.created_at, CurriculumGraphVersion.version_number,
    ))).all()
    return [await _publication_domain(session, row) for row in rows]


async def latest_graph(
    session: AsyncSession, course_id: UUID, revision_id: UUID,
) -> GraphPublication | None:
    graph = await session.scalar(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.course_id == course_id,
        CurriculumGraphVersion.curriculum_revision_id == revision_id,
        CurriculumGraphVersion.status == GraphPublicationStatus.PUBLISHED.value,
    ).order_by(CurriculumGraphVersion.version_number.desc()).limit(1))
    return None if graph is None else await _publication_domain(session, graph)


async def review_edge(
    session: AsyncSession,
    graph_id: UUID,
    edge_id: UUID,
    status: EdgeStatus,
    *,
    reviewer_identity_id: UUID,
    reviewer_subject: str,
    storage: ObjectStorage,
) -> GraphPublication:
    """Create a new immutable graph version for one explicit edge review."""

    if status not in {EdgeStatus.CONFIRMED, EdgeStatus.REJECTED}:
        raise GraphReviewConflictError("An edge review must confirm or reject")
    graph = (await session.scalars(select(CurriculumGraphVersion).where(
        CurriculumGraphVersion.id == graph_id,
    ).with_for_update())).one_or_none()
    if graph is None:
        raise GraphReviewConflictError("Graph version not found")
    new_id = uuid5(graph.id, f"edge-review:{edge_id}:{status.value}:{graph.version_number + 1}")
    existing = await session.get(CurriculumGraphVersion, new_id)
    if existing is not None:
        return await _publication_domain(session, existing)
    current = await latest_graph(session, graph.course_id, graph.curriculum_revision_id)
    if current is None or current.graph_id != graph_id:
        raise GraphReviewConflictError("Graph version is not the current reviewable version")
    rows = await _graph_rows(session, graph)
    snapshot = _snapshot_from_rows(graph, *rows)
    target = next((edge for edge in snapshot.edges if edge.edge_id == edge_id), None)
    if target is None or target.edge_type != EdgeType.PREREQUISITE_OF:
        raise GraphReviewConflictError("Prerequisite edge not found")
    if target.status != EdgeStatus.PROPOSED:
        raise GraphReviewConflictError("Only proposed prerequisite edges may be reviewed")
    changed_edges = tuple(
        target.model_copy(update={"status": status}) if edge.edge_id == edge_id else edge
        for edge in snapshot.edges
    )
    candidate = GraphSnapshot.model_validate(
        snapshot.model_dump(mode="json") | {
            "graph_version": graph.version_number + 1,
            "edges": [edge.model_dump(mode="json") for edge in changed_edges],
        }
    )
    validate_dag(candidate)
    content = candidate.canonical_bytes()
    digest = sha256(content).hexdigest()
    reference = await storage_call(
        persist_json, storage, graph_artifact_key(candidate), content, 4 * 1024 * 1024,
    )
    now = datetime.now(UTC)
    new_graph = CurriculumGraphVersion(
        id=new_id, course_id=graph.course_id,
        curriculum_revision_id=graph.curriculum_revision_id, parent_graph_id=graph.id,
        version_number=candidate.graph_version, status=GraphPublicationStatus.PUBLISHED.value,
        graph_source="EDGE_REVIEW", artifact_sha256=digest, artifact_ref=reference,
        artifact_bytes=len(content),
        curriculum_source=graph.curriculum_source,
        reviewed_by_identity_id=reviewer_identity_id, created_at=now, published_at=now,
    )
    session.add(new_graph)
    await session.flush()
    _add_snapshot_rows(
        session,
        new_id,
        candidate,
        reviewed_edge_id=edge_id,
        reviewed_by_identity_id=reviewer_identity_id,
        reviewed_at=now,
        previous_edges=rows[3],
    )
    await session.flush()
    await insert_learning_event(session, LearningEventInput(
        event_id=uuid5(new_id, "learning-event:edge-review"),
        type=(LearningEventType.PREREQUISITE_EDGE_CONFIRMED
              if status == EdgeStatus.CONFIRMED
              else LearningEventType.PREREQUISITE_EDGE_REJECTED),
        actor_id=reviewer_identity_id, actor_subject=reviewer_subject,
        course_id=graph.course_id, occurred_at=now,
        payload=LearningEventPayload(
            kind="prerequisite_edge_reviewed",
            data={"graph_id": str(new_id), "parent_graph_id": str(graph.id),
                  "edge_id": str(edge_id), "status": status.value},
        ), correlation_id=new_id, causation_id=graph.id,
        idempotency_key=f"edge-review:{new_id}",
    ))
    return await _publication_domain(session, new_graph)
