"""Health check endpoints."""
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/ready")
async def ready():
    """Readiness check endpoint."""
    return {"status": "ready"}
