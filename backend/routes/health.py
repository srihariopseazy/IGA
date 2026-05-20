from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    health = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    # Check Database
    try:
        await db.execute(text("SELECT 1"))
        health["checks"]["database"] = {"status": "healthy"}
    except Exception as e:
        health["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"

    # Check Redis
    try:
        from backend.utils.redis_client import redis_client

        await redis_client.set("health_check", "ok", expire=10)
        val = await redis_client.get("health_check")
        if val == "ok":
            health["checks"]["redis"] = {"status": "healthy"}
        else:
            health["checks"]["redis"] = {"status": "unhealthy", "error": "Unexpected value"}
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"

    # Check RabbitMQ
    try:
        import aio_pika

        connection = await aio_pika.connect_robust(
            settings.RABBITMQ_URL,
            timeout=5,
        )
        await connection.close()
        health["checks"]["rabbitmq"] = {"status": "healthy"}
    except Exception as e:
        health["checks"]["rabbitmq"] = {"status": "unhealthy", "error": str(e)}
        if health["status"] == "healthy":
            health["status"] = "degraded"

    # Check MinIO
    try:
        from minio import Minio

        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        # List buckets as a connectivity check
        buckets = client.list_buckets()
        health["checks"]["minio"] = {"status": "healthy", "buckets": len(list(buckets))}
    except Exception as e:
        health["checks"]["minio"] = {"status": "unhealthy", "error": str(e)}
        if health["status"] == "healthy":
            health["status"] = "degraded"

    status_code = 200 if health["status"] == "healthy" else 503
    return JSONResponse(content=health, status_code=status_code)


@router.get("/health/ready")
async def readiness_probe(db: AsyncSession = Depends(get_db)):
    """
    Kubernetes readiness probe.
    Returns 200 when the application is ready to serve traffic (DB accessible),
    503 otherwise.
    """
    try:
        await db.execute(text("SELECT 1"))
        return JSONResponse(
            content={
                "status": "ready",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            content={
                "status": "not_ready",
                "reason": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            status_code=503,
        )


@router.get("/health/live")
async def liveness_probe():
    """
    Kubernetes liveness probe.
    Always returns 200 as long as the process is alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
