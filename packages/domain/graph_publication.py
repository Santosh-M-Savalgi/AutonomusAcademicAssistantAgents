"""Timestamped publication metadata, separate from the pure graph contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.graph import GraphModel, GraphPublicationStatus, GraphSnapshot


class GraphPublication(GraphModel):
    """Safe graph publication response without object-storage references."""

    graph_id: UUID
    course_id: UUID
    curriculum_revision_id: UUID
    parent_graph_id: UUID | None = None
    graph_version: int = Field(ge=1)
    status: GraphPublicationStatus
    graph_source: str = Field(min_length=1, max_length=64)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    published_at: datetime
    snapshot: GraphSnapshot
