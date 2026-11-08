def test_document_router_routes_xml_and_pdf():
    from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute

    router = DocumentRouter()

    route_xml = router.decide_route(detected_kind="xml", file_size_bytes=1000)
    assert route_xml == ProcessingRoute.XML_DETERMINISTIC

    route_pdf_digital = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_digital",
    )
    assert route_pdf_digital == ProcessingRoute.PDF_DIGITAL

    route_pdf_scan = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_scan",
    )
    assert route_pdf_scan == ProcessingRoute.VISION_FALLBACK
