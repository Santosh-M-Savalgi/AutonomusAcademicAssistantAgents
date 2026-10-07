"""Pure internal identity and learner-authorization contracts."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from packages.domain.models import DomainModel


class StudentIdentity(DomainModel):
    """Stable internal identity mapped from one external authenticated subject.

    The identity is role-neutral. The table is used for both actors and
    learners; authorization remains a separate decision and is never inferred
    from the existence of this mapping.
    """

    id: UUID
    provider_namespace: str = Field(min_length=1, max_length=255)
    external_subject: str = Field(min_length=1, max_length=255)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def require_timezone_aware_timestamps(self) -> Self:
        for value in (self.created_at, self.updated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Identity timestamps must be timezone-aware")
        return self


class LearnerAuthorizationError(PermissionError):
    """Raised when an actor attempts to access another learner implicitly."""


def require_learner_access(
    actor_id: UUID,
    learner_id: UUID,
    *,
    explicitly_authorized: bool = False,
) -> None:
    """Allow self-access or a separately verified delegated operation.

    ``explicitly_authorized`` is intended for a caller that has already
    checked a future delegation/role policy. Course membership alone must not
    be used to set it.
    """

    if actor_id != learner_id and not explicitly_authorized:
        raise LearnerAuthorizationError("Actor is not authorized for this learner")
