from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
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
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "error": str(e)},
        )
