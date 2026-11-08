import json
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    DocumentORM,
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
                else:
                    clean_values[k] = v

        if not clean_values:
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

        # 1. Check Reconciliation Match Status
        match_stmt = select(MatchResultORM).where(
            MatchResultORM.tenant_id == tenant_id,
            MatchResultORM.invoice_id == invoice_id,
        )
        match_res = (await self._session.execute(match_stmt)).scalar_one_or_none()
        if match_res and match_res.requires_review and not match_res.is_matched:
            if not notes or not notes.strip():
                raise ValueError(
                    "Hóa đơn có sai lệch đối soát (requires review). Cần ghi chú lý do phê duyệt (notes/override)."
                )

        # 2. Check Separation of Duties (SoD)
        policy_stmt = select(TolerancePolicyORM).where(TolerancePolicyORM.tenant_id == tenant_id)
        policy = (await self._session.execute(policy_stmt)).scalars().first()
        if policy and policy.separation_of_duties_required:
            # Verify approving user is not the uploader/author
            doc = await self._session.get(DocumentORM, invoice.document_id)
            if doc and getattr(doc, "uploaded_by", None) == actor_id:
                raise PermissionError("Separation of duties violation: Document creator cannot approve invoice.")

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
