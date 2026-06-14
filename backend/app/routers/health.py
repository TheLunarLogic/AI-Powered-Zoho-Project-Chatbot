"""Health check endpoint."""

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    return JSONResponse(
        content={
            "status": "ok",
            "version": "1.0.0",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
