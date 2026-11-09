from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid
import fitz
import numpy as np
import pytest

from invoiceflow.application.processing.service import DocumentAIService
from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    CoordinateSystem,
    DocumentCell,
    DocumentTable,
)
from invoiceflow.infrastructure.document.region_recoverer import RegionOCRRecoverer


def test_region_recoverer_recovers_quantity_arithmetically():
    recoverer = RegionOCRRecoverer()

    # Mock easyocr reader
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [([[0, 0], [10, 0], [10, 10], [0, 10]], "2", 0.96)]
    recoverer._reader = mock_reader

    # Mock page crop and enhance
    recoverer._crop_and_enhance = MagicMock(return_value=np.zeros((100, 100), dtype=np.uint8))

    doc = fitz.open()
    doc.new_page(width=595, height=842)

    bbox = BoundingBox(
        page_index=0,
        x0=50.0,
        y0=100.0,
        x1=500.0,
        y1=120.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )

    result = recoverer.recover_line_quantity(
        doc_pdf=doc,
        page_index=0,
        line_bbox=bbox,
        unit_price=Decimal("25000000.0000"),
        line_amount=Decimal("50000000.0000"),
    )

    doc.close()
    assert result is not None
    qty, conf = result
    assert qty == Decimal("2")
    assert conf == 0.96


def test_region_recoverer_rejects_arithmetically_inconsistent_quantity():
    recoverer = RegionOCRRecoverer()

    # OCR reads 5, but 5 * 25M != 50M
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [([[0, 0], [10, 0], [10, 10], [0, 10]], "5", 0.95)]
    recoverer._reader = mock_reader
    recoverer._crop_and_enhance = MagicMock(return_value=np.zeros((100, 100), dtype=np.uint8))

    doc = fitz.open()
    doc.new_page(width=595, height=842)

    bbox = BoundingBox(
        page_index=0,
        x0=50.0,
        y0=100.0,
        x1=500.0,
        y1=120.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )

    result = recoverer.recover_line_quantity(
        doc_pdf=doc,
        page_index=0,
        line_bbox=bbox,
        unit_price=Decimal("25000000.0000"),
        line_amount=Decimal("50000000.0000"),
    )

    doc.close()
    assert result is None


def test_region_recoverer_recovers_supplier_tax_id():
    recoverer = RegionOCRRecoverer()

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([[0, 0], [10, 0], [10, 10], [0, 10]], "Ma so thue: 0101234567", 0.94)
    ]
    recoverer._reader = mock_reader
    recoverer._crop_and_enhance = MagicMock(return_value=np.zeros((100, 100), dtype=np.uint8))

    doc = fitz.open()
    doc.new_page(width=595, height=842)

    result = recoverer.recover_missing_header_field(
        doc_pdf=doc,
        page_index=0,
        field_name="supplier_tax_id",
    )

    doc.close()
    assert result is not None
    tax_id, conf = result
    assert tax_id == "0101234567"
    assert conf == 0.94


def test_region_recoverer_recovers_invoice_number():
    recoverer = RegionOCRRecoverer()

    mock_reader = MagicMock()
    mock_reader.readtext.return_value = [
        ([[0, 0], [10, 0], [10, 10], [0, 10]], "So: 0048291", 0.91)
    ]
    recoverer._reader = mock_reader
    recoverer._crop_and_enhance = MagicMock(return_value=np.zeros((100, 100), dtype=np.uint8))

    doc = fitz.open()
    doc.new_page(width=595, height=842)

    result = recoverer.recover_missing_header_field(
        doc_pdf=doc,
        page_index=0,
        field_name="invoice_number",
    )

    doc.close()
    assert result is not None
    inv_no, conf = result
    assert inv_no == "0048291"
    assert conf == 0.91


@pytest.mark.asyncio
async def test_service_avoids_vision_fallback_when_region_ocr_recovers():
    # When Region OCR successfully recovers the missing quantity,
    # DocumentAIService avoids calling expensive Vision fallback (cost_usd = 0, used_vision = False).
    mock_llm = MagicMock()
    mock_llm.extract_invoice_data = AsyncMock()

    mock_recoverer = MagicMock()
    mock_recoverer.recover_missing_header_field.return_value = None
    mock_recoverer.recover_line_quantity.return_value = (Decimal("5.0000"), 0.95)

    service = DocumentAIService(llm_adapter=mock_llm, region_recoverer=mock_recoverer)

    # Provide a complete header via digital parser mock
    mock_digital_parser = MagicMock()
    mock_digital_res = MagicMock()
    mock_digital_res.supplier_tax_id = "0101234567"
    mock_digital_res.supplier_name = "Công ty TNHH Thăng Long"
    mock_digital_res.buyer_tax_id = "0109876543"
    mock_digital_res.buyer_name = "Công ty CP ABC"
    mock_digital_res.invoice_number = "0005599"
    mock_digital_res.invoice_series = "1C26TAA"
    mock_digital_res.issue_date = "2026-04-18"
    mock_digital_res.currency = "VND"
    mock_digital_res.subtotal = Decimal("60000000.0000")
    mock_digital_res.tax_total = Decimal("0.0000")
    mock_digital_res.amount_payable = Decimal("60000000.0000")
    mock_digital_res.lines = []
    mock_digital_res.issues = []
    mock_digital_parser.parse.return_value = mock_digital_res
    service._digital_parser = mock_digital_parser

    # Mock Docling returning a table where line 2 has cell merge (qty=0)
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
            DocumentCell(row_index=1, col_index=1, text="Dell XPS 13", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=2, text="2.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=3, text="25000000.0000", bbox=cell_bbox),
            DocumentCell(row_index=1, col_index=4, text="50000000.0000", bbox=cell_bbox),
            # Line 2: Colspan merge on description and qty -> qty=0
            DocumentCell(row_index=2, col_index=0, text="2", bbox=cell_bbox),
            DocumentCell(
                row_index=2,
                col_index=1,
                colspan=2,
                text="Chuot Logitech MX Master 3S",
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

    mock_inspector = MagicMock()
    mock_profile = MagicMock()
    mock_profile.has_rotated_pages = False
    mock_profile.classification = "pdf_digital"
    mock_profile.table_count = 1
    mock_inspector.inspect.return_value = mock_profile
    service._pdf_inspector = mock_inspector

    doc = fitz.open()
    doc.new_page()
    pdf_bytes = doc.write()
    doc.close()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="test_scan.pdf",
        content=pdf_bytes,
    )

    # Verify that Region OCR recovered Line 2 quantity
    agg = result.invoice_aggregate
    assert len(agg.lines) == 2
    assert agg.lines[1].qty == Decimal("5.0000")
    assert "CELL_MERGE_SUSPECTED" not in agg.lines[1].issues
    assert "QTY_UNRECOVERED" not in agg.lines[1].issues

    # Verify Vision was NOT called (avoiding cost)
    mock_llm.extract_invoice_data.assert_not_called()
    assert result.used_vision is False
    assert result.cost_usd == 0.0

    # Verify evidence has region retry
    rec_ev = next(
        (ev for ev in agg.evidence if ev.field_path == "lines[1].qty"),
        None,
    )
    assert rec_ev is not None
    assert rec_ev.source_kind == "ocr_region_retry"
    assert rec_ev.verification_state == "arithmetically_consistent"
