from datetime import datetime, timezone
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from invoiceflow.application.reconciliation.matching_engine import MatchingEngine
from invoiceflow.application.reconciliation.validator import InvoiceValidator
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    IssueSeverity,
    MatchIssue,
    MatchReport,
    MatchStatus,
)
from invoiceflow.infrastructure.database.models import MatchResultORM
from invoiceflow.infrastructure.database.repositories import (
    PolicyRepository,
    PurchasingRepository,
)


def merge_validation(report: MatchReport, validation_issues: list[MatchIssue]) -> MatchReport:
    """Invoice-intrinsic validation issues keep an otherwise clean match from clearing."""
    return MatchReport(
        invoice_id=report.invoice_id,
        status=report.status,
        is_matched=report.is_matched and not validation_issues,
        requires_review=report.requires_review or bool(validation_issues),
        issues=validation_issues + report.issues,
    )


class ReconciliationService:
    """Single entry point for validation + PO/GRN matching used by worker, API and review."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._validator = InvoiceValidator()
        self._matcher = MatchingEngine()
        self._purchasing = PurchasingRepository(session)
        self._policies = PolicyRepository(session)

    async def effective_policy(self, invoice: InvoiceAggregate) -> TolerancePolicy:
        as_of = invoice.issue_date or datetime.now(timezone.utc).date()
        return await self._policies.get_effective(invoice.tenant_id, invoice.supplier_tax_id, as_of)

    async def reconcile_invoice(
        self,
        invoice: InvoiceAggregate,
        policy: Optional[TolerancePolicy] = None,
    ) -> MatchReport:
        policy = policy or await self.effective_policy(invoice)
        val_issues = self._validator.validate(invoice)
        report = await self._match_against_purchasing(invoice, policy)

        combined_report = merge_validation(report, val_issues)
        all_issues = combined_report.issues
        self._session.add(
            MatchResultORM(
                tenant_id=str(invoice.tenant_id),
                invoice_id=str(invoice.id),
                status=combined_report.status.value,
                is_matched=combined_report.is_matched,
                requires_review=combined_report.requires_review,
                issues_json=json.dumps([issue.model_dump() for issue in all_issues]),
            )
        )
        await self._session.flush()
        return combined_report

    async def _match_against_purchasing(
        self, invoice: InvoiceAggregate, policy: TolerancePolicy
    ) -> MatchReport:
        candidates = []
        if invoice.supplier_tax_id:
            candidates = await self._purchasing.list_purchase_orders_for_vendor(
                invoice.tenant_id, invoice.supplier_tax_id
            )
        if len(candidates) > 1:
            # Without a PO reference on the invoice, picking one would be a guess.
            return MatchReport(
                invoice_id=invoice.id,
                status=MatchStatus.EXCEPTION,
                is_matched=False,
                requires_review=True,
                issues=[
                    MatchIssue(
                        code="AMBIGUOUS_PURCHASE_ORDER",
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"{len(candidates)} purchase orders match supplier "
                            f"{invoice.supplier_tax_id}: "
                            + ", ".join(po.po_number for po in candidates)
                        ),
                    )
                ],
            )

        po = candidates[0] if candidates else None
        receipts = None
        if po is not None and policy.goods_receipt_required:
            receipts = await self._purchasing.list_goods_receipts(invoice.tenant_id, po.id)
        return self._matcher.match_3_way(invoice, po, receipts, policy)
