import hashlib
from decimal import Decimal
from typing import Any, Literal
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_db, require_role
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
    return await _export(session, ctx.tenant_id, req.format)


@router.get("/invoices")
@router.get("")
async def get_export_invoices(
    format: Literal["csv", "json", "xlsx"] = Query("csv"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    return await _export(session, ctx.tenant_id, format)


async def _export(session: AsyncSession, tenant_id: str, format_kind: str) -> Response:
    # Only approved invoices, in a stable order, so an export is reproducible and checkable.
    stmt = (
        select(InvoiceORM)
        .where(InvoiceORM.tenant_id == tenant_id, InvoiceORM.status == "APPROVED")
        .order_by(InvoiceORM.issue_date, InvoiceORM.invoice_number, InvoiceORM.id)
    )
    res = await session.execute(stmt)
    response = _format_export_response(format_kind, _build_export_payload(res.scalars().all()))
    response.headers["X-Export-SHA256"] = hashlib.sha256(response.body).hexdigest()
    response.headers["Access-Control-Expose-Headers"] = "X-Export-SHA256"
    return response
