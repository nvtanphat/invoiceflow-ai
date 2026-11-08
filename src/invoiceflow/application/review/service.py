import json
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.domain.invoices.models import InvoiceStatus
from invoiceflow.infrastructure.database.models import AuditLogORM, InvoiceORM


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
        stmt = select(InvoiceORM).where(
            InvoiceORM.tenant_id == tenant_id,
            InvoiceORM.id == invoice_id,
        )
        res = await self._session.execute(stmt)
        invoice = res.scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found.")

        if invoice.revision != expected_revision:
            raise ConcurrencyConflictError(
                f"Stale revision: expected {expected_revision}, but current revision is {invoice.revision}."
            )

        old_values = {}
        for k, v in patches.items():
            if hasattr(invoice, k):
                old_values[k] = str(getattr(invoice, k))
                if k in ("subtotal", "tax_total", "amount_payable", "discount_total"):
                    setattr(invoice, k, Decimal(str(v)))
                else:
                    setattr(invoice, k, v)

        invoice.revision += 1
        invoice.status = "READY_FOR_REVIEW"

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
        return invoice

    async def approve_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        notes: Optional[str] = None,
    ) -> InvoiceORM:
        stmt = select(InvoiceORM).where(
            InvoiceORM.tenant_id == tenant_id,
            InvoiceORM.id == invoice_id,
        )
        res = await self._session.execute(stmt)
        invoice = res.scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found.")

        if invoice.revision != expected_revision:
            raise ConcurrencyConflictError(
                f"Stale revision: expected {expected_revision}, but current revision is {invoice.revision}."
            )

        invoice.status = "APPROVED"
        invoice.revision += 1

        audit = AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICE_APPROVE",
            aggregate_type="invoice",
            aggregate_id=invoice_id,
            details_json=json.dumps({"notes": notes, "approved_revision": invoice.revision}),
        )
        self._session.add(audit)
        await self._session.flush()
        return invoice

    async def reject_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        reason: str,
    ) -> InvoiceORM:
        stmt = select(InvoiceORM).where(
            InvoiceORM.tenant_id == tenant_id,
            InvoiceORM.id == invoice_id,
        )
        res = await self._session.execute(stmt)
        invoice = res.scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found.")

        if invoice.revision != expected_revision:
            raise ConcurrencyConflictError(
                f"Stale revision: expected {expected_revision}, but current revision is {invoice.revision}."
            )

        invoice.status = "REJECTED"
        invoice.revision += 1

        audit = AuditLogORM(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="INVOICE_REJECT",
            aggregate_type="invoice",
            aggregate_id=invoice_id,
            details_json=json.dumps({"reason": reason, "rejected_revision": invoice.revision}),
        )
        self._session.add(audit)
        await self._session.flush()
        return invoice
