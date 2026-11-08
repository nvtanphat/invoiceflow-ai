from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_current_context, get_db, require_role
from invoiceflow.infrastructure.database.models import InvoiceORM
from invoiceflow.infrastructure.storage.exporter import DocumentExporter

router = APIRouter(prefix="/exports", tags=["Exports"])


class ExportRequest(BaseModel):
    format: Literal["csv", "json", "xlsx"] = "csv"
    only_approved: bool = True


@router.post("")
async def create_export(
    req: ExportRequest,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(InvoiceORM).where(InvoiceORM.tenant_id == ctx.tenant_id)
    if req.only_approved:
        stmt = stmt.where(InvoiceORM.status == "APPROVED")

    res = await session.execute(stmt)
    invoices_orm = res.scalars().all()

    invoices_data = [
        {
            "id": inv.id,
            "supplier_name": inv.supplier_name,
            "supplier_tax_id": inv.supplier_tax_id,
            "invoice_number": inv.invoice_number,
            "invoice_series": inv.invoice_series,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "currency": inv.currency,
            "subtotal": float(inv.subtotal),
            "tax_total": float(inv.tax_total),
            "amount_payable": float(inv.amount_payable),
            "status": inv.status,
        }
        for inv in invoices_orm
    ]

    if req.format == "csv":
        csv_str = DocumentExporter.to_csv(invoices_data)
        return Response(
            content=csv_str.encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=invoices_export.csv"},
        )
    elif req.format == "xlsx":
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
