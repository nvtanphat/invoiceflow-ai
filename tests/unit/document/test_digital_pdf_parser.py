from decimal import Decimal
from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalPDFParser


def test_digital_pdf_parser_extracts_vietnamese_invoice_text():
    parser = DigitalPDFParser()
    text = (
        "HOA DON BAN HANG (SCAN)\n"
        "Ky hieu: 2C26TCC So: 0003412 Ngay: 2026-03-08\n"
        "Ben ban: Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội MST: 0105554321\n"
        "Ben mua: Công ty Cổ phần Thương mại Alpha VN MST: 0109998888\n"
        "Hang hoa: Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng [CLEAN-SET-01]\n"
        "So luong: 10.0000 Don gia: 850000.0000 Thue: 8.00%\n"
        "Tien hang: 8500000.0000 Thue GTGT: 680000.0000 Tong cong: 9180000.0000\n"
    )

    res = parser.parse(text)

    assert res.supplier_name == "Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội"
    assert res.supplier_tax_id == "0105554321"
    assert res.buyer_name == "Công ty Cổ phần Thương mại Alpha VN"
    assert res.buyer_tax_id == "0109998888"
    assert res.invoice_number == "0003412"
    assert res.invoice_series == "2C26TCC"
    assert res.issue_date == "2026-03-08"
    assert res.amount_payable == Decimal("9180000.0000")
    assert len(res.lines) == 1
    line = res.lines[0]
    assert line.sku == "CLEAN-SET-01"
    assert "Bộ dụng cụ" in line.description
    assert line.qty == Decimal("10.0000")
    assert line.unit_price == Decimal("850000.0000")
    assert line.line_amount == Decimal("8500000.0000")


def test_digital_pdf_parser_handles_empty_text():
    parser = DigitalPDFParser()
    res = parser.parse("")
    assert res.supplier_name is None
    assert res.supplier_tax_id is None
    assert len(res.lines) == 0
