from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from invoiceflow.application.reconciliation.matching_engine import MatchingEngine
from invoiceflow.application.reconciliation.validator import InvoiceValidator
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import GoodsReceipt, MatchReport, PurchaseOrder
from invoiceflow.infrastructure.database.models import MatchResultORM


class ReconciliationService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._validator = InvoiceValidator()
        self._matcher = MatchingEngine()

    async def reconcile_invoice(
        self,
        invoice: InvoiceAggregate,
        po: Optional[PurchaseOrder] = None,
        receipts: Optional[List[GoodsReceipt]] = None,
        policy: Optional[TolerancePolicy] = None,
    ) -> MatchReport:
        # 1. Deterministic validation
        val_issues = self._validator.validate(invoice)

        # 2. 3-way matching
        report = self._matcher.match_3_way(invoice, po, receipts, policy)

        # Combine issues
        all_issues = val_issues + report.issues
        is_matched = report.is_matched and len(val_issues) == 0
        requires_review = report.requires_review or len(val_issues) > 0

        combined_report = MatchReport(
            invoice_id=invoice.id,
            status=report.status,
            is_matched=is_matched,
            requires_review=requires_review,
            issues=all_issues,
        )

        import json
        result_orm = MatchResultORM(
            tenant_id=str(invoice.tenant_id),
            invoice_id=str(invoice.id),
            status=combined_report.status.value,
            is_matched=combined_report.is_matched,
            requires_review=combined_report.requires_review,
            issues_json=json.dumps([issue.model_dump() for issue in all_issues]),
        )
        self._session.add(result_orm)
        await self._session.flush()

        return combined_report
