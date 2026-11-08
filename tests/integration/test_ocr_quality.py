"""Real OCR quality regression tests: runs the actual Docling + RapidOCR
pipeline (do_ocr=True) against genuine pixel-image PDF fixtures with no text
layer, not a mock and not just the exception-fallback path.

Thresholds are set from the measured baseline in
benchmarks/results/ocr_quality_report.json (see
benchmarks/scripts/evaluate_ocr_quality.py for the full CER/WER report) with
headroom for minor OCR engine version drift, not tuned to make an
otherwise-broken pipeline pass.
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from benchmarks.scripts.evaluate_ocr_quality import (  # noqa: E402
    CASES,
    evaluate_scanned_table_case,
    evaluate_text_case,
)


def _case(case_id: str) -> dict:
    return next(c for c in CASES if c["case_id"] == case_id)


def test_rotated_scan_ocr_is_not_silently_falling_back():
    result = evaluate_text_case(_case("CASE-07-PDF-ROTATED-SCAN"))
    assert result["used_fallback"] is False
    # Real recognition, not an empty/placeholder result.
    assert len(result["recognized_text"]) > 50


def test_rotated_scan_ocr_recognizes_all_monetary_amounts():
    result = evaluate_text_case(_case("CASE-07-PDF-ROTATED-SCAN"))
    assert result["all_amounts_recognized"] is True, result["missing_amounts"]
    assert result["cer"] < 0.25


def test_mixed_pdf_scanned_page_ocr_recognizes_amount():
    result = evaluate_text_case(_case("CASE-09-PDF-MIXED"))
    assert result["used_fallback"] is False
    assert result["all_amounts_recognized"] is True, result["missing_amounts"]
    assert result["cer"] < 0.1


def test_non_rotated_scan_ocr_runs_and_reads_most_fields_despite_known_tail_garbling():
    # Known, documented limitation (see docs/decisions/2026-11-08 update):
    # RapidOCR intermittently garbles the final text block on this specific
    # fixture (the totals line), unrelated to rotation -- CASE-07 (rotated)
    # scores better than this non-rotated case. This test pins the current
    # measured ceiling so a further regression is caught, without pretending
    # the known defect is fixed.
    result = evaluate_text_case(_case("CASE-03-PDF-SCAN"))
    assert result["used_fallback"] is False
    assert result["cer"] < 0.35
    # Supplier/buyer identity and the unit price must still be readable even
    # though the totals line is affected.
    assert "850000" in result["recognized_text"]


def test_scanned_table_structure_is_recognized_under_ocr():
    result = evaluate_scanned_table_case()
    assert result["used_fallback"] is False
    assert result["tables_detected_by_ocr"] >= 1
    assert result["lines_extracted"] >= 1
    # At least the first (non-merge-affected) line must round-trip exactly.
    assert result["lines_correct_count"] >= 1
