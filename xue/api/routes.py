"""FastAPI routes for Xue crawler management."""

from fastapi import APIRouter

from xue import VERSION

router = APIRouter(prefix="/api/v1", tags=["crawls"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": VERSION}
