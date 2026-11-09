from decimal import Decimal
from invoiceflow.domain.documents.models import (
    BoundingBox,
    CoordinateSystem,
    DocumentCell,
    DocumentTable,
)
from invoiceflow.infrastructure.document.table_extractor import StructureAwareTableExtractor


def _make_bbox(p_idx, x0, y0, x1, y1):
    return BoundingBox(
        page_index=p_idx,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )


def test_table_extractor_identifies_standard_vietnamese_columns():
    # Table headers: STT | Mã hàng | Tên hàng hóa, dịch vụ | ĐVT | Số lượng | Đơn giá | Thành tiền
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT", bbox=_make_bbox(0, 10, 50, 40, 70)),
        DocumentCell(row_index=0, col_index=1, text="Mã hàng", bbox=_make_bbox(0, 45, 50, 95, 70)),
        DocumentCell(
            row_index=0,
            col_index=2,
            text="Tên hàng hóa, dịch vụ",
            bbox=_make_bbox(0, 100, 50, 300, 70),
        ),
        DocumentCell(row_index=0, col_index=3, text="ĐVT", bbox=_make_bbox(0, 305, 50, 345, 70)),
        DocumentCell(
            row_index=0, col_index=4, text="Số lượng", bbox=_make_bbox(0, 350, 50, 400, 70)
        ),
        DocumentCell(
            row_index=0, col_index=5, text="Đơn giá", bbox=_make_bbox(0, 405, 50, 480, 70)
        ),
        DocumentCell(
            row_index=0, col_index=6, text="Thành tiền", bbox=_make_bbox(0, 485, 50, 580, 70)
        ),
    ]

    # Row 1: Laptop Dell XPS 13
    row1 = [
        DocumentCell(row_index=1, col_index=0, text="1", bbox=_make_bbox(0, 10, 75, 40, 95)),
        DocumentCell(
            row_index=1, col_index=1, text="DELL-XPS-13", bbox=_make_bbox(0, 45, 75, 95, 95)
        ),
        DocumentCell(
            row_index=1,
            col_index=2,
            text="Máy tính xách tay Dell XPS 13",
            bbox=_make_bbox(0, 100, 75, 300, 95),
        ),
        DocumentCell(row_index=1, col_index=3, text="cái", bbox=_make_bbox(0, 305, 75, 345, 95)),
        DocumentCell(row_index=1, col_index=4, text="5", bbox=_make_bbox(0, 350, 75, 400, 95)),
        DocumentCell(
            row_index=1, col_index=5, text="10.000.000", bbox=_make_bbox(0, 405, 75, 480, 95)
        ),
        DocumentCell(
            row_index=1, col_index=6, text="50.000.000", bbox=_make_bbox(0, 485, 75, 580, 95)
        ),
    ]

    # Row 2 with multi-line wrapped description across sub-row
    row2_part1 = [
        DocumentCell(row_index=2, col_index=0, text="2", bbox=_make_bbox(0, 10, 100, 40, 120)),
        DocumentCell(
            row_index=2, col_index=1, text="LOGI-MX-3", bbox=_make_bbox(0, 45, 100, 95, 120)
        ),
        DocumentCell(
            row_index=2,
            col_index=2,
            text="Chuột không dây Logitech MX Master 3S",
            bbox=_make_bbox(0, 100, 100, 300, 120),
        ),
        DocumentCell(
            row_index=2, col_index=3, text="chiếc", bbox=_make_bbox(0, 305, 100, 345, 120)
        ),
        DocumentCell(row_index=2, col_index=4, text="10", bbox=_make_bbox(0, 350, 100, 400, 120)),
        DocumentCell(
            row_index=2, col_index=5, text="2.000.000", bbox=_make_bbox(0, 405, 100, 480, 120)
        ),
        DocumentCell(
            row_index=2, col_index=6, text="20.000.000", bbox=_make_bbox(0, 485, 100, 580, 120)
        ),
    ]
    # Continuation line for row 2 (only description filled)
    row2_part2 = [
        DocumentCell(
            row_index=3,
            col_index=2,
            text="(Màu xám than, bảo hành 12 tháng chính hãng)",
            bbox=_make_bbox(0, 100, 125, 300, 145),
        ),
    ]

    table = DocumentTable(
        id="tbl-001",
        page_index=0,
        row_count=4,
        column_count=7,
        cells=headers + row1 + row2_part1 + row2_part2,
    )

    extractor = StructureAwareTableExtractor()
    extracted_lines = extractor.extract_invoice_lines(table)

    assert len(extracted_lines) == 2
    # Verify line 1
    l1 = extracted_lines[0]
    assert l1.line_no == 1
    assert l1.sku_ref == "DELL-XPS-13"
    assert l1.description == "Máy tính xách tay Dell XPS 13"
    assert l1.unit == "cái"
    assert l1.qty == Decimal("5.0000")
    assert l1.unit_price == Decimal("10000000.0000")
    assert l1.line_amount == Decimal("50000000.0000")
    assert l1.raw_qty == "5"
    assert l1.raw_unit_price == "10.000.000"
    assert l1.raw_line_amount == "50.000.000"
    assert len(l1.issues) == 0

    # Verify line 2 with merged wrapped description
    l2 = extracted_lines[1]
    assert l2.line_no == 2
    assert l2.sku_ref == "LOGI-MX-3"
    assert "Logitech MX Master 3S" in l2.description
    assert "Màu xám than" in l2.description
    assert l2.unit == "chiếc"
    assert l2.qty == Decimal("10.0000")
    assert l2.unit_price == Decimal("2000000.0000")
    assert l2.line_amount == Decimal("20000000.0000")


def test_table_extractor_10_lines_preserves_cells_and_detects_mismatch():
    # Construct 10 items in a table, with item 7 having an intentional arithmetic mismatch
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Tên hàng"),
        DocumentCell(row_index=0, col_index=2, text="Số lượng"),
        DocumentCell(row_index=0, col_index=3, text="Đơn giá"),
        DocumentCell(row_index=0, col_index=4, text="Thành tiền"),
    ]
    cells = list(headers)
    for i in range(1, 11):
        qty_str = str(i)
        price_str = "100.000"
        # Item 7 has mismatch: 7 * 100.000 = 700.000, but printed is 650.000
        amt_str = "650.000" if i == 7 else f"{i * 100}.000"
        cells.extend(
            [
                DocumentCell(
                    row_index=i,
                    col_index=0,
                    text=str(i),
                    bbox=_make_bbox(0, 10, i * 20, 30, (i + 1) * 20),
                ),
                DocumentCell(
                    row_index=i,
                    col_index=1,
                    text=f"Sản phẩm số {i}",
                    bbox=_make_bbox(0, 35, i * 20, 200, (i + 1) * 20),
                ),
                DocumentCell(
                    row_index=i,
                    col_index=2,
                    text=qty_str,
                    bbox=_make_bbox(0, 205, i * 20, 250, (i + 1) * 20),
                ),
                DocumentCell(
                    row_index=i,
                    col_index=3,
                    text=price_str,
                    bbox=_make_bbox(0, 255, i * 20, 320, (i + 1) * 20),
                ),
                DocumentCell(
                    row_index=i,
                    col_index=4,
                    text=amt_str,
                    bbox=_make_bbox(0, 325, i * 20, 400, (i + 1) * 20),
                ),
            ]
        )

    table = DocumentTable(
        id="tbl-10-items", page_index=0, row_count=11, column_count=5, cells=cells
    )
    extractor = StructureAwareTableExtractor()
    lines = extractor.extract_invoice_lines(table)

    # Acceptance: Exactly 10 InvoiceLine objects created
    assert len(lines) == 10
    # Line 7 must have ARITHMETIC_MISMATCH without changing the raw value
    assert "ARITHMETIC_MISMATCH" in lines[6].issues
    assert lines[6].line_amount == Decimal("650000.0000")
    assert lines[6].raw_line_amount == "650.000"
    # Line 1-6, 8-10 have zero issues
    assert len(lines[0].issues) == 0
    assert len(lines[9].issues) == 0


def test_combined_header_with_inline_sku_keyword_does_not_hijack_description_column():
    # Reproduces the real Docling TableFormer output observed on
    # benchmarks/fixtures/documents/case_06.pdf: the product column header
    # literally contains the word "SKU" ("Ten hang hoa, dich vu / SKU") and a
    # second header cell merges two concepts ("Thue suat" + "Thanh tien")
    # into one physical cell via colspan=2. Column classification must not
    # let a bare "sku" keyword match shadow the much more specific
    # "description" phrase, and must distribute a merged header's multiple
    # concepts across the columns it spans.
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Ten hang hoa, dich vu / SKU"),
        DocumentCell(row_index=0, col_index=2, text="So luong"),
        DocumentCell(row_index=0, col_index=3, text="Don gia"),
        DocumentCell(row_index=0, col_index=4, text="Thue suatThanh tien", colspan=2),
    ]
    row1 = [
        DocumentCell(row_index=1, col_index=0, text="1"),
        DocumentCell(row_index=1, col_index=1, text="May tinh xach tay Dell XPS 13 [DELL-XPS-13]"),
        DocumentCell(row_index=1, col_index=2, text="2.0000"),
        DocumentCell(row_index=1, col_index=3, text="25000000.0000"),
        DocumentCell(row_index=1, col_index=4, text="10.00%"),
        DocumentCell(row_index=1, col_index=5, text="50000000.0000"),
    ]
    table = DocumentTable(
        id="tbl-case06", page_index=0, row_count=2, column_count=6, cells=headers + row1
    )

    lines = StructureAwareTableExtractor().extract_invoice_lines(table)

    assert len(lines) == 1
    line = lines[0]
    assert line.sku_ref == "DELL-XPS-13"
    assert "May tinh xach tay Dell XPS 13" in line.description
    assert "[DELL-XPS-13]" not in line.description
    assert line.qty == Decimal("2.0000")
    assert line.unit_price == Decimal("25000000.0000")
    assert line.line_amount == Decimal("50000000.0000")
    assert line.tax_rate == Decimal("10.00")
    assert "ARITHMETIC_MISMATCH" not in line.issues


def test_zero_quantity_is_preserved_and_flagged_not_rewritten_to_one():
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Ten hang"),
        DocumentCell(row_index=0, col_index=2, text="So luong"),
        DocumentCell(row_index=0, col_index=3, text="Don gia"),
        DocumentCell(row_index=0, col_index=4, text="Thanh tien"),
    ]
    row1 = [
        DocumentCell(row_index=1, col_index=0, text="1"),
        DocumentCell(row_index=1, col_index=1, text="Hang mau khong tinh phi"),
        DocumentCell(row_index=1, col_index=2, text="0"),
        DocumentCell(row_index=1, col_index=3, text="500000.0000"),
        DocumentCell(row_index=1, col_index=4, text="0.0000"),
    ]
    table = DocumentTable(
        id="tbl-zero-qty", page_index=0, row_count=2, column_count=5, cells=headers + row1
    )

    lines = StructureAwareTableExtractor().extract_invoice_lines(table)

    assert len(lines) == 1
    assert lines[0].qty == Decimal("0.0000")
    assert lines[0].raw_qty == "0"
    assert "QTY_ZERO_OR_MISSING" in lines[0].issues


def test_colspan_merged_data_cell_is_flagged_not_fabricated():
    # Row 2 in case_06.pdf has its description and quantity cells fused by
    # TableFormer into a single colspan=2 cell. The extractor must not guess
    # a quantity out of free text; it must flag the row for review instead.
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Ten hang hoa"),
        DocumentCell(row_index=0, col_index=2, text="So luong"),
        DocumentCell(row_index=0, col_index=3, text="Don gia"),
        DocumentCell(row_index=0, col_index=4, text="Thanh tien"),
    ]
    row2 = [
        DocumentCell(row_index=1, col_index=0, text="2"),
        DocumentCell(
            row_index=1,
            col_index=1,
            text="Chuot khong day Logitech MX Master 3S [MOUSE-LOGI] 5.0000",
            colspan=2,
        ),
        DocumentCell(row_index=1, col_index=3, text="2000000.0000"),
        DocumentCell(row_index=1, col_index=4, text="10000000.0000"),
    ]
    table = DocumentTable(
        id="tbl-colspan-data", page_index=0, row_count=2, column_count=5, cells=headers + row2
    )

    lines = StructureAwareTableExtractor().extract_invoice_lines(table)

    assert len(lines) == 1
    line = lines[0]
    assert line.sku_ref == "MOUSE-LOGI"
    assert line.unit_price == Decimal("2000000.0000")
    assert line.line_amount == Decimal("10000000.0000")
    assert "CELL_MERGE_SUSPECTED" in line.issues
    # Quantity must not be fabricated from the merged free-text cell.
    assert line.qty == Decimal("0.0000")


def test_extract_lines_with_evidence_links_fields_to_table_and_cell_ids():
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Ten hang hoa"),
        DocumentCell(row_index=0, col_index=2, text="So luong"),
        DocumentCell(row_index=0, col_index=3, text="Don gia"),
        DocumentCell(row_index=0, col_index=4, text="Thanh tien"),
    ]
    row1 = [
        DocumentCell(
            row_index=1,
            col_index=0,
            text="1",
            id="tbl-1-r1-c0",
            table_id="tbl-1",
        ),
        DocumentCell(
            row_index=1,
            col_index=1,
            text="May tinh Dell XPS 13 [DELL-XPS-13]",
            id="tbl-1-r1-c1",
            table_id="tbl-1",
            bbox=_make_bbox(0, 100, 75, 300, 95),
        ),
        DocumentCell(
            row_index=1,
            col_index=2,
            text="2.0000",
            id="tbl-1-r1-c2",
            table_id="tbl-1",
            bbox=_make_bbox(0, 305, 75, 345, 95),
        ),
        DocumentCell(
            row_index=1,
            col_index=3,
            text="25000000.0000",
            id="tbl-1-r1-c3",
            table_id="tbl-1",
            bbox=_make_bbox(0, 350, 75, 400, 95),
        ),
        DocumentCell(
            row_index=1,
            col_index=4,
            text="50000000.0000",
            id="tbl-1-r1-c4",
            table_id="tbl-1",
            bbox=_make_bbox(0, 405, 75, 480, 95),
        ),
    ]
    table = DocumentTable(
        id="tbl-1", page_index=0, row_count=2, column_count=5, cells=headers + row1
    )

    lines, evidence = StructureAwareTableExtractor().extract_lines_with_evidence([table])

    assert len(lines) == 1
    by_field = {ev.field_path: ev for ev in evidence}

    sku_ev = by_field["lines[0].sku_ref"]
    assert sku_ev.table_id == "tbl-1"
    assert sku_ev.cell_id == "tbl-1-r1-c1"  # SKU was embedded in the description cell
    assert sku_ev.normalized_value == "DELL-XPS-13"

    qty_ev = by_field["lines[0].qty"]
    assert qty_ev.table_id == "tbl-1"
    assert qty_ev.cell_id == "tbl-1-r1-c2"
    assert qty_ev.bbox is not None
    assert qty_ev.bbox.x0 == 305

    amount_ev = by_field["lines[0].line_amount"]
    assert amount_ev.cell_id == "tbl-1-r1-c4"
    assert amount_ev.normalized_value == "50000000.0000"


def test_table_extractor_recovers_fused_sku_and_distinguishes_valid_zero():
    extractor = StructureAwareTableExtractor()

    # Case 1: Fused/unclosed bracket SKU from OCR cell merge
    headers = [
        DocumentCell(
            row_index=0, col_index=0, text="Tên hàng hóa", bbox=_make_bbox(0, 10, 50, 200, 70)
        ),
        DocumentCell(
            row_index=0, col_index=1, text="Số lượng", bbox=_make_bbox(0, 205, 50, 250, 70)
        ),
        DocumentCell(
            row_index=0, col_index=2, text="Đơn giá", bbox=_make_bbox(0, 255, 50, 320, 70)
        ),
        DocumentCell(
            row_index=0, col_index=3, text="Thành tiền", bbox=_make_bbox(0, 325, 50, 400, 70)
        ),
    ]
    # Row with fused SKU and merged quantity slot
    row1 = [
        DocumentCell(
            row_index=1,
            col_index=0,
            colspan=2,
            text="Chuột dây Logitech MX Master 3S [MOUSE-LOGI.0000 không",
            bbox=_make_bbox(0, 10, 75, 250, 95),
        ),
        DocumentCell(
            row_index=1, col_index=2, text="2000000.0000", bbox=_make_bbox(0, 255, 75, 320, 95)
        ),
        DocumentCell(
            row_index=1, col_index=3, text="10000000.0000", bbox=_make_bbox(0, 325, 75, 400, 95)
        ),
    ]
    # Row with valid 0 quantity (e.g. complimentary sample)
    row2 = [
        DocumentCell(
            row_index=2,
            col_index=0,
            text="Túi đựng laptop [BAG-SAMPLE-01]",
            bbox=_make_bbox(0, 10, 100, 200, 120),
        ),
        DocumentCell(
            row_index=2, col_index=1, text="0.0000", bbox=_make_bbox(0, 205, 100, 250, 120)
        ),
        DocumentCell(
            row_index=2, col_index=2, text="0.0000", bbox=_make_bbox(0, 255, 100, 320, 120)
        ),
        DocumentCell(
            row_index=2, col_index=3, text="0.0000", bbox=_make_bbox(0, 325, 100, 400, 120)
        ),
    ]

    table = DocumentTable(
        id="tbl-test", page_index=0, row_count=3, column_count=4, cells=headers + row1 + row2
    )
    lines = extractor.extract_lines([table])

    assert len(lines) == 2
    # Row 1 should extract MOUSE-LOGI SKU even with fused punctuation
    assert lines[0].sku_ref == "MOUSE-LOGI"
    assert "MOUSE-LOGI" not in lines[0].description
    # Row 1 quantity was merged/missing, so it must be flagged as unrecovered
    assert "QTY_UNRECOVERED" in lines[0].issues
    assert "CELL_MERGE_SUSPECTED" in lines[0].issues

    # Row 2 was explicitly 0, so it must NOT be flagged as QTY_UNRECOVERED
    assert lines[1].sku_ref == "BAG-SAMPLE-01"
    assert lines[1].qty == Decimal("0.0000")
    assert "QTY_UNRECOVERED" not in lines[1].issues
    assert "QTY_ZERO_OR_MISSING" in lines[1].issues


def test_hyphenated_skus_preserved_without_truncation():
    """Verify hyphenated SKUs (PAPER-A4-80, LAP-DELL-5520, MOUSE-LOGI) are preserved in full."""
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Ten hang"),
        DocumentCell(row_index=0, col_index=2, text="So luong"),
        DocumentCell(row_index=0, col_index=3, text="Don gia"),
        DocumentCell(row_index=0, col_index=4, text="Thanh tien"),
    ]
    rows = [
        # Bracketed SKU with two hyphens
        DocumentCell(row_index=1, col_index=0, text="1"),
        DocumentCell(row_index=1, col_index=1, text="Giay in photocopy [PAPER-A4-80]"),
        DocumentCell(row_index=1, col_index=2, text="50"),
        DocumentCell(row_index=1, col_index=3, text="80.000"),
        DocumentCell(row_index=1, col_index=4, text="4.000.000"),
        # Unbracketed hyphenated SKU
        DocumentCell(row_index=2, col_index=0, text="2"),
        DocumentCell(row_index=2, col_index=1, text="Laptop Dell LAP-DELL-5520 Core i7"),
        DocumentCell(row_index=2, col_index=2, text="2"),
        DocumentCell(row_index=2, col_index=3, text="25.000.000"),
        DocumentCell(row_index=2, col_index=4, text="50.000.000"),
    ]
    table = DocumentTable(
        id="tbl-hyphenated-skus",
        page_index=0,
        row_count=3,
        column_count=5,
        cells=headers + rows,
    )
    extractor = StructureAwareTableExtractor()
    lines = extractor.extract_invoice_lines(table)

    assert len(lines) == 2
    assert lines[0].sku_ref == "PAPER-A4-80"
    assert lines[1].sku_ref == "LAP-DELL-5520"


def test_table_extractor_filters_summary_rows():
    """Verify that table footer rows like 'Cộng tiền hàng' or 'Tổng cộng' are ignored."""
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Tên hàng hóa"),
        DocumentCell(row_index=0, col_index=2, text="Số lượng"),
        DocumentCell(row_index=0, col_index=3, text="Đơn giá"),
        DocumentCell(row_index=0, col_index=4, text="Thành tiền"),
    ]
    rows = [
        # Line 1
        DocumentCell(row_index=1, col_index=0, text="1"),
        DocumentCell(row_index=1, col_index=1, text="Bàn làm việc gỗ sồi"),
        DocumentCell(row_index=1, col_index=2, text="2"),
        DocumentCell(row_index=1, col_index=3, text="3.500.000"),
        DocumentCell(row_index=1, col_index=4, text="7.000.000"),
        # Table Summary Row 1: Cong tien hang
        DocumentCell(row_index=2, col_index=0, text=""),
        DocumentCell(row_index=2, col_index=1, text="Cộng tiền hàng (Subtotal)"),
        DocumentCell(row_index=2, col_index=2, text=""),
        DocumentCell(row_index=2, col_index=3, text=""),
        DocumentCell(row_index=2, col_index=4, text="7.000.000"),
        # Table Summary Row 2: Tien thue
        DocumentCell(row_index=3, col_index=0, text=""),
        DocumentCell(row_index=3, col_index=1, text="Tiền thuế GTGT (8%)"),
        DocumentCell(row_index=3, col_index=2, text=""),
        DocumentCell(row_index=3, col_index=3, text=""),
        DocumentCell(row_index=3, col_index=4, text="560.000"),
        # Table Summary Row 3: Tong cong
        DocumentCell(row_index=4, col_index=0, text=""),
        DocumentCell(row_index=4, col_index=1, text="Tổng cộng tiền thanh toán"),
        DocumentCell(row_index=4, col_index=2, text=""),
        DocumentCell(row_index=4, col_index=3, text=""),
        DocumentCell(row_index=4, col_index=4, text="7.560.000"),
    ]
    table = DocumentTable(
        id="tbl-with-summary-rows",
        page_index=0,
        row_count=5,
        column_count=5,
        cells=headers + rows,
    )
    extractor = StructureAwareTableExtractor()
    lines = extractor.extract_invoice_lines(table)

    # Exactly 1 real line item, 3 summary rows safely skipped
    assert len(lines) == 1
    assert lines[0].line_no == 1
    assert lines[0].description == "Bàn làm việc gỗ sồi"
    assert lines[0].line_amount == Decimal("7000000.0000")


def test_table_extractor_merges_multiline_description_and_expands_bbox():
    """Verify continuation lines merge text and expand the description BBox."""
    headers = [
        DocumentCell(row_index=0, col_index=0, text="STT"),
        DocumentCell(row_index=0, col_index=1, text="Tên hàng"),
        DocumentCell(row_index=0, col_index=2, text="Số lượng"),
        DocumentCell(row_index=0, col_index=3, text="Đơn giá"),
        DocumentCell(row_index=0, col_index=4, text="Thành tiền"),
    ]
    rows = [
        # Main row with initial description
        DocumentCell(row_index=1, col_index=0, text="1"),
        DocumentCell(
            row_index=1,
            col_index=1,
            text="Máy in laser Canon LBP 2900",
            bbox=_make_bbox(0, 100, 50, 300, 70),
        ),
        DocumentCell(row_index=1, col_index=2, text="1"),
        DocumentCell(row_index=1, col_index=3, text="3.200.000"),
        DocumentCell(row_index=1, col_index=4, text="3.200.000"),
        # Continuation row 1
        DocumentCell(
            row_index=2,
            col_index=1,
            text="(Kèm 01 hộp mực chính hãng Cartridge 303)",
            bbox=_make_bbox(0, 100, 75, 320, 95),
        ),
        # Continuation row 2
        DocumentCell(
            row_index=3,
            col_index=1,
            text="(Bảo hành 12 tháng tại trung tâm ủy quyền)",
            bbox=_make_bbox(0, 100, 100, 350, 120),
        ),
    ]
    table = DocumentTable(
        id="tbl-multiline-bbox",
        page_index=0,
        row_count=4,
        column_count=5,
        cells=headers + rows,
    )
    extractor = StructureAwareTableExtractor()
    lines, evidence = extractor.extract_invoice_lines_with_evidence(table)

    assert len(lines) == 1
    assert "Máy in laser Canon LBP 2900" in lines[0].description
    assert "Kèm 01 hộp mực chính hãng" in lines[0].description
    assert "Bảo hành 12 tháng" in lines[0].description

    # Find description evidence
    desc_ev = next(ev for ev in evidence if ev.field_path == "lines[0].description")
    assert desc_ev.bbox is not None
    # BBox must span from top of line 1 (y0=50) to bottom of continuation line 2 (y1=120)
    assert desc_ev.bbox.y0 == 50
    assert desc_ev.bbox.y1 == 120
    assert desc_ev.bbox.x1 == 350
