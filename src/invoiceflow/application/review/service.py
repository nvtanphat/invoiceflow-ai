from datetime import date
from decimal import Decimal
import json
from typing import Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    DocumentORM,
    InvoiceLineORM,
    InvoiceORM,
    MatchResultORM,
    TolerancePolicyORM,
)

ALLOWED_EDITABLE_FIELDS = {
    "supplier_name",
    "supplier_tax_id",
    "buyer_name",
    "buyer_tax_id",
    "invoice_number",
    "invoice_series",
    "issue_date",
    "currency",
    "subtotal",
    "discount_total",
    "tax_total",
    "amount_payable",
}


class ConcurrencyConflictError(Exception):
    pass


class ReviewService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def update_invoice_fields(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        patches: dict[str, Any],
        reason: str = "Reviewer edit",
    ) -> InvoiceORM:
        invoice = await self._session.get(InvoiceORM, invoice_id)
        if not invoice or invoice.tenant_id != tenant_id:
            raise ValueError(f"Invoice {invoice_id} not found.")

        # Whitelist and sanitize patches
        clean_values: dict[str, Any] = {}
        old_values: dict[str, str] = {}
        for k, v in patches.items():
            if k in ALLOWED_EDITABLE_FIELDS:
                old_values[k] = str(getattr(invoice, k, ""))
                if k in ("subtotal", "tax_total", "amount_payable", "discount_total"):
                    clean_values[k] = Decimal(str(v))
                elif k == "issue_date":
                    if isinstance(v, str) and v:
                        clean_values[k] = date.fromisoformat(v)
                    elif isinstance(v, date):
                        clean_values[k] = v
                else:
                    clean_values[k] = v

        lines_patched = False
        if "lines" in patches and isinstance(patches["lines"], list):
            for line_patch in patches["lines"]:
                line_id = line_patch.get("id")
                line_no = line_patch.get("line_no")
                line_stmt = select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
                if line_id:
                    line_stmt = line_stmt.where(InvoiceLineORM.id == str(line_id))
                elif line_no:
                    line_stmt = line_stmt.where(InvoiceLineORM.line_no == int(line_no))
                ln = (await self._session.execute(line_stmt)).scalar_one_or_none()
                if ln:
                    if "qty" in line_patch:
                        ln.qty = Decimal(str(line_patch["qty"]))
                    if "unit_price" in line_patch:
                        ln.unit_price = Decimal(str(line_patch["unit_price"]))
                    if "line_amount" in line_patch:
                        ln.line_amount = Decimal(str(line_patch["line_amount"]))
                    if "description" in line_patch:
                        ln.description = str(line_patch["description"])
                    lines_patched = True

        if not clean_values and not lines_patched:
            return invoice

        # Atomic Compare-And-Swap update at database level
        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
            )
            .values(
                revision=expected_revision + 1,
                status="READY_FOR_REVIEW",
                **clean_values,
            )
        )
        res = await self._session.execute(stmt)
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision or concurrent update on invoice {invoice_id} (expected revision {expected_revision})."
            )

        audit = AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICE_FIELD_UPDATE",
            aggregate_type="invoice",
            aggregate_id=invoice_id,
            details_json=json.dumps({"reason": reason, "old": old_values, "new": patches}),
        )
        self._session.add(audit)
        await self._session.flush()

        # Refresh invoice object
        await self._session.refresh(invoice)

        # Re-run reconciliation on updated invoice to refresh match result & validation issues
        from invoiceflow.application.reconciliation.service import ReconciliationService
        from invoiceflow.domain.invoices.models import (
            InvoiceAggregate,
            InvoiceLine,
            InvoiceStatus,
            VerificationStatus,
        )

        lines_res = await self._session.execute(
            select(InvoiceLineORM)
            .where(InvoiceLineORM.invoice_id == invoice_id)
            .order_by(InvoiceLineORM.line_no)
        )
        current_lines = lines_res.scalars().all()
        agg_lines = [
            InvoiceLine(
                line_no=line_item.line_no,
                sku_ref=line_item.sku_ref,
                description=line_item.description,
                unit=line_item.unit,
                qty=line_item.qty,
                unit_price=line_item.unit_price,
                discount=line_item.discount,
                tax_rate=line_item.tax_rate,
                tax=line_item.tax,
                line_amount=line_item.line_amount,
            )
            for line_item in current_lines
        ]
        reconcile_agg = InvoiceAggregate(
            id=invoice.id,
            tenant_id=invoice.tenant_id,
            document_id=invoice.document_id,
            revision=invoice.revision,
            status=InvoiceStatus(invoice.status),
            supplier_tax_id=invoice.supplier_tax_id,
            supplier_name=invoice.supplier_name,
            buyer_tax_id=invoice.buyer_tax_id,
            buyer_name=invoice.buyer_name,
            invoice_number=invoice.invoice_number,
            invoice_series=invoice.invoice_series,
            issue_date=invoice.issue_date,
            currency=invoice.currency,
            subtotal=invoice.subtotal,
            discount_total=invoice.discount_total,
            tax_total=invoice.tax_total,
            amount_payable=invoice.amount_payable,
            rounding_adjustment=invoice.rounding_adjustment,
            lines=agg_lines,
            signature_status=VerificationStatus(invoice.signature_status),
            tax_authority_status=VerificationStatus(invoice.tax_authority_status),
        )
        reconciliation = ReconciliationService(self._session)
        await reconciliation.reconcile_invoice(reconcile_agg)

        return invoice

    async def approve_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        notes: Optional[str] = None,
    ) -> InvoiceORM:
        invoice = await self._session.get(InvoiceORM, invoice_id)
        if not invoice or invoice.tenant_id != tenant_id:
            raise ValueError(f"Invoice {invoice_id} not found.")

        # 1. Direct Intrinsic Line Arithmetic Check (Zero Tolerance)
        lines_stmt = select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
        current_lines = (await self._session.execute(lines_stmt)).scalars().all()
        for ln in current_lines:
            expected_amt = (ln.qty * ln.unit_price) - (ln.discount or Decimal("0.0000"))
            if abs(ln.line_amount - expected_amt) >= Decimal("0.0100"):
                raise ValueError(
                    f"Không thể phê duyệt: Hóa đơn có lỗi nghiêm trọng (LINE_ARITHMETIC_MISMATCH: Dòng {ln.line_no} thành tiền {ln.line_amount} != {expected_amt}). Vui lòng đính chính dữ liệu (correct) trước khi duyệt."
                )

        # 2. Check Reconciliation Match Status & Blocking Issues
        match_stmt = (
            select(MatchResultORM)
            .where(
                MatchResultORM.tenant_id == tenant_id,
                MatchResultORM.invoice_id == invoice_id,
            )
            .order_by(MatchResultORM.created_at.desc())
        )
        match_res = (await self._session.execute(match_stmt)).scalars().first()
        if match_res:
            issues = json.loads(match_res.issues_json) if match_res.issues_json else []
            critical_issues = [
                iss
                for iss in issues
                if iss.get("severity") == "critical"
                or iss.get("code")
                in (
                    "LINE_ARITHMETIC_MISMATCH",
                    "TOTAL_PAYABLE_MISMATCH",
                    "MISSING_SUPPLIER_TAX_ID",
                    "MISSING_INVOICE_NUMBER",
                    "ARITHMETIC_MISMATCH",
                    "PARSE_ERROR",
                    "AMBIGUOUS_NUMBER",
                )
            ]
            if critical_issues:
                blocking_codes = ", ".join(
                    sorted({iss.get("code", "UNKNOWN") for iss in critical_issues})
                )
                raise ValueError(
                    f"Không thể phê duyệt: Hóa đơn có lỗi nghiêm trọng ({blocking_codes}). Vui lòng đính chính dữ liệu (correct) trước khi duyệt."
                )

            if match_res.requires_review and not match_res.is_matched:
                if not notes or not notes.strip():
                    raise ValueError(
                        "Hóa đơn có sai lệch đối soát (requires review). Cần ghi chú lý do phê duyệt (notes/override)."
                    )

        # 2. Check Separation of Duties (SoD)
        policy_stmt = select(TolerancePolicyORM).where(TolerancePolicyORM.tenant_id == tenant_id)
        policy = (await self._session.execute(policy_stmt)).scalars().first()
        sod_required = policy.separation_of_duties_required if policy is not None else True
        if sod_required:
            doc = await self._session.get(DocumentORM, invoice.document_id)
            if doc and doc.uploaded_by and doc.uploaded_by == actor_id:
                raise PermissionError(
                    "Separation of duties violation: Document uploader cannot approve invoice."
                )

        # 3. Atomic CAS update
        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
            )
            .values(
                status="APPROVED",
                revision=expected_revision + 1,
            )
        )
        res = await self._session.execute(stmt)
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision: atomic approve failed for invoice {invoice_id} at revision {expected_revision}."
            )

        audit = AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICE_APPROVE",
            aggregate_type="invoice",
            aggregate_id=invoice_id,
            details_json=json.dumps({"notes": notes, "approved_revision": expected_revision + 1}),
        )
        self._session.add(audit)
        await self._session.flush()

        await self._session.refresh(invoice)
        return invoice

    async def reject_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        reason: str,
    ) -> InvoiceORM:
        invoice = await self._session.get(InvoiceORM, invoice_id)
        if not invoice or invoice.tenant_id != tenant_id:
            raise ValueError(f"Invoice {invoice_id} not found.")

        # Atomic CAS update
        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
            )
            .values(
                status="REJECTED",
                revision=expected_revision + 1,
            )
        )
        res = await self._session.execute(stmt)
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision: atomic reject failed for invoice {invoice_id} at revision {expected_revision}."
            )

        audit = AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICE_REJECT",
            aggregate_type="invoice",
            aggregate_id=invoice_id,
            details_json=json.dumps({"reason": reason, "rejected_revision": expected_revision + 1}),
        )
        self._session.add(audit)
        await self._session.flush()

        await self._session.refresh(invoice)
        return invoice
