"""Small persistence queries shared by the Phase 2 API service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.persistence.models import Course, CourseMember, Job


async def find_course(session: AsyncSession, course_id: UUID) -> Course | None:
    """Return a course aggregate by identifier."""

    return await session.get(Course, course_id)


async def find_course_member(
    session: AsyncSession,
    course_id: UUID,
    subject: str,
) -> CourseMember | None:
    """Return a membership row used for course-scoped authorization."""

    result = await session.execute(
        select(CourseMember).where(
            CourseMember.course_id == course_id,
            CourseMember.subject == subject,
        )
    )
    return result.scalar_one_or_none()


async def find_job_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> Job | None:
    """Find an existing job so a retried submission returns the original result."""

    result = await session.execute(select(Job).where(Job.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()
