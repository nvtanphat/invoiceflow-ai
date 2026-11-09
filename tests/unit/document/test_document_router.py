def test_document_router_routes_xml_and_pdf():
    from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute

    router = DocumentRouter()

    route_xml = router.decide_route(detected_kind="xml", file_size_bytes=1000)
    assert route_xml == ProcessingRoute.XML_DETERMINISTIC

    route_xml_canonical = router.decide_route(detected_kind="xml_invoice", file_size_bytes=1000)
    assert route_xml_canonical == ProcessingRoute.XML_DETERMINISTIC

    route_pdf_digital = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_digital",
    )
    assert route_pdf_digital == ProcessingRoute.PDF_DIGITAL

    route_pdf_digital_canonical = router.decide_route(
        detected_kind="digital_pdf",
        file_size_bytes=50000,
        pdf_classification="digital_pdf",
    )
    assert route_pdf_digital_canonical == ProcessingRoute.PDF_DIGITAL

    route_pdf_scan = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_scan",
    )
    assert route_pdf_scan in (
        ProcessingRoute.DOCLING_OCR_STRUCTURED,
        ProcessingRoute.VISION_FALLBACK,
    )

    route_pdf_scan_canonical = router.decide_route(
        detected_kind="scanned_pdf",
        file_size_bytes=50000,
        pdf_classification="scanned_pdf",
    )
    assert route_pdf_scan_canonical == ProcessingRoute.DOCLING_OCR_STRUCTURED

    route_pdf_mixed = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="mixed_pdf",
    )
    assert route_pdf_mixed == ProcessingRoute.DOCLING_OCR_STRUCTURED

    route_pdf_difficult = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_scan",
        is_difficult=True,
    )
    assert route_pdf_difficult == ProcessingRoute.VISION_FALLBACK
