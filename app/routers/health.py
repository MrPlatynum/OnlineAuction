"""Liveness / readiness probe.

Returns 200 with ``{"status": "ok", "db": "ok"}`` when the app and its
Postgres dependency are both reachable, 503 when the DB ping fails.
Designed for load-balancer / Kubernetes ``readinessProbe`` checks —
plain liveness probes can hit the same path and just look at the HTTP
code.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as exc:
        response.status_code = 503
        return {"status": "degraded", "db": "fail", "detail": str(exc)}
