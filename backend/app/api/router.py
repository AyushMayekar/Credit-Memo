from fastapi import APIRouter
from app.api.routes import (
    applications,
    documents,
    jobs,
    review,
    ai,
    memos,
    extraction_review,
)

api_router = APIRouter(prefix="/api/v1")
for router in (
    applications.router,
    documents.router,
    jobs.router,
    review.router,
    ai.router,
    memos.router,
    extraction_review.router,
):
    api_router.include_router(router)
