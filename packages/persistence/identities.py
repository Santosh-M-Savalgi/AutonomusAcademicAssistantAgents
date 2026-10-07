"""Caller-owned transactions for external-subject identity resolution."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.identity import StudentIdentity
from packages.persistence.models import StudentIdentity as StudentIdentityRow


class IdentityResolutionError(ValueError):
    """Raised for invalid external identity inputs or inconsistent storage."""


def stable_identity_id(provider_namespace: str, external_subject: str) -> UUID:
    """Derive a stable internal UUID without treating the subject as a UUID."""

    if not provider_namespace or len(provider_namespace) > 255:
        raise IdentityResolutionError("Invalid identity-provider namespace")
    if not external_subject or len(external_subject) > 255:
        raise IdentityResolutionError("Invalid external subject")
    return uuid5(
        NAMESPACE_URL,
        f"aaa-v3:student-identity:v1:{provider_namespace}:{external_subject}",
    )


def _domain_identity(row: StudentIdentityRow) -> StudentIdentity:
    return StudentIdentity(
        id=row.id,
        provider_namespace=row.provider_namespace,
        external_subject=row.external_subject,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def resolve_student_identity(
    session: AsyncSession,
    provider_namespace: str,
    external_subject: str,
) -> StudentIdentity:
    """Resolve or create an identity without committing the caller's transaction."""

    identity_id = stable_identity_id(provider_namespace, external_subject)
    await session.execute(
        insert(StudentIdentityRow)
        .values(
            id=identity_id,
            provider_namespace=provider_namespace,
            external_subject=external_subject,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(
            index_elements=[
                StudentIdentityRow.provider_namespace,
                StudentIdentityRow.external_subject,
            ]
        )
    )
    row = await session.scalar(
        select(StudentIdentityRow).where(
            StudentIdentityRow.provider_namespace == provider_namespace,
            StudentIdentityRow.external_subject == external_subject,
        )
    )
    if row is None:
        raise IdentityResolutionError("Identity row was not available after resolution")
    return _domain_identity(row)


async def get_student_identity(
    session: AsyncSession, identity_id: UUID,
) -> StudentIdentity | None:
    """Load an internal identity by UUID for authorized server-side use."""

    row = await session.get(StudentIdentityRow, identity_id)
    return None if row is None else _domain_identity(row)
