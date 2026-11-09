from dataclasses import dataclass
import threading
from unittest.mock import patch

from invoiceflow.infrastructure.document.docling_adapter import (
    DoclingAdapter,
    DoclingPatchStatus,
    spatial_group_cells,
)


@dataclass
class MockBox:
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class MockCell:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    from_ocr: bool = True


def test_spatial_group_cells_one_column_order():
    """Verify standard single column top-to-bottom reading order."""
    cells = [
        MockCell(
            text="CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", left=50.0, top=20.0, right=400.0, bottom=35.0
        ),
        MockCell(
            text="Độc lập - Tự do - Hạnh phúc", left=100.0, top=40.0, right=350.0, bottom=55.0
        ),
        MockCell(text="HÓA ĐƠN GIÁ TRỊ GIA TĂNG", left=120.0, top=80.0, right=380.0, bottom=100.0),
    ]
    lines = spatial_group_cells(cells)
    assert len(lines) == 3
    assert lines[0][0].text.startswith("CỘNG HÒA")
    assert lines[1][0].text.startswith("Độc lập")
    assert lines[2][0].text.startswith("HÓA ĐƠN")


def test_spatial_group_cells_scrambled_boxes_reordered():
    """Verify that word boxes returned in arbitrary or reverse order by OCR
    are correctly sorted top-to-bottom, left-to-right."""
    scrambled = [
        MockCell(text="toán", left=80.0, top=88.0, right=140.0, bottom=102.0),
        MockCell(text="Thanh", left=10.0, top=90.0, right=70.0, bottom=104.0),
        MockCell(text="TNHH", left=80.0, top=48.0, right=140.0, bottom=62.0),
        MockCell(text="Công ty", left=10.0, top=50.0, right=70.0, bottom=65.0),
        MockCell(text="Việt Nam", left=150.0, top=51.0, right=230.0, bottom=64.0),
    ]
    lines = spatial_group_cells(scrambled)
    assert len(lines) == 2

    # Line 1: Công ty TNHH Việt Nam
    assert [c.text for c in lines[0]] == ["Công ty", "TNHH", "Việt Nam"]
    # Line 2: Thanh toán
    assert [c.text for c in lines[1]] == ["Thanh", "toán"]


def test_spatial_group_cells_height_skew_and_diacritics():
    """Verify that words with diacritics causing height skew (e.g. 'Ổ', 'Ậ', 'Ệ')
    are properly merged into the same reading line."""
    cells = [
        MockCell(text="ĐỒNG", left=10.0, top=100.0, right=60.0, bottom=118.0),
        MockCell(text="HỒ", left=70.0, top=98.0, right=100.0, bottom=119.0),
        MockCell(text="THỤY", left=110.0, top=102.0, right=160.0, bottom=116.0),
        MockCell(text="SỸ", left=170.0, top=99.0, right=200.0, bottom=121.0),
    ]
    lines = spatial_group_cells(cells)
    assert len(lines) == 1
    assert [c.text for c in lines[0]] == ["ĐỒNG", "HỒ", "THỤY", "SỸ"]


def test_spatial_group_cells_multi_line_table_cells():
    """Verify table row cells where columns are at varying horizontal positions."""
    cells = [
        MockCell(text="1", left=10.0, top=200.0, right=25.0, bottom=215.0),
        MockCell(text="Chuột không dây", left=35.0, top=200.0, right=180.0, bottom=215.0),
        MockCell(text="Logitech MX Master 3S", left=35.0, top=220.0, right=220.0, bottom=235.0),
        MockCell(text="Cái", left=240.0, top=200.0, right=270.0, bottom=215.0),
        MockCell(text="2.0000", left=290.0, top=200.0, right=340.0, bottom=215.0),
    ]
    lines = spatial_group_cells(cells)
    assert len(lines) == 2
    # Row first line: 1 | Chuột không dây | Cái | 2.0000
    assert len(lines[0]) == 4
    assert lines[0][0].text == "1"
    assert lines[0][1].text == "Chuột không dây"
    # Row wrapped description line: Logitech MX Master 3S
    assert len(lines[1]) == 1
    assert lines[1][0].text == "Logitech MX Master 3S"


def test_spatial_group_cells_empty():
    assert spatial_group_cells([]) == []


def test_docling_patch_status_transitions():
    """Verify patch status reporting and idempotency."""
    status = DoclingAdapter.get_patch_status()
    assert status in (
        DoclingPatchStatus.UNINITIALIZED,
        DoclingPatchStatus.ACTIVE,
        DoclingPatchStatus.UNAVAILABLE,
    )

    # Calling patch returns a valid status
    applied_status = DoclingAdapter._patch_docling_reading_order()
    assert applied_status in (DoclingPatchStatus.ACTIVE, DoclingPatchStatus.UNAVAILABLE)
    assert DoclingAdapter.get_patch_status() == applied_status


def test_docling_patch_thread_safety():
    """Verify that multiple concurrent threads calling _patch_docling_reading_order
    do not cause exceptions or race conditions."""
    results = []

    def worker():
        st = DoclingAdapter._patch_docling_reading_order()
        results.append(st)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(r == results[0] for r in results)


def test_docling_patch_handles_missing_internal_apis():
    """Verify that if Docling internal methods are not found, UNAVAILABLE is returned without error."""
    with patch("docling.utils.layout_postprocessor.LayoutPostprocessor", create=True) as mock_lp:
        # Mock class lacking _sort_cells
        if hasattr(mock_lp, "_sort_cells"):
            delattr(mock_lp, "_sort_cells")

        # Temporarily reset patch status
        orig_status = DoclingAdapter._patch_status
        try:
            DoclingAdapter._patch_status = DoclingPatchStatus.UNINITIALIZED
            with patch(
                "docling.models.stages.page_assemble.page_assemble_model.PageAssembleModel"
            ) as mock_pam:
                mock_pam.__call__ = None
                status = DoclingAdapter._patch_docling_reading_order()
                assert status == DoclingPatchStatus.UNAVAILABLE
        finally:
            DoclingAdapter._patch_status = orig_status
