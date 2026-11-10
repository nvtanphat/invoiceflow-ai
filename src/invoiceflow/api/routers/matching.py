from datetime import date
from decimal import Decimal
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_db, require_role
from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.infrastructure.database.models import (
    GoodsReceiptLineORM,
    GoodsReceiptORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
)
from invoiceflow.infrastructure.database.repositories import InvoiceRepository

router = APIRouter(prefix="", tags=["Reconciliation & Purchasing"])


class POLineInput(BaseModel):
    line_no: int
    sku: Optional[str] = None
    description: str
    unit: Optional[str] = None
    ordered_qty: Decimal
    unit_price: Decimal
    line_total: Decimal


class POImportRequest(BaseModel):
    vendor_tax_id: str
    vendor_name: str
    po_number: str
    order_date: date
    currency: str = "VND"
    subtotal: Decimal
    lines: List[POLineInput]


class GRNLineInput(BaseModel):
    po_line_id: str
    line_no: int
    received_qty: Decimal
    rejected_qty: Decimal = Decimal("0.0000")


class GRNImportRequest(BaseModel):
    po_id: str
    grn_number: str
    receipt_date: date
    lines: List[GRNLineInput]


@router.post("/purchase-orders/import", status_code=status.HTTP_201_CREATED)
async def import_purchase_order(
    req: POImportRequest,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    po_orm = PurchaseOrderORM(
        id=str(uuid.uuid4()),
        tenant_id=ctx.tenant_id,
        vendor_tax_id=req.vendor_tax_id,
        vendor_name=req.vendor_name,
        po_number=req.po_number,
        order_date=req.order_date,
        currency=req.currency,
        subtotal=req.subtotal,
    )
    session.add(po_orm)
    await session.flush()

    po_lines = []
    for line in req.lines:
        line_orm = PurchaseOrderLineORM(
            id=str(uuid.uuid4()),
            po_id=po_orm.id,
            line_no=line.line_no,
            sku=line.sku,
            description=line.description,
            unit=line.unit,
            ordered_qty=line.ordered_qty,
            unit_price=line.unit_price,
            line_total=line.line_total,
        )
        session.add(line_orm)
        po_lines.append(line_orm)

    await session.flush()
    return {
        "po_id": po_orm.id,
        "po_number": po_orm.po_number,
        "line_count": len(po_lines),
        "message": "Purchase Order imported successfully.",
    }


@router.post("/goods-receipts/import", status_code=status.HTTP_201_CREATED)
async def import_goods_receipt(
    req: GRNImportRequest,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant"])),
    session: AsyncSession = Depends(get_db),
):
    # Verify PO exists and belongs to the current tenant
    po_stmt = select(PurchaseOrderORM).where(
        PurchaseOrderORM.id == req.po_id,
        PurchaseOrderORM.tenant_id == ctx.tenant_id,
    )
    po = (await session.execute(po_stmt)).scalar_one_or_none()
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase Order not found in the current tenant.",
        )

    # Verify all PO lines belong to this PO
    po_lines_stmt = select(PurchaseOrderLineORM.id).where(PurchaseOrderLineORM.po_id == po.id)
    valid_po_line_ids = set((await session.execute(po_lines_stmt)).scalars().all())

    for line in req.lines:
        if line.po_line_id not in valid_po_line_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"PO line '{line.po_line_id}' does not belong to Purchase Order '{po.id}'.",
            )

    grn_orm = GoodsReceiptORM(
        id=str(uuid.uuid4()),
        tenant_id=ctx.tenant_id,
        po_id=req.po_id,
        grn_number=req.grn_number,
        receipt_date=req.receipt_date,
    )
    session.add(grn_orm)
    await session.flush()

    for line in req.lines:
        grn_line_orm = GoodsReceiptLineORM(
            id=str(uuid.uuid4()),
            grn_id=grn_orm.id,
            po_line_id=line.po_line_id,
            line_no=line.line_no,
            received_qty=line.received_qty,
            rejected_qty=line.rejected_qty,
        )
        session.add(grn_line_orm)

    await session.flush()
    return {
        "grn_id": grn_orm.id,
        "grn_number": grn_orm.grn_number,
        "message": "Goods Receipt imported successfully.",
    }


@router.post("/invoices/{invoice_id}/match")
@router.post("/matching/reconcile/{invoice_id}")
async def match_invoice(
    invoice_id: str,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    inv_repo = InvoiceRepository(session)
    inv = await inv_repo.get_invoice(ctx.tenant_id, invoice_id)
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    report = await ReconciliationService(session).reconcile_invoice(
        await inv_repo.load_aggregate(inv)
    )

    return {
        "invoice_id": str(report.invoice_id),
        "status": report.status.value,
        "is_matched": report.is_matched,
        "requires_review": report.requires_review,
        "issue_count": len(report.issues),
        "issues": [i.model_dump() for i in report.issues],
    }
