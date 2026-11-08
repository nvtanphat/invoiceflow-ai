from decimal import Decimal
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DigitalExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int
    sku: Optional[str] = None
    description: str
    unit: Optional[str] = None
    qty: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal("0.0000")
    tax_rate: Optional[Decimal] = None
    line_amount: Decimal


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
    confidence: float = 0.0

    @property
    def is_confident(self) -> bool:
        return (
            bool(self.supplier_tax_id)
            and bool(self.invoice_number)
            and self.amount_payable > 0
            and len(self.lines) > 0
            and self.confidence >= 0.70
        )


class DigitalPDFParser:
    """Deterministic extractor for digital PDF invoices containing text layers."""

    def parse(self, text: str) -> DigitalInvoiceExtraction:
        if not text or not text.strip():
            return DigitalInvoiceExtraction()

        data: Dict[str, Any] = {"currency": "VND"}
        fields_found = 0

        # 1. Invoice Series
        m_series = re.search(r"(?:Ky hieu|Ký hiệu|Series)(?:\s*\([^)]*\))?:\s*([^\r\n]+)", text, re.IGNORECASE)
        if m_series:
            data["invoice_series"] = m_series.group(1).strip()
            fields_found += 1

        # 2. Invoice Number (preserving leading zeros as string)
        m_inv_no = re.search(r"(?:So|Số|Invoice No|No\.?)(?:\s*\([^)]*\))?:\s*([0-9]+)", text, re.IGNORECASE)
        if m_inv_no:
            data["invoice_number"] = m_inv_no.group(1).strip()
            fields_found += 1

        # 3. Issue Date
        m_date = re.search(
            r"(?:Ngay|Ngày|Date)(?:\s*\([^)]*\))?:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{2}/[0-9]{2}/[0-9]{4})",
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
        m_supp = re.search(r"(?:Don vi ban|Đơn vị bán|Supplier|Người bán)(?:\s*\([^)]*\))?:\s*([^\r\n]+)", text, re.IGNORECASE)
        if m_supp:
            data["supplier_name"] = m_supp.group(1).strip()
            fields_found += 1

        # 5. Buyer Name
        m_buyer = re.search(r"(?:Don vi mua|Đơn vị mua|Buyer|Người mua)(?:\s*\([^)]*\))?:\s*([^\r\n]+)", text, re.IGNORECASE)
        if m_buyer:
            data["buyer_name"] = m_buyer.group(1).strip()
            fields_found += 1

        # 6. Tax IDs (preserving leading zeros as string)
        tax_ids = re.findall(r"(?:Ma so thue|Mã số thuế|Tax ID)(?:\s*\([^)]*\))?:\s*([0-9-]{10,14})", text, re.IGNORECASE)
        if len(tax_ids) >= 1:
            data["supplier_tax_id"] = tax_ids[0].strip()
            fields_found += 1
        if len(tax_ids) >= 2:
            data["buyer_tax_id"] = tax_ids[1].strip()
            fields_found += 1

        # 7. Monetary Totals
        m_subtotal = re.search(r"(?:Cong tien hang|Cộng tiền hàng|Subtotal)(?:\s*\([^)]*\))?:\s*([0-9.,]+)", text, re.IGNORECASE)
        if m_subtotal:
            data["subtotal"] = self._parse_decimal(m_subtotal.group(1))
            fields_found += 1

        m_tax = re.search(r"(?:Tien thue GTGT|Tiền thuế GTGT|Tax Total)(?:\s*\([^)]*\))?:\s*([0-9.,]+)", text, re.IGNORECASE)
        if m_tax:
            data["tax_total"] = self._parse_decimal(m_tax.group(1))
            fields_found += 1

        m_total = re.search(r"(?:Tong cong|Tổng cộng|Total Amount)(?:\s*\([^)]*\))?:\s*([0-9.,]+)", text, re.IGNORECASE)
        if m_total:
            data["amount_payable"] = self._parse_decimal(m_total.group(1))
            fields_found += 1

        # 8. Multi-line Items Extraction
        lines: List[DigitalExtractedLine] = []
        # Pattern matches description, optional [SKU], quantity, unit price, tax rate%, line amount
        # Using flexible whitespace \s+ to handle newlines, spaces, or merged table cells
        pattern_lines = re.compile(
            r"([^\r\n\[]+?)\s*(?:\[([A-Z0-9_-]+)\])?\s+([0-9.,]+)\s+([0-9.,]+)\s+([0-9.,]+)%\s+([0-9.,]+)",
            re.MULTILINE,
        )

        for idx, m_line in enumerate(pattern_lines.finditer(text), start=1):
            desc = m_line.group(1).strip()
            # Ignore table column header matches
            if any(h in desc.lower() for h in ["hang hoa", "dich vu", "description", "stt", "item"]):
                continue
            sku = m_line.group(2).strip() if m_line.group(2) else None
            qty = self._parse_decimal(m_line.group(3), is_qty=True)
            unit_price = self._parse_decimal(m_line.group(4))
            tax_rate = self._parse_decimal(m_line.group(5))
            line_amount = self._parse_decimal(m_line.group(6))

            # Accounting consistency self-healing: if qty was parsed with thousand-multiplier
            if qty > 0 and unit_price > 0 and line_amount > 0:
                if qty * unit_price != line_amount and (qty / Decimal("1000")) * unit_price == line_amount:
                    qty = qty / Decimal("1000")

            lines.append(
                DigitalExtractedLine(
                    line_no=idx,
                    sku=sku,
                    description=desc,
                    qty=qty,
                    unit_price=unit_price,
                    tax_rate=tax_rate,
                    line_amount=line_amount,
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
            confidence=confidence,
        )

    def _parse_decimal(self, val: Any, is_qty: bool = False) -> Decimal:
        if not val:
            return Decimal("0.0000")
        s = str(val).strip()

        # Handle Vietnamese and International monetary formats
        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                # 12.000.000,00 -> standard VN notation
                s = s.replace(".", "").replace(",", ".")
            else:
                # 12,000,000.00 -> US notation
                s = s.replace(",", "")
        elif "." in s:
            parts = s.split(".")
            if is_qty and len(parts) == 2:
                # Quantities with a single dot are decimal representations e.g. 200.000 or 5.5
                s = f"{parts[0]}.{parts[1]}"
            elif len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                # Standard VN thousand separators e.g. 12.000.000 or 60.000
                s = s.replace(".", "")
        elif "," in s:
            parts = s.split(",")
            if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")

        clean = re.sub(r"[^\d.-]", "", s)
        try:
            return Decimal(clean)
        except Exception:
            return Decimal("0.0000")
