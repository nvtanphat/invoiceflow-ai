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

        # 2. Invoice Number
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

        # 6. Tax IDs
        tax_ids = re.findall(r"(?:Ma so thue|Mã số thuế|Tax ID)(?:\s*\([^)]*\))?:\s*(\d{10,14})", text, re.IGNORECASE)
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

        # 8. Line Items
        lines: List[DigitalExtractedLine] = []
        # Pattern matching table row: Description [SKU] \n Qty \n Unit Price \n Tax Rate% \n Line Amount
        m_line = re.search(
            r"([^\r\n]+)\[([A-Z0-9_-]+)\]\s*\n\s*([0-9.,]+)\s*\n\s*([0-9.,]+)\s*\n\s*([0-9.,]+)%\s*\n\s*([0-9.,]+)",
            text,
        )
        if m_line:
            desc = m_line.group(1).strip()
            sku = m_line.group(2).strip()
            qty = self._parse_decimal(m_line.group(3))
            unit_price = self._parse_decimal(m_line.group(4))
            tax_rate = self._parse_decimal(m_line.group(5))
            line_amount = self._parse_decimal(m_line.group(6))
            lines.append(
                DigitalExtractedLine(
                    line_no=1,
                    sku=sku,
                    description=desc,
                    qty=qty,
                    unit_price=unit_price,
                    tax_rate=tax_rate,
                    line_amount=line_amount,
                )
            )
            fields_found += 2

        confidence = round(min(fields_found / 10.0, 1.0), 2)

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

    def _parse_decimal(self, val: Any) -> Decimal:
        if not val:
            return Decimal("0.0000")
        clean = re.sub(r"[^\d.-]", "", str(val).replace(",", "."))
        try:
            return Decimal(clean)
        except Exception:
            return Decimal("0.0000")
