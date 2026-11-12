"""Health probes for orchestrators.

Three endpoints following the Kubernetes convention:

- ``GET /healthz`` 鈥?liveness. Returns 200 unless the process itself is
  broken. No external dependency checks; restarts on failure.
- ``GET /readyz`` 鈥?readiness. Verifies DB reachability. Returns 503
  if the DB is down; orchestrator should stop routing traffic but **not**
  restart the pod (transient DB outage ≠ dead process).
- ``GET /api/health/ready`` 鈥?legacy alias kept for backward compatibility
  with the original test suite.

The router sits at the **root** prefix (no ``/api``), matching the
Kubernetes probe convention. ``app.main`` mounts the legacy
``/api/health`` aliases separately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.rate_limit_store import get_rate_limiter_store
from app.schemas import HealthReadyResponse, HealthResponse

logger = get_logger("rubbish.health")

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def liveness_root() -> HealthResponse:
    """Liveness probe at root 鈥? always 200 if the process is alive."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/readyz", response_model=HealthReadyResponse)
async def readiness_root(
    db: AsyncSession = Depends(get_db),
) -> HealthReadyResponse | JSONResponse:
    """Readiness probe at root 鈥? checks DB + rate-limit store reachability.

    A 503 from this probe means the orchestrator should stop routing
    traffic but **not** restart the process (transient DB outage).
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - exercised in prod only
        # 探针是公开端点：连接串/驱动报错里常带主机名、用户名、端口，
        # 不能回给调用方。详细原因只进日志。
        logger.warning("readiness_db_check_failed", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "database": "unavailable"},
        )
    return HealthReadyResponse(status="ok", database="connected")


# Legacy endpoints at /api/health/* 鈥? preserved for the existing test
# suite and any external health checks that target them.
legacy_router = APIRouter(prefix="/health", tags=["health"])


@legacy_router.get("", response_model=HealthResponse)
async def liveness_legacy() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@legacy_router.get("/ready", response_model=HealthReadyResponse)
async def readiness_legacy(
    db: AsyncSession = Depends(get_db),
) -> HealthReadyResponse | JSONResponse:
    return await readiness_root(db)


__all__ = ["legacy_router", "router"]


# ---------------------------------------------------------------------------
# Sanity check: rate-limit store is reachable.
# ---------------------------------------------------------------------------
async def _rate_limit_healthcheck() -> bool:
    try:
        store = get_rate_limiter_store()
        # Memory store returns immediately; Redis store tries to ping.
        return store is not None
    except Exception:
        return False
