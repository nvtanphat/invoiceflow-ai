from datetime import date
from decimal import Decimal
import json
import re
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.application.reconciliation.service import ReconciliationService
from invoiceflow.application.review.approval_checks import ApprovalPreconditions
from invoiceflow.application.review.evidence_updates import find_candidate, record_field_decision
from invoiceflow.domain.invoices.models import InvoiceStatus
from invoiceflow.infrastructure.database.models import (
    AuditLogORM,
    InvoiceLineORM,
    InvoiceORM,
)
from invoiceflow.infrastructure.database.repositories import InvoiceRepository

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
_MONEY_FIELDS = {"subtotal", "tax_total", "amount_payable", "discount_total"}
_LINE_NUMERIC_FIELDS = ("qty", "unit_price", "line_amount")
_REVIEWABLE_STATUSES = {InvoiceStatus.READY_FOR_REVIEW.value}
_REJECTABLE_STATUSES = {InvoiceStatus.READY_FOR_REVIEW.value, InvoiceStatus.APPROVED.value}
_LINE_FIELD = re.compile(r"^lines\[(\d+)\]\.(\w+)$")


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
        invoice = await self._get_invoice(tenant_id, invoice_id)
        _assert_editable(invoice)

        clean_values, old_values = _clean_header_patches(invoice, patches)
        line_patches = patches.get("lines") if isinstance(patches.get("lines"), list) else []
        corrected_paths = await self._apply_line_patches(invoice_id, line_patches)

        if not clean_values and not corrected_paths:
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
                status=InvoiceStatus.READY_FOR_REVIEW.value,
                **clean_values,
            )
        )
        res = await self._session.execute(stmt)
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision or concurrent update on invoice {invoice_id} (expected revision {expected_revision})."
            )

        corrected_paths.update(
            {field: _evidence_text(value) for field, value in clean_values.items()}
        )
        for path, value in corrected_paths.items():
            await record_field_decision(
                self._session, invoice_id, path, value, "Corrected by reviewer"
            )

        self._session.add(
            AuditLogORM(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="INVOICE_FIELD_UPDATE",
                aggregate_type="invoice",
                aggregate_id=invoice_id,
                details_json=json.dumps({"reason": reason, "old": old_values, "new": patches}),
            )
        )
        await self._session.flush()
        await self._session.refresh(invoice)

        # Corrections change totals and lines, so the match evidence must be refreshed.
        await ReconciliationService(self._session).reconcile_invoice(
            await InvoiceRepository(self._session).load_aggregate(invoice)
        )
        return invoice

    async def resolve_field(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        field_path: str,
        decision: str,
        value: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> InvoiceORM:
        """Settle one flagged field: keep the extracted value, take the Vision candidate,
        or enter the value read from the source document."""
        if not _is_reviewable_field(field_path):
            raise ValueError(f"FIELD_NOT_REVIEWABLE: {field_path}")
        if decision == "accept_extracted":
            return await self._confirm_field(
                tenant_id, invoice_id, expected_revision, actor_id, field_path, reason
            )
        if decision == "accept_candidate":
            candidate = await find_candidate(self._session, invoice_id, field_path)
            if candidate is None or not candidate.normalized_value:
                raise ValueError(f"NO_CANDIDATE: {field_path} has no Vision candidate")
            value = candidate.normalized_value
        elif decision != "correct":
            raise ValueError(f"UNKNOWN_DECISION: {decision}")
        if value is None or not str(value).strip():
            raise ValueError(f"VALUE_REQUIRED: {field_path}")
        return await self.update_invoice_fields(
            tenant_id,
            invoice_id,
            expected_revision,
            actor_id,
            _patch_for(field_path, str(value)),
            reason=reason or f"{decision} {field_path}",
        )

    async def _confirm_field(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        field_path: str,
        reason: Optional[str],
    ) -> InvoiceORM:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        _assert_editable(invoice)
        res = await self._session.execute(
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
            )
            .values(revision=expected_revision + 1)
        )
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision: confirm failed for invoice {invoice_id} at revision {expected_revision}."
            )
        value = await self._current_value(invoice, field_path)
        await record_field_decision(
            self._session,
            invoice_id,
            field_path,
            value,
            reason or "Confirmed by reviewer against the source document",
        )
        self._session.add(
            AuditLogORM(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="INVOICE_FIELD_CONFIRMED",
                aggregate_type="invoice",
                aggregate_id=invoice_id,
                details_json=json.dumps(
                    {"field_path": field_path, "value": value, "reason": reason}
                ),
            )
        )
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice

    async def _current_value(self, invoice: InvoiceORM, field_path: str) -> Optional[str]:
        line_ref = _LINE_FIELD.match(field_path)
        if line_ref is None:
            current = getattr(invoice, field_path)
            return None if current is None else _evidence_text(current)
        line = (
            await self._session.execute(
                select(InvoiceLineORM).where(
                    InvoiceLineORM.invoice_id == invoice.id,
                    InvoiceLineORM.line_no == int(line_ref.group(1)) + 1,
                )
            )
        ).scalar_one_or_none()
        return None if line is None else str(getattr(line, line_ref.group(2)))

    async def approve_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        notes: Optional[str] = None,
    ) -> InvoiceORM:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        if invoice.status not in _REVIEWABLE_STATUSES:
            raise ValueError(
                f"INVOICE_NOT_REVIEWABLE: Hóa đơn ở trạng thái {invoice.status}, không thể phê duyệt."
            )
        await ApprovalPreconditions(self._session).verify(invoice, actor_id, notes)

        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
                InvoiceORM.status.in_(_REVIEWABLE_STATUSES),
            )
            .values(status=InvoiceStatus.APPROVED.value, revision=expected_revision + 1)
        )
        try:
            res = await self._session.execute(stmt)
            if res.rowcount == 0:
                raise ConcurrencyConflictError(
                    f"Stale revision: atomic approve failed for invoice {invoice_id} at revision {expected_revision}."
                )

            self._session.add(
                AuditLogORM(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action="INVOICE_APPROVE",
                    aggregate_type="invoice",
                    aggregate_id=invoice_id,
                    details_json=json.dumps(
                        {"notes": notes, "approved_revision": expected_revision + 1}
                    ),
                )
            )
            await self._session.flush()
            await self._session.refresh(invoice)
            return invoice
        except IntegrityError as exc:
            raise ConcurrencyConflictError(
                f"Concurrent duplicate conflict: Hóa đơn trùng với nhà cung cấp {invoice.supplier_tax_id} và số {invoice.invoice_number} đã được phê duyệt đồng thời bởi tiến trình khác."
            ) from exc

    async def reject_invoice(
        self,
        tenant_id: str,
        invoice_id: str,
        expected_revision: int,
        actor_id: str,
        reason: str,
    ) -> InvoiceORM:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        if invoice.status not in _REJECTABLE_STATUSES:
            raise ValueError(
                f"INVOICE_NOT_REJECTABLE: Hóa đơn ở trạng thái {invoice.status}, không thể từ chối."
            )

        stmt = (
            update(InvoiceORM)
            .where(
                InvoiceORM.tenant_id == tenant_id,
                InvoiceORM.id == invoice_id,
                InvoiceORM.revision == expected_revision,
                InvoiceORM.status.in_(_REJECTABLE_STATUSES),
            )
            .values(status=InvoiceStatus.REJECTED.value, revision=expected_revision + 1)
        )
        res = await self._session.execute(stmt)
        if res.rowcount == 0:
            raise ConcurrencyConflictError(
                f"Stale revision: atomic reject failed for invoice {invoice_id} at revision {expected_revision}."
            )

        self._session.add(
            AuditLogORM(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="INVOICE_REJECT",
                aggregate_type="invoice",
                aggregate_id=invoice_id,
                details_json=json.dumps(
                    {"reason": reason, "rejected_revision": expected_revision + 1}
                ),
            )
        )
        await self._session.flush()
        await self._session.refresh(invoice)
        return invoice

    async def _get_invoice(self, tenant_id: str, invoice_id: str) -> InvoiceORM:
        invoice = await self._session.get(InvoiceORM, invoice_id)
        if not invoice or invoice.tenant_id != tenant_id:
            raise ValueError(f"Invoice {invoice_id} not found.")
        return invoice

    async def _apply_line_patches(
        self, invoice_id: str, line_patches: list[dict[str, Any]]
    ) -> dict[str, str]:
        corrected: dict[str, str] = {}
        for line_patch in line_patches:
            stmt = select(InvoiceLineORM).where(InvoiceLineORM.invoice_id == invoice_id)
            if line_patch.get("id"):
                stmt = stmt.where(InvoiceLineORM.id == str(line_patch["id"]))
            elif line_patch.get("line_no"):
                stmt = stmt.where(InvoiceLineORM.line_no == int(line_patch["line_no"]))
            else:
                continue
            line = (await self._session.execute(stmt)).scalar_one_or_none()
            if line is None:
                continue
            for name in _LINE_NUMERIC_FIELDS:
                if name in line_patch:
                    value = Decimal(str(line_patch[name]))
                    setattr(line, name, value)
                    corrected[f"lines[{line.line_no - 1}].{name}"] = str(value)
            if "description" in line_patch:
                line.description = str(line_patch["description"])
                corrected[f"lines[{line.line_no - 1}].description"] = line.description
        return corrected


def _assert_editable(invoice: InvoiceORM) -> None:
    if invoice.status not in _REVIEWABLE_STATUSES:
        raise ValueError(
            f"INVOICE_NOT_REVIEWABLE: Hóa đơn ở trạng thái {invoice.status}, không thể chỉnh sửa."
        )


def _is_reviewable_field(field_path: str) -> bool:
    if field_path in ALLOWED_EDITABLE_FIELDS:
        return True
    line_ref = _LINE_FIELD.match(field_path)
    return line_ref is not None and line_ref.group(2) in (*_LINE_NUMERIC_FIELDS, "description")


def _patch_for(field_path: str, value: str) -> dict[str, Any]:
    line_ref = _LINE_FIELD.match(field_path)
    if line_ref is None:
        return {field_path: value}
    return {"lines": [{"line_no": int(line_ref.group(1)) + 1, line_ref.group(2): value}]}


def _clean_header_patches(
    invoice: InvoiceORM, patches: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    clean_values: dict[str, Any] = {}
    old_values: dict[str, str] = {}
    for key, value in patches.items():
        if key not in ALLOWED_EDITABLE_FIELDS:
            continue
        old_values[key] = str(getattr(invoice, key, ""))
        if key in _MONEY_FIELDS:
            clean_values[key] = Decimal(str(value))
        elif key == "issue_date":
            if isinstance(value, date):
                clean_values[key] = value
            elif isinstance(value, str) and value:
                clean_values[key] = date.fromisoformat(value)
        else:
            clean_values[key] = value
    return clean_values, old_values


def _evidence_text(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)
