import base64
import hashlib
from decimal import Decimal
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_db, require_role
from invoiceflow.application.exporting.service import (
    claim_for_export,
    get_export_batch,
    list_export_batches,
    list_exportable,
    record_export,
    save_export_batch,
)
from invoiceflow.infrastructure.database.models import InvoiceORM
from invoiceflow.infrastructure.storage.exporter import DocumentExporter

router = APIRouter(prefix="/exports", tags=["Exports"])


class ExportRequest(BaseModel):
    format: Literal["csv", "json", "xlsx"] = "csv"


def _build_export_payload(invoices_orm: list[InvoiceORM]) -> list[dict[str, Any]]:
    return [
        {
            "id": inv.id,
            "supplier_name": inv.supplier_name or "",
            "supplier_tax_id": inv.supplier_tax_id or "",
            "invoice_number": inv.invoice_number or "",
            "invoice_series": inv.invoice_series or "",
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else "",
            "currency": inv.currency,
            "subtotal": Decimal(str(inv.subtotal)),
            "tax_total": Decimal(str(inv.tax_total)),
            "amount_payable": Decimal(str(inv.amount_payable)),
            "status": inv.status,
        }
        for inv in invoices_orm
    ]


def _format_export_response(format_kind: str, invoices_data: list[dict[str, Any]]) -> Response:
    if format_kind == "csv":
        csv_str = DocumentExporter.to_csv(invoices_data)
        return Response(
            content=csv_str.encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=invoices_export.csv"},
        )
    elif format_kind == "xlsx":
        excel_bytes = DocumentExporter.to_excel(invoices_data)
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=invoices_export.xlsx"},
        )
    else:
        json_str = DocumentExporter.to_json(invoices_data)
        return Response(
            content=json_str.encode("utf-8"),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=invoices_export.json"},
        )


@router.post("")
async def create_export(
    req: ExportRequest,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    """Post an export batch: included invoices become EXPORTED and cannot be exported again."""
    invoices = await claim_for_export(session, ctx.tenant_id)
    response = _checksummed(req.format, invoices)
    if invoices:
        sha256 = response.headers["X-Export-SHA256"]
        batch = await save_export_batch(
            session=session,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.user_id,
            invoices=invoices,
            sha256=sha256,
            format_kind=req.format,
            file_bytes=response.body,
        )
        record_export(
            session,
            ctx.tenant_id,
            ctx.user_id,
            invoices,
            sha256,
            req.format,
        )
        response.headers["X-Export-ID"] = batch.id
        response.headers["X-Export-Batch-Number"] = batch.batch_number
    return response


@router.get("/batches")
async def get_batches(
    limit: int = Query(50, ge=1, le=100),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    """List recent export batches with summary metadata."""
    batches = await list_export_batches(session, ctx.tenant_id, limit=limit)
    return [
        {
            "id": b.id,
            "batch_number": b.batch_number,
            "format": b.format,
            "sha256": b.sha256,
            "invoice_count": b.invoice_count,
            "total_amount": float(b.total_amount),
            "created_by": b.created_by,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in batches
    ]


@router.get("/batches/{batch_id}")
async def download_batch(
    batch_id: str,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    """Idempotently re-download the exact artifact of a previously posted export batch."""
    batch = await get_export_batch(session, ctx.tenant_id, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export batch '{batch_id}' not found.",
        )
    file_bytes = base64.b64decode(batch.content_base64)
    media_types = {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
    }
    media_type = media_types.get(batch.format, "application/octet-stream")
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=export_{batch.batch_number}.{batch.format}",
            "X-Export-SHA256": batch.sha256,
            "X-Export-ID": batch.id,
            "X-Export-Batch-Number": batch.batch_number,
        },
    )


@router.get("/invoices")
@router.get("")
async def get_export_invoices(
    format: Literal["csv", "json", "xlsx"] = Query("csv"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    """Read-only preview of what the next posted export would contain."""
    return _checksummed(format, await list_exportable(session, ctx.tenant_id))


def _checksummed(format_kind: str, invoices: list[InvoiceORM]) -> Response:
    response = _format_export_response(format_kind, _build_export_payload(invoices))
    response.headers["X-Export-SHA256"] = hashlib.sha256(response.body).hexdigest()
    response.headers["Access-Control-Expose-Headers"] = "X-Export-SHA256"
    return response
