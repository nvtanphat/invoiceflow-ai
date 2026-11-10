"""Straight-through processing decision split into three independent gates.

EXTRACTION_VERIFIED -> MATCHING_CLEARED -> ACCOUNTING_APPROVED

Verified extraction does not imply a cleared match, and a cleared match does not imply
accounting approval: the last gate additionally needs an explicit tenant policy opt-in
(mirrors the separation between bill matching and bill approval in Odoo / Dynamics AP).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from invoiceflow.domain.invoices.evidence_gate import automation_blockers
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceStatus
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import IssueSeverity, MatchReport, MatchStatus

_ZERO = Decimal("0.0000")
_LINE_ARITHMETIC_TOLERANCE = Decimal("0.0100")
_CLEARED_MATCH_STATUSES = {
    MatchStatus.MATCHED_EXACT: "3_WAY_MATCH_EXACT",
    MatchStatus.MATCHED_WITHIN_TOLERANCE: "3_WAY_MATCH_WITHIN_TOLERANCE",
}


@dataclass
class STPEvaluation:
    extraction_verified: bool
    matching_cleared: bool
    accounting_approved: bool
    stp_reasons: List[str] = field(default_factory=list)
    review_reasons: List[str] = field(default_factory=list)

    @property
    def is_stp_eligible(self) -> bool:
        return self.accounting_approved

    @property
    def target_status(self) -> InvoiceStatus:
        return (
            InvoiceStatus.APPROVED if self.accounting_approved else InvoiceStatus.READY_FOR_REVIEW
        )

    def gates(self) -> dict[str, bool]:
        return {
            "extraction_verified": self.extraction_verified,
            "matching_cleared": self.matching_cleared,
            "accounting_approved": self.accounting_approved,
        }


class STPEvaluator:
    def evaluate(
        self,
        invoice: InvoiceAggregate,
        match_report: Optional[MatchReport] = None,
        policy: Optional[TolerancePolicy] = None,
    ) -> STPEvaluation:
        policy = policy or TolerancePolicy(tenant_id=invoice.tenant_id)
        stp_reasons: List[str] = []

        extraction_blockers = self._extraction_blockers(invoice, stp_reasons)
        matching_blockers = self._matching_blockers(match_report, policy, stp_reasons)
        accounting_blockers = self._accounting_blockers(invoice, policy, stp_reasons)

        extraction_verified = not extraction_blockers
        matching_cleared = not matching_blockers
        return STPEvaluation(
            extraction_verified=extraction_verified,
            matching_cleared=matching_cleared,
            accounting_approved=extraction_verified
            and matching_cleared
            and not accounting_blockers,
            stp_reasons=stp_reasons,
            review_reasons=extraction_blockers + matching_blockers + accounting_blockers,
        )

    def _extraction_blockers(self, invoice: InvoiceAggregate, stp_reasons: List[str]) -> List[str]:
        blockers = automation_blockers(invoice)
        if not invoice.supplier_tax_id or not invoice.supplier_tax_id.strip():
            blockers.append("MISSING_SUPPLIER_TAX_ID")
        if not invoice.invoice_number or not invoice.invoice_number.strip():
            blockers.append("MISSING_INVOICE_NUMBER")
        if invoice.amount_payable <= _ZERO:
            blockers.append("INVALID_AMOUNT_PAYABLE: Total payable amount must be positive")
        if invoice.parser_issues:
            blockers.append("UNRESOLVED_PARSER_ISSUES")
        if invoice.is_arithmetic_balanced:
            stp_reasons.append("ARITHMETIC_BALANCED")
        else:
            blockers.append("ARITHMETIC_UNBALANCED: subtotal - discount + tax != amount_payable")
        blockers.extend(self._line_blockers(invoice))
        if not blockers:
            stp_reasons.append("EXTRACTION_EVIDENCE_VERIFIED")
        return blockers

    @staticmethod
    def _line_blockers(invoice: InvoiceAggregate) -> List[str]:
        if not invoice.lines:
            return ["MISSING_LINE_ITEMS"]
        blockers = []
        for line in invoice.lines:
            if line.issues:
                blockers.append(f"UNRESOLVED_LINE_ISSUES: Line {line.line_no}")
            if line.qty <= _ZERO or line.unit_price <= _ZERO:
                blockers.append(f"INVALID_LINE_QUANTITY_OR_PRICE: Line {line.line_no}")
            expected_amount = (line.qty * line.unit_price) - line.discount
            if abs(line.line_amount - expected_amount) >= _LINE_ARITHMETIC_TOLERANCE:
                blockers.append(
                    f"LINE_ARITHMETIC_ERROR: Line {line.line_no} amount {line.line_amount} "
                    f"!= expected {expected_amount}"
                )
        return blockers

    @staticmethod
    def _matching_blockers(
        report: Optional[MatchReport], policy: TolerancePolicy, stp_reasons: List[str]
    ) -> List[str]:
        if report is None:
            return ["MATCH_REPORT_REQUIRED"]

        blockers = [
            f"CRITICAL_ISSUE_{issue.code}: {issue.message}"
            for issue in report.issues
            if issue.severity == IssueSeverity.CRITICAL
        ]
        if report.status in _CLEARED_MATCH_STATUSES:
            if report.requires_review or not report.is_matched:
                blockers.append("MATCH_REPORT_NOT_CLEARED")
            else:
                stp_reasons.append(_CLEARED_MATCH_STATUSES[report.status])
        elif report.status == MatchStatus.MISSING_PO:
            blockers.extend(_non_po_blockers(report, policy, stp_reasons))
        else:
            blockers.append(f"3_WAY_MATCH_FAILED: Status={report.status.value}")
        return blockers

    @staticmethod
    def _accounting_blockers(
        invoice: InvoiceAggregate, policy: TolerancePolicy, stp_reasons: List[str]
    ) -> List[str]:
        blockers = []
        if invoice.amount_payable > policy.auto_approve_threshold:
            blockers.append(
                f"AMOUNT_EXCEEDS_THRESHOLD: Amount {invoice.amount_payable} exceeds "
                f"auto-approve threshold ({policy.auto_approve_threshold})"
            )
        elif invoice.amount_payable > _ZERO:
            stp_reasons.append("BELOW_AUTO_APPROVE_THRESHOLD")
        if policy.auto_approval_enabled:
            stp_reasons.append("AUTO_APPROVAL_ENABLED_BY_POLICY")
        else:
            blockers.append("AUTO_APPROVAL_DISABLED_BY_POLICY")
        return blockers


def _non_po_blockers(
    report: MatchReport, policy: TolerancePolicy, stp_reasons: List[str]
) -> List[str]:
    if policy.po_required:
        return ["MISSING_PURCHASE_ORDER"]
    other_issues = sorted({issue.code for issue in report.issues if issue.code != "MISSING_PO"})
    if other_issues:
        return [f"NON_PO_INVOICE_HAS_ISSUES: {', '.join(other_issues)}"]
    stp_reasons.append("NON_PO_INVOICE_ALLOWED_BY_POLICY")
    return []
