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
