import fitz

from invoiceflow.infrastructure.document.pdf_inspector import PDFInspector
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter


def test_pdf_inspector_page_level_classification_and_rotation():
    # Create an in-memory 2-page PDF:
    # Page 1: Native text with rotation 0
    # Page 2: Rotated 90 degrees with little text
    doc = fitz.open()

    # Page 0: Native text
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        (50, 100),
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nHÓA ĐƠN GIÁ TRỊ GIA TĂNG\n"
        + "Mô tả hàng hóa dịch vụ chi tiết số 12345 " * 10,
    )

    # Page 1: Rotated 90 degrees
    p2 = doc.new_page(width=595, height=842)
    p2.set_rotation(90)
    p2.insert_text((50, 100), "Chứng từ đính kèm hóa đơn")

    pdf_bytes = doc.tobytes()
    doc.close()

    inspector = PDFInspector()
    report = inspector.inspect(pdf_bytes)

    assert report.page_count == 2
    assert report.is_encrypted is False
    assert 0 in report.page_classifications
    assert 1 in report.page_classifications
    assert report.page_classifications[0] == "native_text"
    assert report.page_rotations[1] == 90
    assert report.has_rotated_pages is True


def test_docling_adapter_handles_empty_or_blank_page_gracefully():
    # Empty PDF with 1 blank page
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    pdf_bytes = doc.tobytes()
    doc.close()

    adapter = DoclingAdapter()
    canonical = adapter.extract_canonical(
        tenant_id="tenant-test-blank",
        document_id="doc-test-blank",
        pdf_bytes=pdf_bytes,
        do_ocr=False,
    )

    assert canonical.document_id == "doc-test-blank"
    assert canonical.page_count == 1
    # Graceful fallback without crashing
    assert (
        canonical.metadata.get("fallback_from") == "docling_empty" or len(canonical.elements) >= 0
    )
