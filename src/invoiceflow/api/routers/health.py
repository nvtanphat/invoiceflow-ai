from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
import psutil
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import get_db

router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def liveness():
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_db)):
    try:
        await session.execute(text("SELECT 1"))
        vm = psutil.virtual_memory()
        is_memory_ok = vm.available >= 100 * 1024 * 1024  # At least 100MB free
        if not is_memory_ok:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "degraded",
                    "database": "connected",
                    "error": "Low available system memory",
                },
            )
        return {"status": "ready", "database": "connected", "memory": "ok"}
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "error": str(e)},
        )


@router.get("/health/metrics")
async def metrics(session: AsyncSession = Depends(get_db)):
    vm = psutil.virtual_memory()
    return {
        "status": "healthy",
        "memory": {
            "total_mb": round(vm.total / (1024 * 1024), 2),
            "available_mb": round(vm.available / (1024 * 1024), 2),
            "percent_used": vm.percent,
        },
    }
