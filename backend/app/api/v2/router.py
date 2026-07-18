"""Root v2 API router registration."""

from fastapi import APIRouter

from app.api.v2 import (
    adaptive,
    analytics,
    auth,
    dashboard,
    jobs,
    knowledge_graph,
    learning,
    lessons,
    quiz,
    retrieval,
    session,
)

router = APIRouter(prefix="/api/v2")
router.include_router(auth.router)
router.include_router(knowledge_graph.router)
router.include_router(learning.router)
router.include_router(lessons.router)
router.include_router(quiz.router)
router.include_router(retrieval.router)
router.include_router(session.router)
router.include_router(dashboard.router)
router.include_router(analytics.router)
router.include_router(adaptive.router)
router.include_router(jobs.router)
