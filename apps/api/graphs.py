"""Authenticated graph publication and explicit edge-review endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth.dependencies import get_current_identity, get_current_student_identity
from apps.api.auth.schemas import AuthenticatedIdentity
from apps.api.curriculum import _review_storage, require_membership
from apps.api.runtime import RuntimeResources
from packages.domain.graph import EdgeStatus
from packages.domain.graph_publication import GraphPublication
from packages.domain.identity import StudentIdentity
from packages.persistence.graphs import (
    get_graph_version,
    latest_graph,
    list_graph_versions,
    review_edge,
)

router = APIRouter(prefix="/api/v3", tags=["learning-graphs"])


async def _member(request: Request, course_id: UUID, identity: AuthenticatedIdentity) -> None:
    await require_membership(request.app.state.runtime, course_id, identity.subject)


async def _graph_or_404(
    request: Request, course_id: UUID, graph_id: UUID,
) -> GraphPublication:
    resources: RuntimeResources = request.app.state.runtime
    async with resources.database.session() as session:
        graph = await get_graph_version(session, graph_id, course_id)
    if graph is None:
        raise HTTPException(status_code=404, detail={
            "code": "GRAPH_NOT_FOUND", "message": "No graph version exists.",
        })
    return graph


@router.get("/courses/{course_id}/graph", response_model=GraphPublication)
async def read_latest_graph(
    course_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> GraphPublication:
    await _member(request, course_id, identity)
    resources: RuntimeResources = request.app.state.runtime
    async with resources.database.session() as session:
        graphs = await list_graph_versions(session, course_id)
    if not graphs:
        raise HTTPException(status_code=404, detail={
            "code": "GRAPH_NOT_FOUND", "message": "No published graph exists.",
        })
    return graphs[-1]


@router.get("/courses/{course_id}/graph/versions", response_model=list[GraphPublication])
async def read_graph_history(
    course_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    curriculum_revision_id: UUID | None = None,
) -> list[GraphPublication]:
    await _member(request, course_id, identity)
    resources: RuntimeResources = request.app.state.runtime
    async with resources.database.session() as session:
        return await list_graph_versions(session, course_id, curriculum_revision_id)


@router.get(
    "/courses/{course_id}/curriculum/{curriculum_revision_id}/graph",
    response_model=GraphPublication,
)
async def read_revision_graph(
    course_id: UUID,
    curriculum_revision_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
) -> GraphPublication:
    await _member(request, course_id, identity)
    resources: RuntimeResources = request.app.state.runtime
    async with resources.database.session() as session:
        graph = await latest_graph(session, course_id, curriculum_revision_id)
    if graph is None:
        raise HTTPException(status_code=404, detail={
            "code": "GRAPH_NOT_FOUND", "message": "No graph exists for this revision.",
        })
    return graph


async def _review_edge(
    request: Request,
    course_id: UUID,
    graph_id: UUID,
    edge_id: UUID,
    status: EdgeStatus,
    identity: AuthenticatedIdentity,
    student: StudentIdentity,
) -> GraphPublication:
    await _member(request, course_id, identity)
    resources: RuntimeResources = request.app.state.runtime
    storage = await _review_storage(request)
    try:
        async with resources.database.session() as session, session.begin():
            graph = await get_graph_version(session, graph_id, course_id)
            if graph is None:
                raise HTTPException(status_code=404, detail={
                    "code": "GRAPH_NOT_FOUND", "message": "No graph version exists.",
                })
            return await review_edge(
                session, graph_id, edge_id, status,
                reviewer_identity_id=student.id,
                reviewer_subject=identity.subject,
                storage=storage,
            )
    except ValueError as error:
        raise HTTPException(status_code=409, detail={
            "code": "GRAPH_EDGE_REVIEW_CONFLICT", "message": str(error),
        }) from error
    finally:
        await storage.close()


@router.post(
    "/courses/{course_id}/graphs/{graph_id}/edges/{edge_id}/confirm",
    response_model=GraphPublication,
)
async def confirm_graph_edge(
    course_id: UUID,
    graph_id: UUID,
    edge_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    student: Annotated[StudentIdentity, Depends(get_current_student_identity)],
) -> GraphPublication:
    return await _review_edge(
        request, course_id, graph_id, edge_id, EdgeStatus.CONFIRMED, identity, student,
    )


@router.post(
    "/courses/{course_id}/graphs/{graph_id}/edges/{edge_id}/reject",
    response_model=GraphPublication,
)
async def reject_graph_edge(
    course_id: UUID,
    graph_id: UUID,
    edge_id: UUID,
    request: Request,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_identity)],
    student: Annotated[StudentIdentity, Depends(get_current_student_identity)],
) -> GraphPublication:
    return await _review_edge(
        request, course_id, graph_id, edge_id, EdgeStatus.REJECTED, identity, student,
    )
