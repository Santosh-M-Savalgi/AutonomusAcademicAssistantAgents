"""Disposable PostgreSQL/MinIO review, edit, OCC and confirmation lifecycle."""

import asyncio
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from apps.api.auth.dependencies import identity_provider_namespace
from apps.worker.config import WorkerSettings
from apps.worker.extraction_config import ExtractionSettings
from apps.worker.runner import Worker
from apps.worker.syllabus import create_handler_registry
from packages.curriculum.graph import graph_from_confirmed_revision
from packages.domain.enums import JobStatus, LearningEventType
from packages.domain.extraction import NodeType
from packages.domain.graph import (
    Concept,
    EdgeSource,
    EdgeStatus,
    EdgeType,
    GraphEdge,
    GraphSource,
    MappingKind,
    TopicConceptMapping,
)
from packages.domain.jobs import JobEventType
from packages.domain.review import review_identity
from packages.persistence import review as review_service
from packages.persistence.artifacts import persist_json
from packages.persistence.graphs import (
    graph_artifact_key,
    graph_build_job_identity,
    publish_graph_for_job,
)
from packages.persistence.identities import stable_identity_id
from packages.persistence.job_events import events_after
from packages.persistence.jobs import JobRepository
from packages.persistence.learning_events import list_learning_events
from packages.persistence.models import (
    Course,
    CourseMember,
    CurriculumReview,
    CurriculumRevision,
    DocumentVersion,
    Job,
)
from packages.persistence.worker_storage import storage_call
from tests.pdf_fixtures import syllabus_pdf

pytestmark = pytest.mark.live_integration


@pytest.fixture
async def review_pipeline(migrate_database, live_database, live_object_storage, minio_bucket,
                           async_http_client, auth_headers, service_settings):
    await asyncio.to_thread(migrate_database)
    course_id = uuid4()
    async with live_database.session() as session, session.begin():
        session.add(Course(id=course_id, title="Review lifecycle course"))
        session.add(CourseMember(course_id=course_id, subject="fixture-student", role="student"))
    pdf = syllabus_pdf(["Module I: Foundations\nUnit 1: Algebra\n1.1 Functions\nBody"])
    response = await async_http_client.post(
        f"/api/v3/courses/{course_id}/syllabus", headers=auth_headers,
        files={"upload": ("review.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 202, response.text
    extraction_id = UUID(response.json()["job_id"])
    async with live_database.session() as session:
        version = (await session.scalars(select(DocumentVersion).where(
            DocumentVersion.document_id == UUID(response.json()["document_id"]),
        ))).one()
    config = WorkerSettings(_env_file=None, concurrency=1, lease_seconds=30,
                            heartbeat_seconds=1, io_timeout_seconds=1, poll_seconds=0.05,
                            reaper_seconds=1, shutdown_grace_seconds=0.05)
    yield SimpleNamespace(
        database=live_database, storage=live_object_storage, settings=service_settings,
        client=async_http_client, auth_headers=auth_headers, course_id=course_id,
        extraction_id=extraction_id, version=version, pdf=pdf, config=config,
        repository=JobRepository(live_database, retry_base=0.01, retry_max=0.04),
    )


async def process_pipeline(pipeline):
    registry = create_handler_registry(pipeline.database, pipeline.settings,
                                       ExtractionSettings(_env_file=None))
    worker = Worker(pipeline.repository, registry, pipeline.config)
    extraction = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)
    assert extraction is not None
    await worker.execute(extraction)
    async with pipeline.database.session() as session:
        extraction_row = await session.get(Job, pipeline.extraction_id)
        draft_row = (await session.scalars(select(Job).where(
            Job.parent_job_id == pipeline.extraction_id, Job.job_type == "curriculum_draft",
        ))).one()
    assert extraction_row.status == "SUCCEEDED"
    draft = await pipeline.repository.claim(worker.worker_id, pipeline.config.lanes, 30)
    assert draft is not None and draft.id == draft_row.id
    await worker.execute(draft)
    async with pipeline.database.session() as session:
        completed = await session.get(Job, draft_row.id)
    return draft_row.id, completed.result_ref


async def test_review_edit_confirm_and_original_artifact_immutability(review_pipeline):
    draft_id, original_ref = await process_pipeline(review_pipeline)
    original_prefix = f"minio://{review_pipeline.storage.bucket}/"

    def read(ref):
        response = review_pipeline.storage.client.get_object(
            review_pipeline.storage.bucket, ref.removeprefix(original_prefix),
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    original_bytes = await asyncio.to_thread(read, original_ref)
    start = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert start.status_code == 200, start.text
    review = start.json()["review"]
    assert review["status"] == "UNDER_REVIEW" and review["revision_number"] == 1
    elements = start.json()["revision"]["elements"]
    elements[0]["title"] = "Reviewed foundations"
    elements.append({
        "id": str(uuid4()), "key": "human-note", "type": "TOPIC",
        "title": "Exam review", "parent_id": None, "order": len(elements) + 1,
        "source_node_id": None, "sources": [], "origin": "HUMAN",
        "parse_confidence": 0, "learning_outcomes": ["Review exam skills"],
    })
    saved = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1, "elements": elements},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["review"]["revision_number"] == 2
    duplicate = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1, "elements": elements},
    )
    assert duplicate.status_code == 200
    stale_elements = [dict(element) for element in elements]
    stale_elements[0]["title"] = "Competing edit"
    stale = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1, "elements": stale_elements},
    )
    assert stale.status_code == 409
    confirmed = await review_pipeline.client.post(
        f"/api/v3/curriculum/{draft_id}/confirm",
        headers=review_pipeline.auth_headers, json={"expected_revision": 2},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["review"]["status"] == "CONFIRMED"
    assert confirmed.json()["review"]["confirmed_by"] == "fixture-student"
    repeat = await review_pipeline.client.post(
        f"/api/v3/curriculum/{draft_id}/confirm",
        headers=review_pipeline.auth_headers, json={"expected_revision": 2},
    )
    assert repeat.status_code == 200
    blocked = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 2, "elements": elements},
    )
    assert blocked.status_code == 409
    read_confirmed = await review_pipeline.client.get(
        f"/api/v3/curriculum/{draft_id}/confirmed", headers=review_pipeline.auth_headers,
    )
    assert read_confirmed.status_code == 200
    assert read_confirmed.json()["revision"]["elements"][0]["title"] == "Reviewed foundations"
    assert await asyncio.to_thread(read, original_ref) == original_bytes


async def test_confirmation_builds_and_publishes_an_immutable_graph(review_pipeline):
    draft_id, _ = await process_pipeline(review_pipeline)
    started = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert started.status_code == 200, started.text
    confirmed = await review_pipeline.client.post(
        f"/api/v3/curriculum/{draft_id}/confirm",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 200, confirmed.text
    payload = confirmed.json()
    graph_job_id = UUID(payload["graph_job_id"])
    assert graph_job_id == graph_build_job_identity(
        UUID(payload["review"]["id"]), UUID(payload["revision"]["id"]),
    )

    registry = create_handler_registry(
        review_pipeline.database, review_pipeline.settings, ExtractionSettings(_env_file=None),
    )
    worker = Worker(review_pipeline.repository, registry, review_pipeline.config)
    graph_job = await review_pipeline.repository.claim(
        worker.worker_id, review_pipeline.config.lanes, 30,
    )
    assert graph_job is not None and graph_job.id == graph_job_id
    await worker.execute(graph_job)

    async with review_pipeline.database.session() as session:
        stored_job = await session.get(Job, graph_job_id)
        events = await list_learning_events(session, course_id=review_pipeline.course_id)
    assert stored_job is not None and stored_job.status == "SUCCEEDED"
    assert {event.event_type for event in events} >= {
        LearningEventType.CURRICULUM_CONFIRMED.value,
        LearningEventType.GRAPH_BUILT.value,
    }

    graph = await review_pipeline.client.get(
        f"/api/v3/courses/{review_pipeline.course_id}/graph",
        headers=review_pipeline.auth_headers,
    )
    assert graph.status_code == 200, graph.text
    graph_body = graph.json()
    assert graph_body["status"] == "PUBLISHED"
    assert graph_body["graph_version"] == 1
    assert graph_body["snapshot"]["curriculum_revision_id"] == payload["revision"]["id"]
    assert "artifact_ref" not in graph_body

    history = await review_pipeline.client.get(
        f"/api/v3/courses/{review_pipeline.course_id}/graph/versions",
        headers=review_pipeline.auth_headers,
    )
    assert history.status_code == 200
    assert [item["graph_version"] for item in history.json()] == [1]


async def test_edge_review_creates_a_new_artifact_backed_graph_version(review_pipeline):
    draft_id, _ = await process_pipeline(review_pipeline)
    started = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert started.status_code == 200, started.text
    elements = started.json()["revision"]["elements"]
    elements.append({
        "id": str(uuid4()), "key": "second-topic", "type": "TOPIC",
        "title": "Second topic", "parent_id": None, "order": len(elements) + 1,
        "source_node_id": None, "sources": [], "origin": "HUMAN",
        "parse_confidence": 0, "learning_outcomes": [],
    })
    saved = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1, "elements": elements},
    )
    assert saved.status_code == 200, saved.text
    confirmed = await review_pipeline.client.post(
        f"/api/v3/curriculum/{draft_id}/confirm",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 2},
    )
    assert confirmed.status_code == 200, confirmed.text

    graph_job_id = UUID(confirmed.json()["graph_job_id"])
    registry = create_handler_registry(
        review_pipeline.database, review_pipeline.settings, ExtractionSettings(_env_file=None),
    )
    worker = Worker(review_pipeline.repository, registry, review_pipeline.config)
    graph_job = await review_pipeline.repository.claim(
        worker.worker_id, review_pipeline.config.lanes, 30,
    )
    assert graph_job is not None and graph_job.id == graph_job_id
    review, revision = await review_service.get_review(
        review_pipeline.database, review_pipeline.storage,
        UUID(confirmed.json()["review"]["id"]),
    )
    topics = [element for element in revision.elements if element.type == NodeType.TOPIC]
    assert len(topics) >= 2
    concepts = tuple(
        Concept(
            id=uuid4(), key=f"explicit-{index}", title=element.title,
            source=GraphSource.USER_DEFINED, confidence=1.0, verified=True,
            derived_from_topic_id=element.id,
        )
        for index, element in enumerate(topics[:2], 1)
    )
    mappings = tuple(
        TopicConceptMapping(
            mapping_id=uuid4(), topic_id=element.id, concept_id=concept.id,
            mapping_kind=MappingKind.EXPLICIT, source=GraphSource.USER_DEFINED,
            confidence=1.0, verified=True,
        )
        for element, concept in zip(topics[:2], concepts, strict=True)
    )
    edge = GraphEdge(
        edge_id=uuid4(), edge_type=EdgeType.PREREQUISITE_OF,
        source_node_id=concepts[0].id, target_node_id=concepts[1].id,
        source=EdgeSource.LLM_PROPOSED, confidence=0.8, status=EdgeStatus.PROPOSED,
    )
    snapshot = graph_from_confirmed_revision(
        review, revision, concepts=concepts, mappings=mappings, edges=(edge,),
    )
    content = snapshot.canonical_bytes()
    artifact_ref = await storage_call(
        persist_json, review_pipeline.storage, graph_artifact_key(snapshot), content,
        4 * 1024 * 1024,
    )
    actor_id = stable_identity_id(
        identity_provider_namespace(review_pipeline.settings), "fixture-student",
    )
    async with review_pipeline.database.session() as session, session.begin():
        assert await publish_graph_for_job(
            session, graph_job, snapshot, artifact_ref=artifact_ref,
            artifact_sha256=sha256(content).hexdigest(), artifact_bytes=len(content),
            actor_identity_id=actor_id, actor_subject="fixture-student",
        )
    assert await review_pipeline.repository.finish(
        graph_job, JobStatus.SUCCEEDED, result_ref=artifact_ref,
    )

    graph = await review_pipeline.client.get(
        f"/api/v3/courses/{review_pipeline.course_id}/graph",
        headers=review_pipeline.auth_headers,
    )
    assert graph.status_code == 200, graph.text
    graph_id = UUID(graph.json()["graph_id"])
    edge_id = UUID(str(edge.edge_id))
    reviewed = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/graphs/{graph_id}/edges/{edge_id}/confirm",
        headers=review_pipeline.auth_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["graph_version"] == 2
    assert reviewed.json()["snapshot"]["edges"][0]["status"] == EdgeStatus.CONFIRMED.value
    assert reviewed.json()["artifact_sha256"] != graph.json()["artifact_sha256"]

    repeated = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/graphs/{graph_id}/edges/{edge_id}/confirm",
        headers=review_pipeline.auth_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["graph_id"] == reviewed.json()["graph_id"]


async def test_extraction_and_draft_handlers_emit_durable_progress(review_pipeline):
    draft_id, _ = await process_pipeline(review_pipeline)
    extraction_events = await events_after(
        review_pipeline.database, review_pipeline.extraction_id, 0,
    )
    draft_events = await events_after(review_pipeline.database, draft_id, 0)
    assert JobEventType.CREATED in [event.type for event in extraction_events]
    assert JobEventType.STARTED in [event.type for event in extraction_events]
    assert any(
        event.type == JobEventType.STAGE_STARTED
        and event.payload["stage"] == "extraction"
        for event in extraction_events
    )
    assert any(
        event.type == JobEventType.PROGRESS_UPDATED
        and event.payload["stage"] == "enqueueing_draft"
        for event in extraction_events
    )
    assert any(
        event.type == JobEventType.STAGE_STARTED
        and event.payload["stage"] == "generating_curriculum"
        for event in draft_events
    )
    assert draft_events[-1].type == JobEventType.COMPLETED


async def test_review_requires_membership_and_draft_completion(review_pipeline):
    missing = await review_pipeline.client.get(
        f"/api/v3/curriculum/{uuid4()}/review", headers=review_pipeline.auth_headers,
    )
    assert missing.status_code == 404
    response = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{uuid4()}/review",
        headers=review_pipeline.auth_headers,
    )
    assert response.status_code == 404


async def test_cross_course_review_access_is_rejected(review_pipeline):
    draft_id, _ = await process_pipeline(review_pipeline)
    other_course = uuid4()
    async with review_pipeline.database.session() as session, session.begin():
        session.add(Course(id=other_course, title="Other course"))
    response = await review_pipeline.client.post(
        f"/api/v3/courses/{other_course}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert response.status_code == 403


async def test_revision_history_is_recoverable(review_pipeline):
    draft_id, _ = await process_pipeline(review_pipeline)
    start = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert start.status_code == 200
    history = await review_pipeline.client.get(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
    )
    assert history.status_code == 200
    assert [item["revision_number"] for item in history.json()] == [1]


async def test_concurrent_review_starts_return_the_persisted_winner(review_pipeline, monkeypatch):
    draft_id, _ = await process_pipeline(review_pipeline)
    barrier = asyncio.Barrier(2)
    storage_call = review_service.storage_call

    async def synchronized_write(function, *args, **kwargs):
        result = await storage_call(function, *args, **kwargs)
        if function is review_service.persist_json:
            # Both requests have observed that no review exists before either commits.
            await asyncio.wait_for(barrier.wait(), 5)
        return result

    monkeypatch.setattr(review_service, "storage_call", synchronized_write)
    results = await asyncio.gather(*(
        review_service.begin_review(review_pipeline.database, review_pipeline.storage,
                                    draft_id, actor)
        for actor in ("reviewer-one", "reviewer-two")
    ), return_exceptions=True)
    assert all(isinstance(result, tuple) for result in results), results
    assert results[0] == results[1]
    stored = await review_service.get_review(
        review_pipeline.database, review_pipeline.storage, review_identity(draft_id),
    )
    assert results[0] == stored
    async with review_pipeline.database.session() as session:
        assert len((await session.scalars(select(CurriculumReview))).all()) == 1
        assert len((await session.scalars(select(CurriculumRevision))).all()) == 1


async def test_delayed_review_start_returns_current_committed_revision(
    review_pipeline, monkeypatch,
):
    draft_id, _ = await process_pipeline(review_pipeline)
    paused, resume = asyncio.Event(), asyncio.Event()
    storage_call = review_service.storage_call

    async def delayed_write(function, *args, **kwargs):
        result = await storage_call(function, *args, **kwargs)
        if function is review_service.persist_json and not paused.is_set():
            paused.set()
            await asyncio.wait_for(resume.wait(), 10)
        return result

    monkeypatch.setattr(review_service, "storage_call", delayed_write)
    delayed = asyncio.create_task(review_service.begin_review(
        review_pipeline.database, review_pipeline.storage, draft_id, "delayed-reviewer",
    ))
    try:
        await asyncio.wait_for(paused.wait(), 5)
        review, revision = await review_service.begin_review(
            review_pipeline.database, review_pipeline.storage, draft_id, "winning-reviewer",
        )
        elements = [item.model_copy(deep=True) for item in revision.elements]
        elements[0].title = "Edit committed before delayed start resumes"
        saved = await review_service.save_revision(
            review_pipeline.database, review_pipeline.storage, review.id, 1,
            elements, "winning-reviewer",
        )
    finally:
        resume.set()
        result = await delayed
    assert result == saved
    assert result[0].revision_number == result[1].revision_number == 2


async def test_concurrent_confirmation_is_idempotent(review_pipeline, monkeypatch):
    draft_id, _ = await process_pipeline(review_pipeline)
    review, _ = await review_service.begin_review(
        review_pipeline.database, review_pipeline.storage, draft_id, "reviewer",
    )
    barrier = asyncio.Barrier(2)
    load_revision = review_service._load_revision

    async def synchronized_load(*args):
        revision = await load_revision(*args)
        await asyncio.wait_for(barrier.wait(), 5)
        return revision

    with monkeypatch.context() as patch:
        patch.setattr(review_service, "_load_revision", synchronized_load)
        results = await asyncio.gather(*(
            review_service.confirm_review(review_pipeline.database, review_pipeline.storage,
                                          review.id, 1, actor)
            for actor in ("reviewer-one", "reviewer-two")
        ), return_exceptions=True)
    assert not any(isinstance(result, Exception) for result in results), results
    assert results[0] == results[1]
    async with review_pipeline.database.session() as session:
        stored = await session.get(CurriculumReview, review.id)
        confirmed_at = stored.confirmed_at
        assert stored.confirmed_by == results[0].confirmed_by
    repeated = await review_service.confirm_review(
        review_pipeline.database, review_pipeline.storage, review.id, 1, "another-reviewer",
    )
    assert repeated == results[0]
    async with review_pipeline.database.session() as session:
        stored = await session.get(CurriculumReview, review.id)
        assert stored.confirmed_at == confirmed_at


@pytest.mark.parametrize("invalid_edit", ["human-relabel", "source-range", "hierarchy"])
async def test_invalid_edit_returns_422_without_persisting(review_pipeline, invalid_edit):
    draft_id, _ = await process_pipeline(review_pipeline)
    start = await review_pipeline.client.post(
        f"/api/v3/courses/{review_pipeline.course_id}/curriculum/drafts/{draft_id}/review",
        headers=review_pipeline.auth_headers,
    )
    assert start.status_code == 200
    elements = start.json()["revision"]["elements"]
    if invalid_edit == "human-relabel":
        elements[0].update(origin="HUMAN", source_node_id=None, sources=[])
    elif invalid_edit == "source-range":
        elements[0]["sources"] = []
    else:
        elements[0]["parent_id"] = elements[-1]["id"]
    response = await review_pipeline.client.put(
        f"/api/v3/curriculum/{draft_id}/review/revisions",
        headers=review_pipeline.auth_headers,
        json={"expected_revision": 1, "elements": elements},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] in {"INVALID_REVISION", "INVALID_PROVENANCE"}
    current = await review_pipeline.client.get(
        f"/api/v3/curriculum/{draft_id}/review", headers=review_pipeline.auth_headers,
    )
    assert current.json() == start.json()
    history = await review_service.list_revisions(
        review_pipeline.database, review_pipeline.storage, review_identity(draft_id),
    )
    assert len(history) == 1
