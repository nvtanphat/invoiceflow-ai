from decimal import Decimal
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from invoiceflow.domain.documents.value_parsing import parse_vn_decimal
from invoiceflow.infrastructure.document.text_normalization import normalize_extracted_text
from invoiceflow.infrastructure.document.totals_extractor import extract_invoice_totals


class DigitalExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int
    sku: Optional[str] = None
    description: str
    unit: Optional[str] = None
    raw_qty: Optional[str] = None
    qty: Decimal
    raw_unit_price: Optional[str] = None
    unit_price: Decimal
    discount: Decimal = Decimal("0.0000")
    tax_rate: Optional[Decimal] = None
    raw_line_amount: Optional[str] = None
    line_amount: Decimal
    issues: List[str] = Field(default_factory=list)


class DigitalInvoiceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_tax_id: Optional[str] = None
    supplier_name: Optional[str] = None
    buyer_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_series: Optional[str] = None
    issue_date: Optional[str] = None
    currency: str = "VND"
    subtotal: Decimal = Decimal("0.0000")
    tax_total: Decimal = Decimal("0.0000")
    amount_payable: Decimal = Decimal("0.0000")
    lines: List[DigitalExtractedLine] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    @property
    def is_confident(self) -> bool:
        if bool(self.issues) or any(bool(line.issues) for line in self.lines):
            return False
        return (
            bool(self.supplier_tax_id)
            and bool(self.invoice_number)
            and self.amount_payable > 0
            and len(self.lines) > 0
            and self.confidence >= 0.70
        )


class DigitalPDFParser:
    """Deterministic extractor for digital PDF invoices containing text layers.

    Preserves raw vs normalized values, flags arithmetic/format ambiguities,
    and strictly avoids arbitrary data mutation or false self-healing.
    """

    def parse(self, text: str) -> DigitalInvoiceExtraction:
        if not text or not text.strip():
            return DigitalInvoiceExtraction()

        text = normalize_extracted_text(text)

        data: Dict[str, Any] = {"currency": "VND"}
        fields_found = 0
        doc_issues: List[str] = []

        # 1. Invoice Series
        m_series = re.search(
            r"(?:Ky hieu mau so|Ký hiệu mẫu số|Mẫu số - Ký hiệu|Ky hieu|Ký hiệu|Series)(?:\s*\([^)]*\))?[:\s]+([A-Z0-9/_-]+)",
            text,
            re.IGNORECASE,
        )
        if m_series:
            data["invoice_series"] = m_series.group(1).strip()
            fields_found += 1

        # 2. Invoice Number (preserving leading zeros as string)
        m_inv_no = re.search(
            r"(?<!mau\s)(?<!mẫu\s)(?<!ky hieu\s)(?<!ký hiệu\s)(?:\bSố hóa đơn\b|\bSo hoa don\b|\bHóa đơn số\b|\bHoa don so\b|\bSố HĐ\b|\bSo HĐ\b|\bInvoice No\b|\bNo\.?|\bSố\b|\bSo\b)(?:\s*\([^)]*\))?[:\s]+([0-9]+)",
            text,
            re.IGNORECASE,
        )
        if m_inv_no:
            data["invoice_number"] = m_inv_no.group(1).strip()
            fields_found += 1

        # 3. Issue Date (natural Vietnamese or standard numeric)
        m_nat_date = re.search(
            r"(?:Ngay|Ngày)(?:\s*\([^)]*\))?\s*([0-9]{1,2})\s*(?:thang|tháng)\s*([0-9]{1,2})\s*(?:nam|năm)\s*([0-9]{4})",
            text,
            re.IGNORECASE,
        )
        if m_nat_date:
            day = m_nat_date.group(1).zfill(2)
            month = m_nat_date.group(2).zfill(2)
            year = m_nat_date.group(3)
            data["issue_date"] = f"{year}-{month}-{day}"
            fields_found += 1
        else:
            m_date = re.search(
                r"(?:Ngay|Ngày|Date)(?:\s*\([^)]*\))?[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{2}/[0-9]{2}/[0-9]{4})",
                text,
                re.IGNORECASE,
            )
            if m_date:
                raw_d = m_date.group(1).strip()
                if "/" in raw_d:
                    parts = raw_d.split("/")
                    raw_d = f"{parts[2]}-{parts[1]}-{parts[0]}"
                data["issue_date"] = raw_d
                fields_found += 1

        # 4. Supplier Name
        m_supp = re.search(
            r"(?:Don vi ban|Đơn vị bán|Supplier|Người bán|Ben ban|Bên bán)(?:\s*\([^)]*\))?:\s*([^\r\n]+)",
            text,
            re.IGNORECASE,
        )
        if m_supp:
            raw_supp = m_supp.group(1).strip()
            clean_supp = re.sub(
                r"[\s-]+(?:MST|Ma so thue|Mã số thuế).*$", "", raw_supp, flags=re.IGNORECASE
            ).strip()
            data["supplier_name"] = clean_supp
            fields_found += 1

        # 5. Buyer Name
        m_buyer = re.search(
            r"(?:Don vi mua|Đơn vị mua|Buyer|Người mua|Ben mua|Bên mua)(?:\s*\([^)]*\))?:\s*([^\r\n]+)",
            text,
            re.IGNORECASE,
        )
        if m_buyer:
            raw_buyer = m_buyer.group(1).strip()
            clean_buyer = re.sub(
                r"[\s-]+(?:MST|Ma so thue|Mã số thuế).*$", "", raw_buyer, flags=re.IGNORECASE
            ).strip()
            data["buyer_name"] = clean_buyer
            fields_found += 1

        # 6. Tax IDs (contextual: Seller vs Buyer)
        m_supp_tax = re.search(
            r"(?:Don vi ban|Đơn vị bán|Người bán|Bên bán|Seller|Supplier)[^\r\n]*?(?:MST|Ma so thue|Mã số thuế|Tax ID)[:\s]+([0-9]{10}(?:-[0-9]{3})?)",
            text,
            re.IGNORECASE,
        )
        m_buyer_tax = re.search(
            r"(?:Don vi mua|Đơn vị mua|Người mua|Bên mua|Buyer|Khách hàng)[^\r\n]*?(?:MST|Ma so thue|Mã số thuế|Tax ID)[:\s]+([0-9]{10}(?:-[0-9]{3})?)",
            text,
            re.IGNORECASE,
        )
        if m_supp_tax:
            data["supplier_tax_id"] = m_supp_tax.group(1).strip()
            fields_found += 1
        if m_buyer_tax:
            data["buyer_tax_id"] = m_buyer_tax.group(1).strip()
            fields_found += 1

        if not data.get("supplier_tax_id") or not data.get("buyer_tax_id"):
            tax_ids = re.findall(
                r"(?:Ma so thue|Mã số thuế|Tax ID|MST)(?:\s*\([^)]*\))?[:\s]+([0-9-]{10,14})",
                text,
                re.IGNORECASE,
            )
            if not data.get("supplier_tax_id") and len(tax_ids) >= 1:
                data["supplier_tax_id"] = tax_ids[0].strip()
                fields_found += 1
            if not data.get("buyer_tax_id") and len(tax_ids) >= 2:
                data["buyer_tax_id"] = tax_ids[1].strip()
                fields_found += 1

        # 7. Monetary Totals
        totals = extract_invoice_totals(text)
        for field_name in ("subtotal", "tax_total", "amount_payable"):
            total = totals.get(field_name)
            if total is None:
                # Left at zero for the aggregate, but flagged so it is never taken as read.
                doc_issues.append(f"{field_name.upper()}_NOT_FOUND")
                continue
            value, parse_issue = parse_vn_decimal(total.raw)
            data[field_name] = value
            if parse_issue:
                doc_issues.append(f"{field_name.upper()}_{parse_issue}")
            fields_found += 1

        # 8. Multi-line Items Extraction
        lines: List[DigitalExtractedLine] = []
        pattern_lines = re.compile(
            r"([^\r\n\[]+?)\s*(?:\[([A-Z0-9_-]+)\])?\s*([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)%\s+([0-9.,]+)",
            re.MULTILINE,
        )

        for idx, m_line in enumerate(pattern_lines.finditer(text), start=1):
            desc = m_line.group(1).strip()
            # Ignore table column header matches
            if any(
                h in desc.lower() for h in ["hang hoa", "dich vu", "description", "stt", "item"]
            ):
                continue
            sku = m_line.group(2).strip() if m_line.group(2) else None
            if not sku:
                m_sku = re.search(r"\[([A-Z0-9_-]+)\]", desc)
                if m_sku:
                    sku = m_sku.group(1)
                    desc = re.sub(r"\s*\[[A-Z0-9_-]+\]\s*", "", desc).strip()
                else:
                    m_unbr = re.search(r"\b([A-Z0-9]+(?:-[A-Z0-9]+)+)\b", desc)
                    if m_unbr:
                        cand = m_unbr.group(1)
                        if not re.match(r"^\d{4}-\d{2}-\d{2}$", cand) and not re.match(
                            r"^\d{10}-\d{3}$", cand
                        ):
                            sku = cand
                            desc = desc.replace(cand, "").strip(" -:,")
            raw_qty = m_line.group(3).strip()
            raw_unit_price = m_line.group(4).strip()
            raw_tax_rate = m_line.group(5).strip()
            raw_line_amount = m_line.group(6).strip()

            qty, qty_issue = parse_vn_decimal(raw_qty, is_qty=True)
            unit_price, price_issue = parse_vn_decimal(raw_unit_price)
            tax_rate, _ = parse_vn_decimal(raw_tax_rate)
            line_amount, amount_issue = parse_vn_decimal(raw_line_amount)

            line_issues: List[str] = []
            if qty_issue:
                line_issues.append(qty_issue)
            if price_issue:
                line_issues.append(price_issue)
            if amount_issue:
                line_issues.append(amount_issue)

            # Strict validation check: do NOT mutate data, flag discrepancy if present
            expected_amount = qty * unit_price
            if abs(line_amount - expected_amount) > Decimal("1.0000"):
                line_issues.append("ARITHMETIC_MISMATCH")

            lines.append(
                DigitalExtractedLine(
                    line_no=idx,
                    sku=sku,
                    description=desc,
                    raw_qty=raw_qty,
                    qty=qty,
                    raw_unit_price=raw_unit_price,
                    unit_price=unit_price,
                    discount=Decimal("0.0000"),
                    tax_rate=tax_rate,
                    raw_line_amount=raw_line_amount,
                    line_amount=line_amount,
                    issues=line_issues,
                )
            )

        if not lines:
            pattern_labeled = re.compile(
                r"([^\r\n\[]+?)\s*(?:\[([A-Z0-9_-]+)\])?\s+(?:SL|So luong|Số lượng):\s*([0-9.,]+)\s+(?:Don gia|Đơn giá):\s*([0-9.,]+)",
                re.IGNORECASE,
            )
            for idx, m_line in enumerate(pattern_labeled.finditer(text), start=1):
                desc = m_line.group(1).strip()
                if any(
                    h in desc.lower() for h in ["hang hoa", "dich vu", "description", "stt", "item"]
                ):
                    continue
                sku = m_line.group(2).strip() if m_line.group(2) else None
                if not sku:
                    m_sku = re.search(r"\[([A-Z0-9_-]+)\]", desc)
                    if m_sku:
                        sku = m_sku.group(1)
                        desc = re.sub(r"\s*\[[A-Z0-9_-]+\]\s*", "", desc).strip()
                    else:
                        m_unbr = re.search(r"\b([A-Z0-9]+(?:-[A-Z0-9]+)+)\b", desc)
                        if m_unbr:
                            cand = m_unbr.group(1)
                            if not re.match(r"^\d{4}-\d{2}-\d{2}$", cand) and not re.match(
                                r"^\d{10}-\d{3}$", cand
                            ):
                                sku = cand
                                desc = desc.replace(cand, "").strip(" -:,")
                raw_qty = m_line.group(3).strip()
                raw_price = m_line.group(4).strip()
                qty, qty_issue = parse_vn_decimal(raw_qty, is_qty=True)
                unit_price, price_issue = parse_vn_decimal(raw_price)
                line_amount = qty * unit_price
                line_issues = []
                if qty_issue:
                    line_issues.append(qty_issue)
                if price_issue:
                    line_issues.append(price_issue)
                lines.append(
                    DigitalExtractedLine(
                        line_no=idx,
                        sku=sku,
                        description=desc,
                        raw_qty=raw_qty,
                        qty=qty,
                        raw_unit_price=raw_price,
                        unit_price=unit_price,
                        discount=Decimal("0.0000"),
                        tax_rate=None,
                        raw_line_amount=str(line_amount),
                        line_amount=line_amount,
                        issues=line_issues,
                    )
                )

        if not lines:
            m_item = re.search(
                r"(?:Hang hoa|Hàng hóa|Description|Ten hang)(?:\s*\([^)]*\))?:\s*([^\r\n]+)",
                text,
                re.IGNORECASE,
            )
            m_qty = re.search(
                r"(?:So luong|Số lượng|Qty)(?:\s*\([^)]*\))?:\s*([0-9.,]+)",
                text,
                re.IGNORECASE,
            )
            m_price = re.search(
                r"(?:Don gia|Đơn giá|Price)(?:\s*\([^)]*\))?:\s*([0-9.,]+)",
                text,
                re.IGNORECASE,
            )
            m_amt = re.search(
                r"(?:Tien hang|Tiền hàng|Amount)(?:\s*\([^)]*\))?:\s*([0-9.,]+)",
                text,
                re.IGNORECASE,
            )
            if m_item and m_qty and m_price:
                item_desc = m_item.group(1).strip()
                item_sku = None
                m_sku = re.search(r"\[([A-Z0-9_-]+)\]", item_desc)
                if m_sku:
                    item_sku = m_sku.group(1)
                    item_desc = re.sub(r"\s*\[[A-Z0-9_-]+\]\s*", "", item_desc).strip()
                qty_val, q_err = parse_vn_decimal(m_qty.group(1), is_qty=True)
                price_val, p_err = parse_vn_decimal(m_price.group(1))
                amt_val = qty_val * price_val
                if m_amt:
                    parsed_a, _ = parse_vn_decimal(m_amt.group(1))
                    if parsed_a > Decimal("0.0000"):
                        amt_val = parsed_a
                item_issues = []
                if q_err:
                    item_issues.append(q_err)
                if p_err:
                    item_issues.append(p_err)
                lines.append(
                    DigitalExtractedLine(
                        line_no=1,
                        sku=item_sku,
                        description=item_desc,
                        raw_qty=m_qty.group(1).strip(),
                        qty=qty_val,
                        raw_unit_price=m_price.group(1).strip(),
                        unit_price=price_val,
                        discount=Decimal("0.0000"),
                        tax_rate=None,
                        raw_line_amount=m_amt.group(1).strip() if m_amt else str(amt_val),
                        line_amount=amt_val,
                        issues=item_issues,
                    )
                )

        if lines:
            fields_found += 2

        # Weighted confidence calibration: Core header fields (60%) + Lines (40%)
        header_ratio = min(fields_found / 8.0, 1.0)
        lines_ratio = 1.0 if lines else 0.0
        confidence = round(0.6 * header_ratio + 0.4 * lines_ratio, 2)

        return DigitalInvoiceExtraction(
            supplier_tax_id=data.get("supplier_tax_id"),
            supplier_name=data.get("supplier_name"),
            buyer_tax_id=data.get("buyer_tax_id"),
            buyer_name=data.get("buyer_name"),
            invoice_number=data.get("invoice_number"),
            invoice_series=data.get("invoice_series"),
            issue_date=data.get("issue_date"),
            currency=data.get("currency", "VND"),
            subtotal=data.get("subtotal", Decimal("0.0000")),
            tax_total=data.get("tax_total", Decimal("0.0000")),
            amount_payable=data.get("amount_payable", Decimal("0.0000")),
            lines=lines,
            issues=doc_issues,
            confidence=confidence,
        )
