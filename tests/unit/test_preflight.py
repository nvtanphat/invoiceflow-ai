import pytest


def test_preflight_allows_valid_xml_and_pdf():
    from invoiceflow.application.ingestion.preflight import IngestionPreflight, PreflightError

    preflight = IngestionPreflight(max_size_bytes=1024 * 1024, max_pages=10)

    # Valid XML
    xml_bytes = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?><HDon><DLHDon></DLHDon></HDon>"
    meta = preflight.inspect_and_validate(filename="invoice.xml", content=xml_bytes)
    assert meta.detected_mime == "application/xml"
    assert meta.detected_kind == "xml"
    assert len(meta.sha256) == 64

    # Valid PDF magic header %PDF-
    pdf_bytes = b"%PDF-1.4\n%test\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    pdf_meta = preflight.inspect_and_validate(filename="invoice.pdf", content=pdf_bytes)
    assert pdf_meta.detected_mime == "application/pdf"
    assert pdf_meta.detected_kind == "pdf"


def test_preflight_rejects_mime_spoofing():
    from invoiceflow.application.ingestion.preflight import IngestionPreflight, PreflightError

    preflight = IngestionPreflight(max_size_bytes=1024 * 1024, max_pages=10)

    # File named .pdf but containing Windows executable MZ
    fake_pdf = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"
    with pytest.raises(PreflightError) as exc_info:
        preflight.inspect_and_validate(filename="invoice.pdf", content=fake_pdf)
    msg = str(exc_info.value).lower()
    assert "mime mismatch" in msg or "does not match" in msg or "disallowed" in msg


def test_preflight_rejects_oversized_file():
    from invoiceflow.application.ingestion.preflight import IngestionPreflight, PreflightError

    preflight = IngestionPreflight(max_size_bytes=100, max_pages=10)
    big_content = b"%PDF-1.4\n" + b"A" * 200
    with pytest.raises(PreflightError) as exc:
        preflight.inspect_and_validate(filename="large.pdf", content=big_content)
    assert "exceeds maximum allowed size" in str(exc.value)
