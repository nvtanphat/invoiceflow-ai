from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.api.dependencies import AuthenticatedContext, get_current_context, get_db
from invoiceflow.application.reporting.processing_summary import processing_summary

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/processing-summary")
async def get_processing_summary(
    days: int = Query(14, ge=1, le=90),
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    return await processing_summary(
        session, ctx.tenant_id, days=days, today=datetime.now(timezone.utc).date()
    )
