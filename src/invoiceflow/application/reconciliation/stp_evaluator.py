from dataclasses import dataclass, field
from decimal import Decimal
import logging
from typing import List, Optional

from invoiceflow.domain.invoices.models import (
    FieldVerificationState,
    InvoiceAggregate,
    InvoiceStatus,
    VerificationStatus,
)
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import IssueSeverity, MatchReport, MatchStatus

logger = logging.getLogger(__name__)


@dataclass
class STPEvaluation:
    is_stp_eligible: bool
    target_status: InvoiceStatus
    stp_reasons: List[str] = field(default_factory=list)
    review_reasons: List[str] = field(default_factory=list)


class STPEvaluator:
    """Evaluates whether an invoice qualifies for Straight-Through Processing (STP)

    without human intervention, based on risk-based policy criteria.
    """

    def evaluate(
        self,
        invoice: InvoiceAggregate,
        match_report: Optional[MatchReport] = None,
        policy: Optional[TolerancePolicy] = None,
    ) -> STPEvaluation:
        stp_reasons: List[str] = []
        review_reasons: List[str] = []

        if policy is None:
            policy = TolerancePolicy(tenant_id=invoice.tenant_id)

        # 1. Amount Threshold Check
        if invoice.amount_payable > policy.auto_approve_threshold:
            review_reasons.append(
                f"AMOUNT_EXCEEDS_THRESHOLD: Amount {invoice.amount_payable} exceeds auto-approve threshold ({policy.auto_approve_threshold})"
            )
        elif invoice.amount_payable <= Decimal("0.0000"):
            review_reasons.append("INVALID_AMOUNT_PAYABLE: Total payable amount must be positive")
        else:
            stp_reasons.append("BELOW_AUTO_APPROVE_THRESHOLD")

        # 2. Critical Validation & Matching Issues Check
        if match_report is not None:
            critical_issues = [
                iss for iss in match_report.issues if iss.severity == IssueSeverity.CRITICAL
            ]
            if critical_issues:
                for c_iss in critical_issues:
                    review_reasons.append(f"CRITICAL_ISSUE_{c_iss.code}: {c_iss.message}")

            # Match status check
            if match_report.status == MatchStatus.MATCHED_EXACT:
                stp_reasons.append("3_WAY_MATCH_EXACT")
            elif match_report.status == MatchStatus.MATCHED_WITHIN_TOLERANCE:
                stp_reasons.append("3_WAY_MATCH_WITHIN_TOLERANCE")
            elif match_report.status == MatchStatus.MISSING_PO:
                # Allowed for non-PO invoices if verified electronic invoice or zero critical issues
                if invoice.signature_status == VerificationStatus.VERIFIED:
                    stp_reasons.append("NON_PO_VERIFIED_ELECTRONIC_INVOICE")
                elif not critical_issues and not match_report.issues:
                    stp_reasons.append("NON_PO_VALID_DIRECT_INVOICE")
                else:
                    review_reasons.append("MISSING_PURCHASE_ORDER")
            else:
                review_reasons.append(f"3_WAY_MATCH_FAILED: Status={match_report.status.value}")

        # 3. Field Verification States and Evidence Conflicts Check
        has_conflict = False
        has_invalid = False

        for ev in invoice.evidence:
            if ev.verification_state == FieldVerificationState.CONFLICT:
                has_conflict = True
                review_reasons.append(
                    f"FIELD_CONFLICT: {ev.field_path} ({ev.review_reason or 'candidate discrepancy'})"
                )
            elif ev.verification_state == FieldVerificationState.INVALID:
                has_invalid = True
                review_reasons.append(
                    f"FIELD_INVALID: {ev.field_path} ({ev.review_reason or 'format violation'})"
                )
            elif ev.verification_state == FieldVerificationState.ZERO and ev.field_path in (
                "amount_payable",
                "subtotal",
            ):
                review_reasons.append(f"ZERO_FINANCIAL_TOTAL: {ev.field_path} is zero or negative")

        if not has_conflict:
            stp_reasons.append("NO_UNRESOLVED_CONFLICTS")
        if not has_invalid:
            stp_reasons.append("NO_INVALID_FIELDS")

        # 4. Intrinsic Arithmetic Balance Check
        if not invoice.is_arithmetic_balanced:
            review_reasons.append(
                "ARITHMETIC_UNBALANCED: subtotal - discount + tax != amount_payable"
            )
        else:
            stp_reasons.append("ARITHMETIC_BALANCED")

        # Line-by-line arithmetic check
        for line in invoice.lines:
            expected_amt = (line.qty * line.unit_price) - line.discount
            if abs(line.line_amount - expected_amt) >= Decimal("0.0100"):
                review_reasons.append(
                    f"LINE_ARITHMETIC_ERROR: Line {line.line_no} amount {line.line_amount} != expected {expected_amt}"
                )

        # 5. Mandatory Headers
        if not invoice.supplier_tax_id or not invoice.supplier_tax_id.strip():
            review_reasons.append("MISSING_SUPPLIER_TAX_ID")
        if not invoice.invoice_number or not invoice.invoice_number.strip():
            review_reasons.append("MISSING_INVOICE_NUMBER")

        # Final decision
        is_stp_eligible = len(review_reasons) == 0
        target_status = (
            InvoiceStatus.APPROVED if is_stp_eligible else InvoiceStatus.READY_FOR_REVIEW
        )

        return STPEvaluation(
            is_stp_eligible=is_stp_eligible,
            target_status=target_status,
            stp_reasons=stp_reasons,
            review_reasons=review_reasons,
        )
