from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db

router = APIRouter(tags=["Health & System"])


@router.get("/health")
async def health_check():
    """Liveness probe returning 200 OK if API service is running."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness probe checking database and Redis connectivity."""
    checks = {"database": False, "redis": False}

    # Check PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"

    # Check Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)}"

    all_ready = checks["database"] is True and checks["redis"] is True
    status_code = status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ready else "not_ready",
            "components": checks,
        },
    )
