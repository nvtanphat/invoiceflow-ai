from decimal import Decimal
import re
from typing import List, Optional
import unicodedata
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    GoodsReceipt,
    IssueSeverity,
    MatchIssue,
    MatchReport,
    MatchStatus,
    POLine,
    PurchaseOrder,
)

_UOM_SYNONYMS = {
    "cai": "cai",
    "chiec": "cai",
    "pc": "cai",
    "pcs": "cai",
    "piece": "cai",
    "pieces": "cai",
    "bo": "bo",
    "set": "bo",
    "sets": "bo",
    "hop": "hop",
    "box": "hop",
    "boxes": "hop",
    "thung": "thung",
    "carton": "thung",
    "ctn": "thung",
    "kg": "kg",
    "kilogram": "kg",
    "kilo": "kg",
    "g": "g",
    "gram": "g",
    "m": "m",
    "met": "m",
    "meter": "m",
    "cuon": "cuon",
    "roll": "cuon",
    "rolls": "cuon",
    "goi": "goi",
    "pack": "goi",
    "package": "goi",
    "binh": "binh",
    "can": "can",
    "chai": "chai",
    "bottle": "chai",
    "lo": "lo",
}


def _normalize_uom(uom: Optional[str]) -> Optional[str]:
    if not uom:
        return None
    text = unicodedata.normalize("NFD", uom.strip().lower())
    clean = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    clean = re.sub(r"[^\w]", "", clean)
    return _UOM_SYNONYMS.get(clean, clean)


class MatchingEngine:
    def match_3_way(
        self,
        invoice: InvoiceAggregate,
        po: Optional[PurchaseOrder] = None,
        receipts: Optional[List[GoodsReceipt]] = None,
        policy: Optional[TolerancePolicy] = None,
    ) -> MatchReport:
        if policy is None:
            policy = TolerancePolicy(tenant_id=invoice.tenant_id)

        issues: List[MatchIssue] = []

        if po is None:
            issues.append(
                MatchIssue(
                    code="MISSING_PO",
                    severity=IssueSeverity.WARNING,
                    message="No corresponding Purchase Order found for this invoice.",
                )
            )
            return MatchReport(
                invoice_id=invoice.id,
                status=MatchStatus.MISSING_PO,
                is_matched=False,
                requires_review=True,
                issues=issues,
            )

        # Check total amount delta policy
        amount_delta = abs(invoice.amount_payable - po.subtotal)
        if amount_delta > policy.max_amount_delta:
            issues.append(
                MatchIssue(
                    code="MAX_AMOUNT_DELTA_EXCEEDED",
                    severity=IssueSeverity.WARNING,
                    message=f"Total invoice amount deviation ({amount_delta}) exceeds max policy delta ({policy.max_amount_delta}).",
                    field_path="amount_payable",
                    actual_value=str(invoice.amount_payable),
                    expected_value=str(po.subtotal),
                )
            )

        # Build index of PO lines
        po_lines_by_id = {line.id: line for line in po.lines}
        po_lines_by_sku = {line.sku: line for line in po.lines if line.sku}
        po_lines_by_no = {line.line_no: line for line in po.lines}

        # Build index of total received qty per PO line across all GRNs
        received_qty_by_po_line: dict = {}
        if receipts:
            for grn in receipts:
                for grn_line in grn.lines:
                    po_line_id = grn_line.po_line_id
                    current = received_qty_by_po_line.get(po_line_id, Decimal("0.0000"))
                    received_qty_by_po_line[po_line_id] = current + grn_line.received_qty

        has_price_variance = False
        has_qty_variance = False
        has_missing_grn = False
        has_minor_price_variance = False
        has_minor_qty_variance = False

        for inv_line in invoice.lines:
            # 1. Multi-factor match to PO line
            matched_po_line: Optional[POLine] = None
            if (
                inv_line.purchase_order_line_id
                and inv_line.purchase_order_line_id in po_lines_by_id
            ):
                matched_po_line = po_lines_by_id[inv_line.purchase_order_line_id]
            elif inv_line.sku_ref and inv_line.sku_ref in po_lines_by_sku:
                matched_po_line = po_lines_by_sku[inv_line.sku_ref]
            else:
                # Text token similarity match on description
                inv_tokens = set(re.findall(r"\w+", inv_line.description.lower()))
                best_sim = 0.0
                best_cand = None
                for candidate_po_line in po.lines:
                    po_tokens = set(re.findall(r"\w+", candidate_po_line.description.lower()))
                    if inv_tokens and po_tokens:
                        sim = len(inv_tokens & po_tokens) / len(inv_tokens | po_tokens)
                        if sim > best_sim:
                            best_sim = sim
                            best_cand = candidate_po_line
                if best_cand and best_sim >= 0.50:
                    matched_po_line = best_cand
                elif inv_line.line_no in po_lines_by_no:
                    matched_po_line = po_lines_by_no[inv_line.line_no]

            if not matched_po_line:
                issues.append(
                    MatchIssue(
                        code="UNMATCHED_LINE",
                        severity=IssueSeverity.WARNING,
                        message=f"Invoice line {inv_line.line_no} could not be matched to any PO line.",
                        line_no=inv_line.line_no,
                    )
                )
                continue

            # Unit of Measure (UoM) cross-validation
            norm_inv_unit = _normalize_uom(inv_line.unit)
            norm_po_unit = _normalize_uom(matched_po_line.unit)
            if norm_inv_unit and norm_po_unit and norm_inv_unit != norm_po_unit:
                issues.append(
                    MatchIssue(
                        code="UOM_MISMATCH",
                        severity=IssueSeverity.WARNING,
                        message=f"Line {inv_line.line_no}: Invoiced unit '{inv_line.unit}' differs from PO unit '{matched_po_line.unit}'.",
                        line_no=inv_line.line_no,
                        field_path=f"lines[{inv_line.line_no}].unit",
                        actual_value=inv_line.unit,
                        expected_value=matched_po_line.unit,
                    )
                )

            # 2. Price match
            if not policy.is_price_within_tolerance(
                matched_po_line.unit_price, inv_line.unit_price
            ):
                has_price_variance = True
                issues.append(
                    MatchIssue(
                        code="PRICE_VARIANCE",
                        severity=IssueSeverity.WARNING,
                        message=f"Line {inv_line.line_no}: unit price {inv_line.unit_price} exceeds PO price {matched_po_line.unit_price} beyond tolerance.",
                        line_no=inv_line.line_no,
                        field_path=f"lines[{inv_line.line_no}].unit_price",
                        actual_value=str(inv_line.unit_price),
                        expected_value=str(matched_po_line.unit_price),
                    )
                )
            elif inv_line.unit_price != matched_po_line.unit_price:
                has_minor_price_variance = True

            # 3. 3-way quantity match with GRN
            if receipts is not None:
                tot_received = received_qty_by_po_line.get(matched_po_line.id, Decimal("0.0000"))
                if tot_received == Decimal("0.0000") and inv_line.qty > Decimal("0.0000"):
                    has_missing_grn = True
                    issues.append(
                        MatchIssue(
                            code="MISSING_GRN",
                            severity=IssueSeverity.WARNING,
                            message=f"Line {inv_line.line_no}: No goods receipt recorded for PO line {matched_po_line.line_no}.",
                            line_no=inv_line.line_no,
                            actual_value=str(inv_line.qty),
                            expected_value="0.0000",
                        )
                    )
                elif not policy.is_qty_within_tolerance(tot_received, inv_line.qty):
                    has_qty_variance = True
                    issues.append(
                        MatchIssue(
                            code="QUANTITY_VARIANCE",
                            severity=IssueSeverity.WARNING,
                            message=f"Line {inv_line.line_no}: Invoiced qty {inv_line.qty} != Total received qty {tot_received}.",
                            line_no=inv_line.line_no,
                            field_path=f"lines[{inv_line.line_no}].qty",
                            actual_value=str(inv_line.qty),
                            expected_value=str(tot_received),
                        )
                    )
                elif inv_line.qty != tot_received:
                    has_minor_qty_variance = True

        # Determine overall match status
        has_critical_issue = any(i.severity == IssueSeverity.CRITICAL for i in issues)

        if has_qty_variance:
            status = MatchStatus.QUANTITY_VARIANCE
            is_matched = False
            requires_review = True
        elif has_price_variance:
            status = MatchStatus.PRICE_VARIANCE
            is_matched = False
            requires_review = True
        elif has_missing_grn:
            status = MatchStatus.MISSING_GRN
            is_matched = False
            requires_review = True
        elif has_critical_issue:
            status = MatchStatus.EXCEPTION
            is_matched = False
            requires_review = True
        elif has_minor_price_variance or has_minor_qty_variance:
            status = MatchStatus.MATCHED_WITHIN_TOLERANCE
            is_matched = True
            requires_review = False
        elif issues:
            status = MatchStatus.EXCEPTION
            is_matched = False
            requires_review = True
        else:
            status = MatchStatus.MATCHED_EXACT
            is_matched = True
            requires_review = False

        return MatchReport(
            invoice_id=invoice.id,
            status=status,
            is_matched=is_matched,
            requires_review=requires_review,
            issues=issues,
        )
