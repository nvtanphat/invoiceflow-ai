from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest
from invoiceflow.application.processing.service import DocumentAIService
from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    CoordinateSystem,
    DocumentCell,
    DocumentTable,
)
from invoiceflow.infrastructure.llm.provider import ExtractedLine, ExtractionResult


@pytest.mark.asyncio
async def test_document_ai_service_reconciles_ocr_cell_merge_with_vision():
    # Mock LLM adapter that returns Vision results
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0101234567",
            supplier_name="Công ty TNHH Thiết bị Văn phòng Thăng Long",
            invoice_number="0005599",
            amount_payable=Decimal("60000000.0000"),
            line_items=[
                ExtractedLine(
                    line_no=1,
                    sku="DELL-XPS-13",
                    description="Máy tính xách tay Dell XPS 13",
                    qty=Decimal("2.0000"),
                    unit_price=Decimal("25000000.0000"),
                    line_amount=Decimal("50000000.0000"),
                ),
                ExtractedLine(
                    line_no=2,
                    sku="MOUSE-LOGI",
                    description="Chuột không dây Logitech MX Master 3S",
                    qty=Decimal("5.0000"),
                    unit_price=Decimal("2000000.0000"),
                    line_amount=Decimal("10000000.0000"),
                ),
            ],
            cost_usd=0.002,
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    # Mock DoclingAdapter to return a canonical doc with table cell merge on row 2
    mock_docling = MagicMock()
    cell_bbox = BoundingBox(
        page_index=0,
        x0=10.0,
        y0=50.0,
        x1=100.0,
        y1=70.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )
    table = DocumentTable(
        id="tbl-test",
        page_index=0,
        row_count=3,
        column_count=5,
        cells=[
            DocumentCell(row_index=0, col_index=0, text="STT", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=1, text="Ten hang", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=2, text="So luong", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=3, text="Don gia", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=4, text="Thanh tien", bbox=cell_bbox),
            # Line 1: Normal
            DocumentCell(row_index=1, col_index=0, text="1", bbox=cell_bbox),
            DocumentCell(
                row_index=1, col_index=1, text="Dell XPS 13 [DELL-XPS-13]", bbox=cell_bbox
            ),
            DocumentCell(row_index=1, col_index=2, text="2.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=3, text="25000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="50000000.0000", bbox=cell_bbox),
            # Line 2: Colspan merge on description and qty
            DocumentCell(row_index=2, col_index=0, text="2", bbox=cell_bbox),
            DocumentCell(
                row_index=2,
                col_index=1,
                colspan=2,
                text="Chuot Logitech [MOUSE-LOGI.0000",
                bbox=cell_bbox,
            ),
            DocumentCell(row_index=2, col_index=3, text="2000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=2, col_index=4, text="10000000.0000", bbox=cell_bbox),
        ],
    )
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[table],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    # Mock PDF Inspector
    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    # Dummy 1-page PDF
    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_scan_table.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    assert len(agg.lines) == 2
    # Line 1 unchanged
    assert agg.lines[0].sku_ref == "DELL-XPS-13"
    assert agg.lines[0].qty == Decimal("2.0000")
    # Line 2 recovered via Vision and verified arithmetically (5 * 2M = 10M)
    assert agg.lines[1].sku_ref == "MOUSE-LOGI"
    assert agg.lines[1].qty == Decimal("5.0000")
    assert agg.lines[1].unit_price == Decimal("2000000.0000")
    assert agg.lines[1].line_amount == Decimal("10000000.0000")
    assert "QTY_UNRECOVERED" not in agg.lines[1].issues
    assert "ARITHMETIC_MISMATCH" not in agg.lines[1].issues

    # Table cell bounding boxes are preserved
    table_evs = [ev for ev in agg.evidence if ev.source_kind == "pdf_table"]
    assert len(table_evs) > 0
    # Vision evidence for recovered quantity exists
    vision_qty_ev = [
        ev
        for ev in agg.evidence
        if ev.field_path == "lines[1].qty" and ev.source_kind == "vision_llm"
    ]
    assert len(vision_qty_ev) == 1
    assert vision_qty_ev[0].normalized_value == "5.0000"
    assert vision_qty_ev[0].verification_state == "arithmetically_consistent"
    # Dynamic confidence must not be hardcoded to 0.95
    assert vision_qty_ev[0].confidence != 0.95


@pytest.mark.asyncio
async def test_document_ai_service_preserves_ocr_when_vision_conflicts():
    """Verify that when OCR already has valid values and Vision proposes different ones,
    OCR values are preserved, FIELD_CONFLICT issues are raised, and invoice routes to Human Review.
    """
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0109999999",  # Conflicts with OCR 0105554321
            supplier_name="Công ty Sai Tên",
            invoice_number="0009999",  # Conflicts with OCR 0003412
            amount_payable=Decimal("99999999.0000"),  # Conflicts with OCR 9180000
            line_items=[],
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    # Mock digital parser to return solid OCR extracted values
    mock_digital = MagicMock()
    from invoiceflow.infrastructure.document.digital_pdf_parser import DigitalInvoiceExtraction

    mock_digital.parse.return_value = DigitalInvoiceExtraction(
        supplier_tax_id="0105554321",
        supplier_name="Công ty TNHH Vệ sinh Hà Nội",
        invoice_number="0003412",
        invoice_series="2C26TCC",
        issue_date="2026-03-08",
        subtotal=Decimal("8500000.0000"),
        tax_total=Decimal("680000.0000"),
        amount_payable=Decimal("9180000.0000"),
        lines=[],
        issues=[],
    )
    service._digital_parser = mock_digital

    mock_docling = MagicMock()
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 0
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_conflict.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    # OCR values must be preserved!
    assert agg.supplier_tax_id == "0105554321"
    assert agg.invoice_number == "0003412"
    assert agg.amount_payable == Decimal("9180000.0000")

    # Conflict issues must be recorded
    assert any("FIELD_CONFLICT_SUPPLIER_TAX_ID" in iss for iss in agg.parser_issues)
    assert any("FIELD_CONFLICT_INVOICE_NUMBER" in iss for iss in agg.parser_issues)
    assert any("FIELD_CONFLICT_AMOUNT_PAYABLE" in iss for iss in agg.parser_issues)


@pytest.mark.asyncio
async def test_document_ai_service_matches_lines_by_multifactor_not_line_no():
    """Verify that lines are matched using multi-factor signals (SKU, price, amount)
    even when row order is reversed, and NOT blindly by raw line_no.
    """
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0101234567",
            invoice_number="0005599",
            amount_payable=Decimal("60000000.0000"),
            line_items=[
                # Vision returns line 2 first (reversed order)
                ExtractedLine(
                    line_no=1,
                    sku="MOUSE-LOGI",
                    description="Chuột không dây Logitech MX Master 3S",
                    qty=Decimal("5.0000"),
                    unit_price=Decimal("2000000.0000"),
                    line_amount=Decimal("10000000.0000"),
                ),
                ExtractedLine(
                    line_no=2,
                    sku="DELL-XPS-13",
                    description="Máy tính xách tay Dell XPS 13",
                    qty=Decimal("2.0000"),
                    unit_price=Decimal("25000000.0000"),
                    line_amount=Decimal("50000000.0000"),
                ),
            ],
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    cell_bbox = BoundingBox(
        page_index=0,
        x0=10.0,
        y0=50.0,
        x1=100.0,
        y1=70.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )
    table = DocumentTable(
        id="tbl-test",
        page_index=0,
        row_count=3,
        column_count=5,
        cells=[
            DocumentCell(row_index=0, col_index=0, text="STT", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=1, text="Ten hang", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=2, text="So luong", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=3, text="Don gia", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=4, text="Thanh tien", bbox=cell_bbox),
            # Row 1 in OCR is DELL
            DocumentCell(row_index=1, col_index=0, text="1", bbox=cell_bbox),
            DocumentCell(
                row_index=1, col_index=1, text="Dell XPS 13 [DELL-XPS-13]", bbox=cell_bbox
            ),
            DocumentCell(row_index=1, col_index=2, text="2.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=3, text="25000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="50000000.0000", bbox=cell_bbox),
            # Row 2 in OCR is MOUSE with unrecovered qty
            DocumentCell(row_index=2, col_index=0, text="2", bbox=cell_bbox),
            DocumentCell(
                row_index=2,
                col_index=1,
                colspan=2,
                text="Chuot Logitech [MOUSE-LOGI.0000",
                bbox=cell_bbox,
            ),
            DocumentCell(row_index=2, col_index=3, text="2000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=2, col_index=4, text="10000000.0000", bbox=cell_bbox),
        ],
    )

    mock_docling = MagicMock()
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[table],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_reversed_lines.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    assert len(agg.lines) == 2
    # Line 1 in OCR must remain DELL with price 25M
    assert agg.lines[0].sku_ref == "DELL-XPS-13"
    assert agg.lines[0].unit_price == Decimal("25000000.0000")
    # Line 2 in OCR must be matched with Vision's MOUSE-LOGI (price 2M, qty 5.0)
    assert agg.lines[1].sku_ref == "MOUSE-LOGI"
    assert agg.lines[1].qty == Decimal("5.0000")
    assert agg.lines[1].unit_price == Decimal("2000000.0000")
    assert agg.lines[1].line_amount == Decimal("10000000.0000")


@pytest.mark.asyncio
async def test_document_ai_service_rejects_vision_quantity_when_arithmetic_fails():
    """Verify that if Vision proposes a quantity that violates line arithmetic (qty * price != amount),
    the quantity is NOT adopted, and a mismatch issue is recorded."""
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0101234567",
            amount_payable=Decimal("10000000.0000"),
            line_items=[
                ExtractedLine(
                    line_no=1,
                    sku="ITEM-A",
                    description="Sản phẩm A",
                    qty=Decimal("99.0000"),  # False quantity! 99 * 2M != 10M
                    unit_price=Decimal("2000000.0000"),
                    line_amount=Decimal("10000000.0000"),
                ),
            ],
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    cell_bbox = BoundingBox(
        page_index=0,
        x0=10.0,
        y0=50.0,
        x1=100.0,
        y1=70.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )
    table = DocumentTable(
        id="tbl-test",
        page_index=0,
        row_count=2,
        column_count=5,
        cells=[
            DocumentCell(row_index=0, col_index=0, text="STT", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=1, text="Ten hang", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=2, text="So luong", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=3, text="Don gia", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=4, text="Thanh tien", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=0, text="1", bbox=cell_bbox),
            DocumentCell(
                row_index=1, col_index=1, colspan=2, text="San pham A [ITEM-A.0000", bbox=cell_bbox
            ),
            DocumentCell(row_index=1, col_index=3, text="2000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="10000000.0000", bbox=cell_bbox),
        ],
    )

    mock_docling = MagicMock()
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[table],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_arith_fail.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    assert len(agg.lines) == 1
    # Quantity must NOT be overwritten with 99
    assert agg.lines[0].qty != Decimal("99.0000")
    assert any("VISION_QUANTITY_ARITHMETIC_MISMATCH" in iss for iss in agg.lines[0].issues)


@pytest.mark.asyncio
async def test_document_ai_service_handles_ambiguous_line_matches():
    """Verify that when multiple Vision candidates have nearly identical high match scores,
    the match is treated as ambiguous and LINE_MATCH_AMBIGUOUS is flagged."""
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0101234567",
            amount_payable=Decimal("2000000.0000"),
            line_items=[
                ExtractedLine(
                    line_no=1,
                    sku="",
                    description="Vật tư tiêu hao loại 1",
                    qty=Decimal("1.0000"),
                    unit_price=Decimal("1000000.0000"),
                    line_amount=Decimal("1000000.0000"),
                ),
                ExtractedLine(
                    line_no=2,
                    sku="",
                    description="Vật tư tiêu hao loại 2",
                    qty=Decimal("1.0000"),
                    unit_price=Decimal("1000000.0000"),
                    line_amount=Decimal("1000000.0000"),
                ),
            ],
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    cell_bbox = BoundingBox(
        page_index=0,
        x0=10.0,
        y0=50.0,
        x1=100.0,
        y1=70.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )
    table = DocumentTable(
        id="tbl-test",
        page_index=0,
        row_count=2,
        column_count=5,
        cells=[
            DocumentCell(row_index=0, col_index=0, text="STT", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=1, text="Ten hang", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=2, text="So luong", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=3, text="Don gia", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=4, text="Thanh tien", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=0, text="1", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=1, text="Vat tu tieu hao", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=2, text="0.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=3, text="1000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="1000000.0000", bbox=cell_bbox),
        ],
    )

    mock_docling = MagicMock()
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[table],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_ambig.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    assert any("LINE_MATCH_AMBIGUOUS" in iss for iss in agg.lines[0].issues)


@pytest.mark.asyncio
async def test_document_ai_service_preserves_ocr_valid_qty_when_vision_differs():
    """Verify that when OCR already recognized a valid non-zero quantity,
    Vision AI NEVER overwrites it even if Vision's quantity satisfies arithmetic consistency.
    Both values must be preserved: OCR value kept in line, Vision value stored as candidate evidence,
    and LINE_QTY_CONFLICT is raised.
    """
    mock_llm = MagicMock()
    mock_llm._client = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock(
        return_value=ExtractionResult(
            supplier_tax_id="0101234567",
            amount_payable=Decimal("8000.0000"),
            line_items=[
                ExtractedLine(
                    line_no=1,
                    sku="ITEM-X",
                    description="Vật tư X",
                    qty=Decimal("8.0000"),
                    unit_price=Decimal("1000.0000"),
                    line_amount=Decimal("8000.0000"),
                ),
            ],
        )
    )

    service = DocumentAIService(llm_adapter=mock_llm)

    cell_bbox = BoundingBox(
        page_index=0,
        x0=10.0,
        y0=50.0,
        x1=100.0,
        y1=70.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )
    table = DocumentTable(
        id="tbl-test",
        page_index=0,
        row_count=2,
        column_count=5,
        cells=[
            DocumentCell(row_index=0, col_index=0, text="STT", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=1, text="Ten hang", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=2, text="So luong", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=3, text="Don gia", bbox=cell_bbox),
            DocumentCell(row_index=0, col_index=4, text="Thanh tien", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=0, text="1", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=1, text="Vat tu X [ITEM-X]", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=2, text="10.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=3, text="1000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="8000.0000", bbox=cell_bbox),
        ],
    )

    mock_docling = MagicMock()
    mock_docling.extract_canonical.return_value = CanonicalDocument(
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        source_format="pdf",
        parser_name="docling",
        parser_version="2.87.0",
        config_hash="test",
        source_checksum="test",
        page_count=1,
        elements=[],
        tables=[table],
    )
    mock_docling._normalize_page_rotation.side_effect = lambda b: b
    service._docling_adapter = mock_docling

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_scan"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_ocr_qty_preserve.pdf",
        content=pdf_bytes,
    )

    agg = result.invoice_aggregate
    assert len(agg.lines) == 1
    assert agg.lines[0].qty == Decimal("10.0000")
    assert any("LINE_QTY_CONFLICT" in iss for iss in agg.lines[0].issues)
    assert any("LINE_QTY_CONFLICT" in iss for iss in agg.parser_issues)
    assert "ARITHMETIC_MISMATCH" in agg.lines[0].issues

    cand_evs = [ev for ev in agg.evidence if ev.field_path == "lines[0].qty.candidate_vision"]
    assert len(cand_evs) == 1
    assert cand_evs[0].raw_value == "8.0000"
    assert cand_evs[0].verification_state == "model_proposed"
    assert cand_evs[0].review_reason is not None


@pytest.mark.asyncio
async def test_review_service_blocks_approval_on_unresolved_candidate_conflicts():
    """Verify that ReviewService blocks approval with ValueError when unresolved candidate vision
    evidence (verification_state='model_proposed') exists, and permits approval once resolved.
    """
    from invoiceflow.application.review.service import ReviewService
    from invoiceflow.infrastructure.database.models import (
        FieldEvidenceORM,
        InvoiceLineORM,
        InvoiceORM,
        MatchResultORM,
    )
    from invoiceflow.infrastructure.database.session import DatabaseSessionManager

    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()

    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    inv_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())

    async with db_manager.session() as session:
        inv = InvoiceORM(
            id=inv_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            revision=1,
            status="READY_FOR_REVIEW",
            supplier_tax_id="0105554321",
            supplier_name="Cong ty Alpha",
            invoice_number="0001234",
            currency="VND",
            subtotal=Decimal("8000.0000"),
            discount_total=Decimal("0.0000"),
            tax_total=Decimal("800.0000"),
            amount_payable=Decimal("8800.0000"),
            rounding_adjustment=Decimal("0.0000"),
            signature_status="verified",
            tax_authority_status="verified",
        )
        session.add(inv)

        line = InvoiceLineORM(
            id=str(uuid.uuid4()),
            invoice_id=inv_id,
            line_no=1,
            description="San pham X",
            qty=Decimal("8.0000"),
            unit_price=Decimal("1000.0000"),
            discount=Decimal("0.0000"),
            line_amount=Decimal("8000.0000"),
        )
        session.add(line)

        cand_ev = FieldEvidenceORM(
            id=str(uuid.uuid4()),
            invoice_id=inv_id,
            field_path="supplier_tax_id.candidate_vision",
            source_kind="vision_llm",
            raw_value="0109999999",
            normalized_value="0109999999",
            confidence=0.80,
            extractor="openai_vision",
            verification_state="model_proposed",
            review_reason="Conflicting candidate from Vision AI",
        )
        session.add(cand_ev)

        match_result = MatchResultORM(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            status="MATCHED",
            is_matched=True,
            requires_review=False,
            issues_json="[]",
        )
        session.add(match_result)
        await session.commit()

    async with db_manager.session() as session:
        review_service = ReviewService(session)

        with pytest.raises(ValueError, match="xung đột tài chính chưa giải quyết"):
            await review_service.approve_invoice(
                tenant_id=tenant_id,
                invoice_id=inv_id,
                expected_revision=1,
                actor_id=actor_id,
            )

        updated = await review_service.update_invoice_fields(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            expected_revision=1,
            actor_id=actor_id,
            patches={"supplier_tax_id": "0105554321"},
            reason="Reviewer verified supplier tax ID against original invoice",
        )
        assert updated.revision == 2

        approved = await review_service.approve_invoice(
            tenant_id=tenant_id,
            invoice_id=inv_id,
            expected_revision=2,
            actor_id=actor_id,
            notes="Duyệt hóa đơn sau khi xác minh",
        )
        assert approved.status == "APPROVED"
        assert approved.revision == 3

    await db_manager.close()


def test_field_verification_state_semantics():
    from invoiceflow.domain.invoices.models import FieldEvidence, FieldVerificationState

    ev_valid = FieldEvidence(
        field_path="amount_payable",
        source_kind="docling_table",
        raw_value="10000000",
        normalized_value="10000000",
        verification_state=FieldVerificationState.VALID,
    )
    assert ev_valid.verification_state == "valid"
    assert ev_valid.verification_state == FieldVerificationState.VALID

    ev_missing = FieldEvidence(
        field_path="lines[0].qty",
        source_kind="docling_table",
        raw_value=None,
        normalized_value=None,
        verification_state=FieldVerificationState.MISSING,
        review_reason="Quantity cell missing due to table merge",
    )
    assert ev_missing.verification_state == "missing"

    ev_conflict = FieldEvidence(
        field_path="supplier_tax_id.candidate_vision",
        source_kind="vision_llm",
        raw_value="0105554321",
        normalized_value="0105554321",
        verification_state=FieldVerificationState.CONFLICT,
    )
    assert ev_conflict.verification_state == "conflict"
