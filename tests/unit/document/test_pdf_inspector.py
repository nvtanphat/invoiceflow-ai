from decimal import Decimal
import fitz
import pytest

from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser
from invoiceflow.infrastructure.document.pdf_inspector import PDFInspectionError, PDFInspector


@pytest.fixture
def sample_digital_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "HOA DON GIA TRI GIA TANG", fontsize=16)
    page.insert_text((50, 130), "So hoa don: INV-00123", fontsize=12)
    page.insert_text((50, 160), "Tong tien thanh toan: 1.500.000 VND", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_pdf_inspector_inspects_digital_pdf(sample_digital_pdf_bytes):
    inspector = PDFInspector()
    report = inspector.inspect(sample_digital_pdf_bytes)

    assert report.page_count == 1
    assert report.is_encrypted is False
    assert report.classification == "pdf_digital"
    assert report.has_sufficient_text is True
    assert "HOA DON" in report.extracted_sample_text
    assert "INV-00123" in report.extracted_sample_text


def test_pdf_inspector_rejects_corrupted_pdf():
    inspector = PDFInspector()
    with pytest.raises(PDFInspectionError):
        inspector.inspect(b"%PDF-1.4 corrupt junk trailer broken %%EOF")


def test_digital_pdf_parser_deterministic():
    sample_text = """
    Ky hieu (Series): 1C26TBB
    So (Invoice No): 0008890
    Ngay (Date): 2026-03-05
    Don vi ban (Supplier): Cong ty CP Giay & Van phong pham Mien Nam
    Ma so thue (Tax ID): 0309876543
    Don vi mua (Buyer): Cong ty Co phan Thuong mai Alpha VN
    Ma so thue (Tax ID): 0109998888
    Cong tien hang (Subtotal): 12000000.0000
    Tien thue GTGT (Tax Total): 960000.0000
    Tong cong (Total Amount): 12960000.0000
    Giay photocopy Double A A4 70gsm [PAPER-A4-70]
    200.0000
    60000.0000
    8.00%
    12000000.0000
    """
    parser = DigitalPDFParser()
    res = parser.parse(sample_text)

    assert res.is_confident is True
    assert res.supplier_tax_id == "0309876543"
    assert res.buyer_tax_id == "0109998888"
    assert res.invoice_number == "0008890"
    assert res.amount_payable == Decimal("12960000.0000")
    assert len(res.lines) == 1
    assert res.lines[0].sku == "PAPER-A4-70"
    assert res.lines[0].qty == Decimal("200.0000")


def test_digital_pdf_parser_multi_line_and_vietnamese_currency_format():
    sample_text = """
    Ký hiệu: 2C26TBB
    Số: 0008899
    Ngày: 06/03/2026
    Đơn vị bán: Công ty CP Giấy Miền Nam
    Mã số thuế: 0309876543
    Đơn vị mua: Công ty Cổ phần Alpha VN
    Mã số thuế: 0109998888
    Cộng tiền hàng: 25.000.000
    Tiền thuế GTGT: 2.000.000
    Tổng cộng: 27.000.000
    Giấy photocopy Double A A4 70gsm [PAPER-A4-70] 200 60.000 8% 12.000.000
    Bút bi Thiên Long 0.5mm [PEN-TL-05] 500 26.000 8% 13.000.000
    """
    parser = DigitalPDFParser()
    res = parser.parse(sample_text)

    assert res.is_confident is True
    assert res.invoice_number == "0008899"
    assert res.supplier_tax_id == "0309876543"
    assert res.issue_date == "2026-03-06"
    assert res.subtotal == Decimal("25000000")
    assert res.amount_payable == Decimal("27000000")

    assert len(res.lines) == 2
    assert res.lines[0].sku == "PAPER-A4-70"
    assert res.lines[0].qty == Decimal("200")
    assert res.lines[0].unit_price == Decimal("60000")
    assert res.lines[0].line_amount == Decimal("12000000")

    assert res.lines[1].sku == "PEN-TL-05"
    assert res.lines[1].qty == Decimal("500")
    assert res.lines[1].unit_price == Decimal("26000")
    assert res.lines[1].line_amount == Decimal("13000000")
