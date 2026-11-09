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
