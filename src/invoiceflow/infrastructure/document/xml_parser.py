from datetime import date, datetime
from decimal import Decimal
import io
import re
from typing import Optional
from uuid import UUID
from xml.etree.ElementTree import Element as XmlElement
import defusedxml.ElementTree as ET

from invoiceflow.domain.invoices.models import (
    FieldEvidence,
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
    VerificationStatus,
)


class XMLParsingError(Exception):
    pass


class SecureXMLParser:
    """Hardened XML Parser for Vietnamese electronic invoices conforming to TT78/ND123/ND254."""

    def parse_invoice_xml(
        self,
        tenant_id: UUID | str,
        document_id: UUID | str,
        xml_content: bytes,
    ) -> InvoiceAggregate:
        if not xml_content:
            raise XMLParsingError("Empty XML content.")

        # Defense-in-depth: check for DOCTYPE entities before parsing
        header_sample = xml_content[:1024].lower()
        if b"<!entity" in header_sample or b"<!doctype" in header_sample:
            raise XMLParsingError("Security alert: DOCTYPE and ENTITY definitions are forbidden.")

        try:
            tree = ET.parse(io.BytesIO(xml_content))
            root = tree.getroot()
        except Exception as e:
            raise XMLParsingError(f"Failed to parse XML: {str(e)}") from e

        # Extract general header info
        tt_chung = self._find_element(root, ["DLHDon", "TTChung"], ["TTChung"])
        invoice_series = self._get_text(tt_chung, ["KHHDon", "KHMSHDon"])
        invoice_number = self._get_text(tt_chung, ["SHDon"])
        issue_date_str = self._get_text(tt_chung, ["NLap", "NgayLap"])
        issue_date = self._parse_date(issue_date_str)
        currency = self._get_text(tt_chung, ["DVTTe"]) or "VND"

        # Supplier info
        n_ban = self._find_element(root, ["DLHDon", "NDHDon", "NBan"], ["NBan"])
        supplier_name = self._get_text(n_ban, ["Ten", "TenNBan"])
        supplier_tax_id = self._get_text(n_ban, ["MST", "MSTNBan"])

        # Buyer info
        n_mua = self._find_element(root, ["DLHDon", "NDHDon", "NMua"], ["NMua"])
        buyer_name = self._get_text(n_mua, ["Ten", "TenNMua"])
        buyer_tax_id = self._get_text(n_mua, ["MST", "MSTNMua"])

        # Total amounts
        t_toan = self._find_element(root, ["DLHDon", "NDHDon", "TToan"], ["TToan"])
        subtotal = self._parse_decimal(self._get_text(t_toan, ["TgTCThue", "TongTienChuaThue"]))
        tax_total = self._parse_decimal(self._get_text(t_toan, ["TgTThue", "TongTienThue"]))
        amount_payable = self._parse_decimal(
            self._get_text(t_toan, ["TgTTTBSo", "TongTienThanhToan"])
        )

        # Line items
        lines: list[InvoiceLine] = []
        dshhdvu = self._find_element(root, ["DLHDon", "NDHDon", "DSHHDVu"], ["DSHHDVu"])
        if dshhdvu is not None:
            line_no = 1
            for child in dshhdvu:
                if child.tag.endswith("HHDVu") or child.tag.endswith("Item"):
                    desc = self._get_text(child, ["THHDVu", "TenHHDVu"]) or f"Item {line_no}"
                    sku = self._get_text(child, ["MHHDVu", "MaHHDVu"])
                    if not sku and "[" in desc and "]" in desc:
                        m_sku = re.search(r"\[([A-Za-z0-9_-]+)\]", desc)
                        if m_sku:
                            sku = m_sku.group(1)
                    unit = self._get_text(child, ["DVTinh"])
                    qty = self._parse_decimal(
                        self._get_text(child, ["SLuong", "SoLuong"])
                    ) or Decimal("1.0000")
                    price = self._parse_decimal(self._get_text(child, ["DGia", "DonGia"]))
                    discount = self._parse_decimal(self._get_text(child, ["STCKhau", "TienCK"]))
                    line_amount = self._parse_decimal(
                        self._get_text(child, ["ThTien", "ThanhTien"])
                    )

                    tax_rate_str = self._get_text(child, ["TSuat", "ThueSuat"])
                    tax_rate = self._parse_tax_rate(tax_rate_str)
                    tax = self._parse_decimal(self._get_text(child, ["TThue", "TienThue"]))

                    lines.append(
                        InvoiceLine(
                            line_no=line_no,
                            sku_ref=sku,
                            description=desc,
                            unit=unit,
                            qty=qty,
                            unit_price=price,
                            discount=discount,
                            tax_rate=tax_rate,
                            tax=tax,
                            line_amount=line_amount
                            if line_amount > Decimal("0")
                            else (qty * price - discount),
                        )
                    )
                    line_no += 1

        # Check digital signature presence (marked unverified until cryptographic certificate check)
        signature_el = self._find_element(root, ["DSCKS"], ["Signature"])
        sig_status = (
            VerificationStatus.UNVERIFIED
            if signature_el is not None
            else VerificationStatus.NOT_CHECKED
        )

        evidence = [
            FieldEvidence(
                field_path="amount_payable",
                source_kind="xml",
                raw_value=str(amount_payable),
                normalized_value=str(amount_payable),
                confidence=1.0,
                extractor="xml_deterministic",
            )
        ]

        return InvoiceAggregate(
            tenant_id=UUID(str(tenant_id)),
            document_id=UUID(str(document_id)),
            revision=1,
            status=InvoiceStatus.READY_FOR_REVIEW,
            supplier_tax_id=supplier_tax_id,
            supplier_name=supplier_name,
            buyer_tax_id=buyer_tax_id,
            buyer_name=buyer_name,
            invoice_number=invoice_number,
            invoice_series=invoice_series,
            issue_date=issue_date,
            currency=currency,
            subtotal=subtotal,
            tax_total=tax_total,
            amount_payable=amount_payable,
            lines=lines,
            evidence=evidence,
            signature_status=sig_status,
            tax_authority_status=VerificationStatus.NOT_CHECKED,
        )

    def _find_element(self, root: XmlElement, *paths: list[str]) -> Optional[XmlElement]:
        for path in paths:
            curr: Optional[XmlElement] = root
            for segment in path:
                if curr is None:
                    break
                found = None
                for child in curr:
                    clean_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if clean_tag == segment:
                        found = child
                        break
                curr = found
            if curr is not None:
                return curr
        return None

    def _get_text(self, element: Optional[XmlElement], tags: list[str]) -> Optional[str]:
        if element is None:
            return None
        for tag in tags:
            for child in element:
                clean_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if clean_tag == tag and child.text:
                    return child.text.strip()
        return None

    def _parse_date(self, val: Optional[str]) -> Optional[date]:
        if not val:
            return None
        # Support formats: YYYY-MM-DD or DD/MM/YYYY
        clean = val.strip()
        try:
            return datetime.strptime(clean[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
        try:
            return datetime.strptime(clean[:10], "%d/%m/%Y").date()
        except ValueError:
            return None

    def _parse_decimal(self, val: Optional[str]) -> Decimal:
        if not val:
            return Decimal("0.0000")
        clean = re.sub(r"[^\d.-]", "", val.replace(",", "."))
        try:
            return Decimal(clean)
        except Exception:
            return Decimal("0.0000")

    def _parse_tax_rate(self, val: Optional[str]) -> Optional[Decimal]:
        if not val:
            return None
        clean = val.replace("%", "").strip()
        try:
            return Decimal(clean)
        except Exception:
            return None
