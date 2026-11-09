from decimal import Decimal
import re
from typing import List
from invoiceflow.domain.invoices.models import InvoiceAggregate
from invoiceflow.domain.purchasing.models import IssueSeverity, MatchIssue

_TAX_ID_PATTERN = re.compile(r"^\d{10}(?:-\d{3})?$")


class InvoiceValidator:
    _VALID_VAT_RATES = {
        Decimal("0.0"),
        Decimal("0.00"),
        Decimal("0.0000"),
        Decimal("5.0"),
        Decimal("5.00"),
        Decimal("5.0000"),
        Decimal("8.0"),
        Decimal("8.00"),
        Decimal("8.0000"),
        Decimal("10.0"),
        Decimal("10.00"),
        Decimal("10.0000"),
    }

    @staticmethod
    def _is_valid_vietnamese_tax_id(tax_id: str) -> bool:
        clean = tax_id.strip()
        return bool(_TAX_ID_PATTERN.match(clean))

    @staticmethod
    def _verify_mst_checksum(tax_id: str) -> bool:
        """Verifies 10-digit enterprise Vietnamese MST checksum using mod-11 weighting:
        weights: [31, 29, 23, 19, 17, 13, 7, 5, 3]
        """
        clean = tax_id.strip()[:10]
        if not clean.isdigit() or len(clean) != 10:
            return False
        digits = [int(c) for c in clean]
        weights = [31, 29, 23, 19, 17, 13, 7, 5, 3]
        total = sum(d * w for d, w in zip(digits[:9], weights))
        check = 10 - (total % 11)
        if check == 10:
            check = 0
        return digits[9] == check

    def validate(self, invoice: InvoiceAggregate) -> List[MatchIssue]:
        issues: List[MatchIssue] = []

        # 1. Mandatory field checks & Vietnamese Tax ID validation
        if not invoice.supplier_tax_id or not invoice.supplier_tax_id.strip():
            issues.append(
                MatchIssue(
                    code="MISSING_SUPPLIER_TAX_ID",
                    severity=IssueSeverity.CRITICAL,
                    message="Supplier tax ID (Mã số thuế bên bán) is missing.",
                    field_path="supplier_tax_id",
                )
            )
        elif not self._is_valid_vietnamese_tax_id(invoice.supplier_tax_id):
            issues.append(
                MatchIssue(
                    code="INVALID_SUPPLIER_TAX_ID",
                    severity=IssueSeverity.CRITICAL,
                    message=f"Supplier tax ID '{invoice.supplier_tax_id}' does not conform to Vietnamese 10/13 digit format.",
                    field_path="supplier_tax_id",
                    actual_value=invoice.supplier_tax_id,
                )
            )
        elif len(invoice.supplier_tax_id.strip()[:10]) == 10 and not self._verify_mst_checksum(
            invoice.supplier_tax_id
        ):
            issues.append(
                MatchIssue(
                    code="TAX_ID_CHECKSUM_WARNING",
                    severity=IssueSeverity.WARNING,
                    message=f"Supplier tax ID '{invoice.supplier_tax_id}' does not match official Mod-11 checksum.",
                    field_path="supplier_tax_id",
                    actual_value=invoice.supplier_tax_id,
                )
            )

        if invoice.buyer_tax_id and invoice.buyer_tax_id.strip():
            if not self._is_valid_vietnamese_tax_id(invoice.buyer_tax_id):
                issues.append(
                    MatchIssue(
                        code="INVALID_BUYER_TAX_ID",
                        severity=IssueSeverity.CRITICAL,
                        message=f"Buyer tax ID '{invoice.buyer_tax_id}' does not conform to Vietnamese 10/13 digit format.",
                        field_path="buyer_tax_id",
                        actual_value=invoice.buyer_tax_id,
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

        # 2. Line arithmetic & VAT rate validation
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

            # Vietnamese VAT rate validation per line
            if line.tax_rate is not None and line.tax_rate >= Decimal("0.0000"):
                if line.tax_rate not in self._VALID_VAT_RATES:
                    issues.append(
                        MatchIssue(
                            code="INVALID_VAT_RATE",
                            severity=IssueSeverity.WARNING,
                            message=f"Line {line.line_no}: VAT rate {line.tax_rate}% is not a recognized Vietnamese statutory rate (0%, 5%, 8%, 10%, KCT).",
                            line_no=line.line_no,
                            field_path=f"lines[{line.line_no}].tax_rate",
                            actual_value=str(line.tax_rate),
                        )
                    )

            if (
                line.tax > Decimal("0.0000")
                and line.tax_rate is not None
                and line.tax_rate > Decimal("0.0000")
            ):
                expected_tax = (line.line_amount * line.tax_rate) / Decimal("100.0000")
                if abs(line.tax - expected_tax) > Decimal("1.0000"):
                    issues.append(
                        MatchIssue(
                            code="LINE_TAX_ARITHMETIC_MISMATCH",
                            severity=IssueSeverity.WARNING,
                            message=f"Line {line.line_no}: Tax amount {line.tax} does not match expected tax {expected_tax:.2f} based on rate {line.tax_rate}%.",
                            line_no=line.line_no,
                            field_path=f"lines[{line.line_no}].tax",
                            actual_value=str(line.tax),
                            expected_value=str(expected_tax),
                        )
                    )

        # 3. Subtotal vs line sum validation
        if invoice.lines and invoice.subtotal > Decimal("0.0000"):
            if abs(line_sum - invoice.subtotal) >= Decimal("1.0000"):
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
        ) >= Decimal("1.0000"):
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

        # 5. Tax breakdown vs total tax validation
        if invoice.tax_breakdown:
            calc_tax_breakdown_sum = sum(
                (tb.tax_amount for tb in invoice.tax_breakdown), Decimal("0.0000")
            )
            if abs(calc_tax_breakdown_sum - invoice.tax_total) >= Decimal("1.0000"):
                issues.append(
                    MatchIssue(
                        code="TAX_BREAKDOWN_MISMATCH",
                        severity=IssueSeverity.CRITICAL,
                        message=f"Sum of tax breakdown ({calc_tax_breakdown_sum}) does not equal total tax ({invoice.tax_total})",
                        field_path="tax_total",
                        actual_value=str(invoice.tax_total),
                        expected_value=str(calc_tax_breakdown_sum),
                    )
                )

        # 6. Currency validation
        if invoice.currency and invoice.currency.upper() != "VND":
            if invoice.exchange_rate is not None and invoice.exchange_rate <= Decimal("0.0000"):
                issues.append(
                    MatchIssue(
                        code="INVALID_EXCHANGE_RATE",
                        severity=IssueSeverity.WARNING,
                        message=f"Exchange rate for foreign currency {invoice.currency} must be greater than zero.",
                        field_path="exchange_rate",
                    )
                )

        # 7. Document-level parser issues propagation
        for p_issue in getattr(invoice, "parser_issues", []):
            is_critical = any(k in p_issue for k in ["MISMATCH", "ERROR", "AMBIGUOUS", "CONFLICT"])
            issues.append(
                MatchIssue(
                    code=p_issue,
                    severity=IssueSeverity.CRITICAL if is_critical else IssueSeverity.WARNING,
                    message=f"Phát hiện cảnh báo trích xuất tài liệu: {p_issue}",
                )
            )

        # 8. Line-level parser issues propagation
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

    def check_duplicates(
        self,
        invoice: InvoiceAggregate,
        existing_invoices: List[InvoiceAggregate],
    ) -> List[MatchIssue]:
        issues: List[MatchIssue] = []
        if not invoice.supplier_tax_id or not invoice.invoice_number:
            return issues

        inv_num = invoice.invoice_number.strip().lower()
        inv_tax = invoice.supplier_tax_id.strip()
        inv_series = (invoice.invoice_series or "").strip().lower()

        for other in existing_invoices:
            if str(other.id) == str(invoice.id):
                continue
            if (
                other.supplier_tax_id
                and other.supplier_tax_id.strip() == inv_tax
                and other.invoice_number
                and other.invoice_number.strip().lower() == inv_num
            ):
                other_series = (other.invoice_series or "").strip().lower()
                if not inv_series or not other_series or inv_series == other_series:
                    issues.append(
                        MatchIssue(
                            code="DUPLICATE_INVOICE",
                            severity=IssueSeverity.CRITICAL,
                            message=f"Duplicate invoice detected: supplier {inv_tax}, invoice {inv_num}, series {inv_series} matches invoice {other.id}.",
                            field_path="invoice_number",
                            actual_value=invoice.invoice_number,
                            expected_value=f"unique (matches {other.id})",
                        )
                    )
                    break
        return issues
