from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_current_context, get_db
from invoiceflow.infrastructure.database.models import ProcessingJobORM

router = APIRouter(prefix="/jobs", tags=["Processing Jobs"])


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(ProcessingJobORM).where(
        ProcessingJobORM.tenant_id == ctx.tenant_id,
        ProcessingJobORM.id == job_id,
    )
    res = await session.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    return {
        "id": job.id,
        "document_id": job.document_id,
        "status": job.status,
        "stage": job.stage,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.get("")
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ProcessingJobORM)
        .where(ProcessingJobORM.tenant_id == ctx.tenant_id)
        .order_by(ProcessingJobORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(stmt)
    jobs = res.scalars().all()
    return [
        {
            "id": j.id,
            "document_id": j.document_id,
            "status": j.status,
            "stage": j.stage,
            "attempt_count": j.attempt_count,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]
