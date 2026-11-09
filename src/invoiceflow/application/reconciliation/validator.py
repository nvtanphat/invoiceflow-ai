from decimal import Decimal
from typing import List
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.domain.purchasing.models import IssueSeverity, MatchIssue


class InvoiceValidator:
    def validate(self, invoice: InvoiceAggregate) -> List[MatchIssue]:
        issues: List[MatchIssue] = []

        # 1. Mandatory field checks
        if not invoice.supplier_tax_id or not invoice.supplier_tax_id.strip():
            issues.append(
                MatchIssue(
                    code="MISSING_SUPPLIER_TAX_ID",
                    severity=IssueSeverity.CRITICAL,
                    message="Supplier tax ID (Mã số thuế bên bán) is missing.",
                    field_path="supplier_tax_id",
                )
            )

        if not invoice.invoice_number or not invoice.invoice_number.strip():
            issues.append(
                MatchIssue(
                    code="MISSING_INVOICE_NUMBER",
                    severity=IssueSeverity.CRITICAL,
                    message="Invoice number (Số hóa đơn) is missing.",
                    field_path="invoice_number",
                )
            )

        if invoice.amount_payable <= Decimal("0.0000"):
            issues.append(
                MatchIssue(
                    code="INVALID_AMOUNT_PAYABLE",
                    severity=IssueSeverity.WARNING,
                    message="Total amount payable must be greater than zero.",
                    field_path="amount_payable",
                    actual_value=str(invoice.amount_payable),
                )
            )

        # 2. Line arithmetic validation
        line_sum = Decimal("0.0000")
        for line in invoice.lines:
            expected_line_amount = (line.qty * line.unit_price) - line.discount
            if abs(line.line_amount - expected_line_amount) >= Decimal("0.0100"):
                issues.append(
                    MatchIssue(
                        code="LINE_ARITHMETIC_MISMATCH",
                        severity=IssueSeverity.CRITICAL,
                        message=f"Line {line.line_no}: qty * price - discount != line_amount ({line.line_amount} != {expected_line_amount})",
                        line_no=line.line_no,
                        field_path=f"lines[{line.line_no}].line_amount",
                        actual_value=str(line.line_amount),
                        expected_value=str(expected_line_amount),
                    )
                )
            line_sum += line.line_amount

        # 3. Subtotal vs line sum validation
        if invoice.lines and invoice.subtotal > Decimal("0.0000"):
            if abs(line_sum - invoice.subtotal) >= Decimal("0.0100"):
                issues.append(
                    MatchIssue(
                        code="SUBTOTAL_MISMATCH",
                        severity=IssueSeverity.WARNING,
                        message=f"Subtotal {invoice.subtotal} does not equal sum of lines {line_sum}",
                        field_path="subtotal",
                        actual_value=str(invoice.subtotal),
                        expected_value=str(line_sum),
                    )
                )

        # 4. Total payable arithmetic balance
        expected_payable = (
            invoice.subtotal
            - invoice.discount_total
            + invoice.tax_total
            + invoice.rounding_adjustment
        )
        if invoice.subtotal > Decimal("0.0000") and abs(
            invoice.amount_payable - expected_payable
        ) >= Decimal("0.0100"):
            issues.append(
                MatchIssue(
                    code="TOTAL_PAYABLE_MISMATCH",
                    severity=IssueSeverity.CRITICAL,
                    message=f"Amount payable {invoice.amount_payable} does not equal subtotal - discount + tax ({expected_payable})",
                    field_path="amount_payable",
                    actual_value=str(invoice.amount_payable),
                    expected_value=str(expected_payable),
                )
            )

        # 5. Document-level parser issues propagation
        for p_issue in getattr(invoice, "parser_issues", []):
            is_critical = any(k in p_issue for k in ["MISMATCH", "ERROR", "AMBIGUOUS", "CONFLICT"])
            issues.append(
                MatchIssue(
                    code=p_issue,
                    severity=IssueSeverity.CRITICAL if is_critical else IssueSeverity.WARNING,
                    message=f"Phát hiện cảnh báo trích xuất tài liệu: {p_issue}",
                )
            )

        # 6. Line-level parser issues propagation (e.g. ARITHMETIC_MISMATCH, AMBIGUOUS_NUMBER, PARSE_ERROR, CONFLICT)
        for line in invoice.lines:
            for l_issue in getattr(line, "issues", []):
                if l_issue == "ARITHMETIC_MISMATCH" and any(
                    i.code == "LINE_ARITHMETIC_MISMATCH" and i.line_no == line.line_no
                    for i in issues
                ):
                    continue
                is_crit = l_issue in (
                    "ARITHMETIC_MISMATCH",
                    "PARSE_ERROR",
                    "AMBIGUOUS_NUMBER",
                ) or any(k in l_issue for k in ["CONFLICT", "MISMATCH"])
                issues.append(
                    MatchIssue(
                        code=l_issue,
                        severity=IssueSeverity.CRITICAL if is_crit else IssueSeverity.WARNING,
                        message=f"Dòng {line.line_no}: Cảnh báo bóc tách số học ({l_issue})",
                        line_no=line.line_no,
                        field_path=f"lines[{line.line_no}]",
                        actual_value=getattr(line, "raw_line_amount", None)
                        or str(line.line_amount),
                    )
                )

        return issues
