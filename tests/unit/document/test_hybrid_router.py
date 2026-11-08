from invoiceflow.application.processing.document_router import DocumentRouter, ProcessingRoute


def test_hybrid_router_selects_optimal_routes():
    router = DocumentRouter()

    # 1. XML document -> XML deterministic (Zero LLM, Zero OCR)
    r_xml = router.decide_route(detected_kind="xml", file_size_bytes=10000)
    assert r_xml == ProcessingRoute.XML_DETERMINISTIC

    # 2. Digital PDF with high text coverage -> PDF digital
    r_digital = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=50000,
        pdf_classification="pdf_digital",
        text_coverage_ratio=0.95,
        table_count=1,
    )
    assert r_digital == ProcessingRoute.PDF_DIGITAL

    # 3. Scanned PDF with tables -> Docling OCR structured extraction before LLM
    r_scan = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=150000,
        pdf_classification="pdf_scan",
        text_coverage_ratio=0.0,
        table_count=1,
    )
    assert r_scan == ProcessingRoute.DOCLING_OCR_STRUCTURED

    # 4. Corrupted / Low quality scan without tables -> Vision LLM targeted fallback
    r_difficult = router.decide_route(
        detected_kind="pdf",
        file_size_bytes=500000,
        pdf_classification="pdf_scan",
        text_coverage_ratio=0.0,
        table_count=0,
        is_difficult=True,
    )
    assert r_difficult == ProcessingRoute.VISION_FALLBACK
