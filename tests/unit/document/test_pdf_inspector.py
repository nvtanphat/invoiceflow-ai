import fitz
import pytest


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
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector

    inspector = PDFInspector()
    report = inspector.inspect(sample_digital_pdf_bytes)

    assert report.page_count == 1
    assert report.is_encrypted is False
    assert report.classification == "pdf_digital"
    assert report.has_sufficient_text is True
    assert "HOA DON" in report.extracted_sample_text
    assert "INV-00123" in report.extracted_sample_text


def test_pdf_inspector_rejects_corrupted_pdf():
    from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector, PDFInspectionError

    inspector = PDFInspector()
    with pytest.raises(PDFInspectionError):
        inspector.inspect(b"%PDF-1.4 corrupt junk trailer broken %%EOF")
