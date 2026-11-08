from datetime import date
from decimal import Decimal
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import AuthenticatedContext, get_current_context, get_db, require_role
from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine, InvoiceStatus
from invoiceflow.domain.purchasing.models import (
    GoodsReceipt,
    GRNLine,
    POLine,
    PurchaseOrder,
)
from invoiceflow.infrastructure.database.models import (
    GoodsReceiptLineORM,
    GoodsReceiptORM,
    InvoiceLineORM,
    InvoiceORM,
    PurchaseOrderLineORM,
    PurchaseOrderORM,
)

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
async def match_invoice(
    invoice_id: str,
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    inv_stmt = select(InvoiceORM).where(
        InvoiceORM.tenant_id == ctx.tenant_id,
        InvoiceORM.id == invoice_id,
    )
    res = await session.execute(inv_stmt)
    inv = res.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    lines_res = await session.execute(
        select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
    )
    lines_orm = lines_res.scalars().all()

    inv_aggregate = InvoiceAggregate(
        id=uuid.UUID(inv.id),
        tenant_id=uuid.UUID(inv.tenant_id),
        document_id=uuid.UUID(inv.document_id),
        revision=inv.revision,
        status=InvoiceStatus(inv.status),
        supplier_tax_id=inv.supplier_tax_id,
        supplier_name=inv.supplier_name,
        invoice_number=inv.invoice_number,
        invoice_series=inv.invoice_series,
        issue_date=inv.issue_date,
        currency=inv.currency,
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_total=inv.tax_total,
        amount_payable=inv.amount_payable,
        lines=[
            InvoiceLine(
                line_no=l.line_no,
                sku_ref=l.sku_ref,
                description=l.description,
                unit=l.unit,
                qty=l.qty,
                unit_price=l.unit_price,
                discount=l.discount,
                tax_rate=l.tax_rate,
                tax=l.tax,
                line_amount=l.line_amount,
                purchase_order_line_id=uuid.UUID(l.po_line_id) if l.po_line_id else None,
            )
            for l in lines_orm
        ],
    )

    # Search corresponding PO if supplier tax ID matches
    po_stmt = select(PurchaseOrderORM).where(
        PurchaseOrderORM.tenant_id == ctx.tenant_id,
        PurchaseOrderORM.vendor_tax_id == inv.supplier_tax_id,
    )
    po_res = await session.execute(po_stmt)
    po_orm = po_res.scalars().first()

    domain_po: Optional[PurchaseOrder] = None
    domain_receipts: List[GoodsReceipt] = []

    if po_orm:
        po_lines_res = await session.execute(
            select(PurchaseOrderLineORM).where(PurchaseOrderLineORM.po_id == po_orm.id)
        )
        domain_po = PurchaseOrder(
            id=uuid.UUID(po_orm.id),
            tenant_id=uuid.UUID(po_orm.tenant_id),
            vendor_tax_id=po_orm.vendor_tax_id,
            vendor_name=po_orm.vendor_name,
            po_number=po_orm.po_number,
            order_date=po_orm.order_date,
            currency=po_orm.currency,
            subtotal=po_orm.subtotal,
            lines=[
                POLine(
                    id=uuid.UUID(pl.id),
                    po_id=uuid.UUID(pl.po_id),
                    line_no=pl.line_no,
                    sku=pl.sku,
                    description=pl.description,
                    unit=pl.unit,
                    ordered_qty=pl.ordered_qty,
                    unit_price=pl.unit_price,
                    line_total=pl.line_total,
                )
                for pl in po_lines_res.scalars().all()
            ],
        )

        # Fetch associated GRNs
        grn_res = await session.execute(
            select(GoodsReceiptORM).where(GoodsReceiptORM.po_id == po_orm.id)
        )
        for grn_o in grn_res.scalars().all():
            grn_lines_res = await session.execute(
                select(GoodsReceiptLineORM).where(GoodsReceiptLineORM.grn_id == grn_o.id)
            )
            domain_receipts.append(
                GoodsReceipt(
                    id=uuid.UUID(grn_o.id),
                    tenant_id=uuid.UUID(grn_o.tenant_id),
                    po_id=uuid.UUID(grn_o.po_id),
                    grn_number=grn_o.grn_number,
                    receipt_date=grn_o.receipt_date,
                    lines=[
                        GRNLine(
                            id=uuid.UUID(gl.id),
                            grn_id=uuid.UUID(gl.grn_id),
                            po_line_id=uuid.UUID(gl.po_line_id),
                            line_no=gl.line_no,
                            received_qty=gl.received_qty,
                            rejected_qty=gl.rejected_qty,
                        )
                        for gl in grn_lines_res.scalars().all()
                    ],
                )
            )

    recon_service = ReconciliationService(session)
    report = await recon_service.reconcile_invoice(
        invoice=inv_aggregate,
        po=domain_po,
        receipts=domain_receipts,
    )

    return {
        "invoice_id": str(report.invoice_id),
        "status": report.status.value,
        "is_matched": report.is_matched,
        "requires_review": report.requires_review,
        "issue_count": len(report.issues),
        "issues": [i.model_dump() for i in report.issues],
    }
