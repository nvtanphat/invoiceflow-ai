import json
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.api.dependencies import (
    AuthenticatedContext,
    get_current_context,
    get_db,
    require_role,
)
from invoiceflow.application.review.service import ConcurrencyConflictError, ReviewService
from invoiceflow.infrastructure.database.models import (
    FieldEvidenceORM,
    InvoiceLineORM,
    InvoiceORM,
    MatchResultORM,
)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


class UnifiedReviewRequest(BaseModel):
    action: str  # "approve", "reject", "correct"
    notes: Optional[str] = None
    reason: Optional[str] = None
    corrections: Optional[dict[str, Any]] = None


class PatchInvoiceRequest(BaseModel):
    patches: dict[str, Any]
    reason: Optional[str] = "Reviewer modification"


class ApprovalRequest(BaseModel):
    notes: Optional[str] = None


class RejectionRequest(BaseModel):
    reason: str


@router.get("")
async def list_invoices(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    stmt = (
        select(InvoiceORM)
        .where(InvoiceORM.tenant_id == ctx.tenant_id)
        .order_by(InvoiceORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(InvoiceORM.status == status_filter)

    res = await session.execute(stmt)
    invoices = res.scalars().all()
    return [
        {
            "id": inv.id,
            "document_id": inv.document_id,
            "revision": inv.revision,
            "status": inv.status,
            "supplier_tax_id": inv.supplier_tax_id,
            "supplier_name": inv.supplier_name,
            "invoice_number": inv.invoice_number,
            "invoice_series": inv.invoice_series,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "currency": inv.currency,
            "amount_payable": str(inv.amount_payable),
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invoices
    ]


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    ctx: AuthenticatedContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(InvoiceORM).where(
        InvoiceORM.tenant_id == ctx.tenant_id,
        InvoiceORM.id == invoice_id,
    )
    res = await session.execute(stmt)
    inv = res.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    # Fetch lines
    lines_res = await session.execute(
        select(InvoiceLineORM)
        .where(InvoiceLineORM.invoice_id == invoice_id)
        .order_by(InvoiceLineORM.line_no)
    )
    lines = lines_res.scalars().all()

    # Fetch evidence
    ev_res = await session.execute(
        select(FieldEvidenceORM).where(FieldEvidenceORM.invoice_id == invoice_id)
    )
    evidence = ev_res.scalars().all()

    # Fetch latest matching issues
    match_res = await session.execute(
        select(MatchResultORM)
        .where(MatchResultORM.tenant_id == ctx.tenant_id, MatchResultORM.invoice_id == invoice_id)
        .order_by(MatchResultORM.created_at.desc())
    )
    latest_match = match_res.scalars().first()
    issues = json.loads(latest_match.issues_json) if latest_match else []

    return {
        "id": inv.id,
        "document_id": inv.document_id,
        "revision": inv.revision,
        "status": inv.status,
        "supplier_tax_id": inv.supplier_tax_id,
        "supplier_name": inv.supplier_name,
        "buyer_tax_id": inv.buyer_tax_id,
        "buyer_name": inv.buyer_name,
        "invoice_number": inv.invoice_number,
        "invoice_series": inv.invoice_series,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "currency": inv.currency,
        "subtotal": str(inv.subtotal),
        "discount_total": str(inv.discount_total),
        "tax_total": str(inv.tax_total),
        "amount_payable": str(inv.amount_payable),
        "signature_status": inv.signature_status,
        "tax_authority_status": inv.tax_authority_status,
        "lines": [
            {
                "id": line.id,
                "line_no": line.line_no,
                "description": line.description,
                "unit": line.unit,
                "qty": str(line.qty),
                "unit_price": str(line.unit_price),
                "discount": str(line.discount),
                "tax_rate": str(line.tax_rate) if line.tax_rate else None,
                "line_amount": str(line.line_amount),
            }
            for line in lines
        ],
        "evidence": [
            {
                "field_name": e.field_path,
                "field_path": e.field_path,
                "source": e.source_kind,
                "source_kind": e.source_kind,
                "page": e.page_index if e.page_index is not None else 0,
                "page_index": e.page_index if e.page_index is not None else 0,
                "bbox": json.loads(e.bbox_json) if e.bbox_json else None,
                "bbox_json": e.bbox_json or "",
                "table_id": e.table_id,
                "cell_id": e.cell_id,
                "raw_value": e.raw_value or "",
                "normalized_value": e.normalized_value or "",
                "confidence": float(e.confidence)
                if getattr(e, "confidence", None) is not None
                else 1.0,
            }
            for e in evidence
        ],
        "issues": issues,
    }


@router.post("/{invoice_id}/review")
async def review_invoice_unified(
    invoice_id: str,
    req: UnifiedReviewRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' containing expected revision integer is required.",
        )
    try:
        expected_revision = int(if_match.strip('"'))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid If-Match header."
        )

    review_service = ReviewService(session)
    try:
        if req.action == "approve":
            updated = await review_service.approve_invoice(
                tenant_id=ctx.tenant_id,
                invoice_id=invoice_id,
                expected_revision=expected_revision,
                actor_id=ctx.user_id,
                notes=req.notes or req.reason or "Phê duyệt bởi kiểm soát viên",
            )
        elif req.action == "reject":
            updated = await review_service.reject_invoice(
                tenant_id=ctx.tenant_id,
                invoice_id=invoice_id,
                expected_revision=expected_revision,
                actor_id=ctx.user_id,
                reason=req.reason or "Rejected by reviewer",
            )
        else:
            updated = await review_service.update_invoice_fields(
                tenant_id=ctx.tenant_id,
                invoice_id=invoice_id,
                expected_revision=expected_revision,
                actor_id=ctx.user_id,
                patches=req.corrections or {},
                reason=req.reason or "Reviewer corrections",
            )
        return {
            "id": updated.id,
            "invoice_id": updated.id,
            "revision": updated.revision,
            "status": updated.status,
            "message": f"Invoice review action '{req.action}' completed successfully.",
        }
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{invoice_id}/revisions")
async def patch_invoice(
    invoice_id: str,
    req: PatchInvoiceRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' containing expected revision integer is required.",
        )
    try:
        expected_revision = int(if_match.strip('"'))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid If-Match header."
        )

    review_service = ReviewService(session)
    try:
        updated = await review_service.update_invoice_fields(
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            expected_revision=expected_revision,
            actor_id=ctx.user_id,
            patches=req.patches,
            reason=req.reason or "Manual patch",
        )
        return {
            "invoice_id": updated.id,
            "revision": updated.revision,
            "status": updated.status,
            "message": "Invoice revised successfully.",
        }
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: str,
    req: ApprovalRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' is required for approval.",
        )
    expected_revision = int(if_match.strip('"'))

    review_service = ReviewService(session)
    try:
        approved = await review_service.approve_invoice(
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            expected_revision=expected_revision,
            actor_id=ctx.user_id,
            notes=req.notes,
        )
        return {
            "invoice_id": approved.id,
            "revision": approved.revision,
            "status": approved.status,
            "message": "Invoice approved successfully.",
        }
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/{invoice_id}/reject")
async def reject_invoice(
    invoice_id: str,
    req: RejectionRequest,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    ctx: AuthenticatedContext = Depends(require_role(["admin", "accountant", "reviewer"])),
    session: AsyncSession = Depends(get_db),
):
    if not if_match:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Header 'If-Match' is required for rejection.",
        )
    expected_revision = int(if_match.strip('"'))

    review_service = ReviewService(session)
    try:
        rejected = await review_service.reject_invoice(
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            expected_revision=expected_revision,
            actor_id=ctx.user_id,
            reason=req.reason,
        )
        return {
            "invoice_id": rejected.id,
            "revision": rejected.revision,
            "status": rejected.status,
            "message": "Invoice rejected.",
        }
    except ConcurrencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
