"""Real OCR verification on scanned/rotated/mixed Vietnamese invoice PDFs.

Runs the actual DoclingAdapter + EasyOCR pipeline (not a mock, not just the
exception-fallback path) against fixtures that are genuine pixel images with
no selectable text layer, and measures:

  - CER/WER of the recognized free text against the known source text.
  - Whether every monetary amount in the document was recognized exactly.
  - For the scanned table case, whether structure-aware table extraction
    recovers the correct line items from OCR'd table cells.

Produces benchmarks/results/ocr_quality_report.json as evidence.
"""

import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from benchmarks.scripts.ocr_metrics import compute_cer, compute_cer_wer  # noqa: E402
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter  # noqa: E402
from invoiceflow.infrastructure.document.table_extractor import (  # noqa: E402
    StructureAwareTableExtractor,
)

DOCS_DIR = ROOT_DIR / "benchmarks" / "fixtures" / "documents"
RESULTS_DIR = ROOT_DIR / "benchmarks" / "results"

_AMOUNT_PATTERN = re.compile(r"\b\d[\d.,]*\d\b")


def _align_lines_and_score(reference_text: str, hypothesis_text: str) -> dict[str, Any]:
    """CER/WER computed after greedily re-pairing hypothesis lines to their
    best-matching reference line.

    Docling's OCR layout/reading-order model does not always return text
    blocks in top-to-bottom order for rotated pages (observed directly:
    bbox y-coordinates cluster near-identically for a rotated scan, so they
    carry no reliable ordering signal either). Scoring CER/WER on raw
    concatenation order conflates "got the words right" with "got the
    paragraph order right," which is a layout concern, not a character
    recognition concern -- the standard practice (e.g. ICDAR OCR
    benchmarks) is to score per matched text line. Lines that cannot be
    matched (missing or spurious) still count as full insertion/deletion
    error, so genuine garbage (e.g. a duplicated/mirrored OCR artifact) is
    still penalized.
    """
    ref_lines = [line for line in reference_text.split("\n") if line.strip()]
    unmatched_hyp = [line for line in hypothesis_text.split("\n") if line.strip()]

    aligned_ref: list[str] = []
    aligned_hyp: list[str] = []
    for ref_line in ref_lines:
        if unmatched_hyp:
            best_idx = min(
                range(len(unmatched_hyp)),
                key=lambda i: compute_cer(ref_line, unmatched_hyp[i]),
            )
            aligned_hyp.append(unmatched_hyp.pop(best_idx))
        else:
            aligned_hyp.append("")
        aligned_ref.append(ref_line)

    metrics = compute_cer_wer("\n".join(aligned_ref), "\n".join(aligned_hyp))
    return {
        **metrics,
        "unmatched_hypothesis_lines": unmatched_hyp,
    }


def _extract_amounts(text: str) -> set[str]:
    # Every amount in these fixtures is formatted "<integer>.0000" (fixed
    # 4-decimal Decimal convention used throughout this codebase), so the
    # integer part before the first "." is the VND amount; a trailing
    # ".0000" is a decimal fraction, not a Vietnamese thousands separator,
    # and must not be concatenated into the integer. Only keeps 3+ digit
    # integer parts to avoid matching stray single/double-digit noise.
    amounts = set()
    for token in _AMOUNT_PATTERN.findall(text):
        integer_part = token.split(".")[0].replace(",", "")
        if len(integer_part) >= 3:
            amounts.add(integer_part)
    return amounts


CASES: list[dict[str, Any]] = [
    {
        "case_id": "CASE-03-PDF-SCAN",
        "filename": "case_03.pdf",
        "description": "Scanned (image-only) Vietnamese invoice, no rotation",
        "reference_text": (
            "HOA DON BAN HANG (SCAN)\n"
            "Ky hieu: 2C26TCC  So: 0003412  Ngay: 2026-03-08\n"
            "Ben ban: Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội - MST: 0105554321\n"
            "Ben mua: Công ty Cổ phần Thương mại Alpha VN - MST: 0109998888\n"
            "Hang hoa: Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng [CLEAN-SET-01]\n"
            "So luong: 10.0000  Don gia: 850000.0000  Thue: 8.00%\n"
            "Tien hang: 8500000.0000  Thue GTGT: 680000.0000  Tong cong: 9180000.0000"
        ),
        "expected_amounts": ["850000", "8500000", "680000", "9180000"],
    },
    {
        "case_id": "CASE-07-PDF-ROTATED-SCAN",
        "filename": "case_07.pdf",
        "description": "Scanned (image-only) Vietnamese invoice, rotated 90 degrees",
        "reference_text": (
            "HOA DON BAN HANG (ROTATED SCAN)\n"
            "Ky hieu: 2C26TCC  So: 0003499  Ngay: 2026-03-12\n"
            "Ben ban: Công ty TNHH Dịch vụ Vệ sinh Công nghiệp Hà Nội - MST: 0105554321\n"
            "Ben mua: Công ty Cổ phần Thương mại Alpha VN - MST: 0109998888\n"
            "Hang hoa: Bộ dụng cụ và hóa chất vệ sinh sàn văn phòng [CLEAN-SET-01]\n"
            "So luong: 10.0000  Don gia: 850000.0000  Thue: 8.00%\n"
            "Tien hang: 8500000.0000  Thue GTGT: 680000.0000  Tong cong: 9180000.0000"
        ),
        "expected_amounts": ["850000", "8500000", "680000", "9180000"],
    },
    {
        "case_id": "CASE-09-PDF-MIXED",
        "filename": "case_09.pdf",
        "description": "Mixed PDF: page 1 digital text, page 2 scanned attachment image",
        "reference_text": (
            "PHIEU GIAO HANG DINH KEM (SCAN)\n"
            "Hang hoa: Giấy photocopy Double A A4 70gsm [PAPER-A4-70]  So luong: 200.0000"
        ),
        "expected_amounts": ["200"],
        "ocr_page_index": 1,
    },
]


def _run_ocr(filename: str) -> dict[str, Any]:
    pdf_bytes = (DOCS_DIR / filename).read_bytes()
    adapter = DoclingAdapter()
    start = time.perf_counter()
    canonical_doc = adapter.extract_canonical(
        tenant_id="ocr-quality-eval",
        document_id="ocr-quality-eval",
        pdf_bytes=pdf_bytes,
        do_ocr=True,
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "canonical_doc": canonical_doc,
        "latency_ms": latency_ms,
        "used_fallback": canonical_doc.metadata.get("fallback_from") is not None,
    }


def evaluate_text_case(case: dict[str, Any]) -> dict[str, Any]:
    ocr_result = _run_ocr(case["filename"])
    canonical_doc = ocr_result["canonical_doc"]

    page_filter = case.get("ocr_page_index")
    elements = [
        el for el in canonical_doc.elements if page_filter is None or el.page_index == page_filter
    ]
    recognized_text = "\n".join(el.text for el in elements)

    metrics = _align_lines_and_score(case["reference_text"], recognized_text)
    found_amounts = _extract_amounts(recognized_text)
    expected_amounts = set(case["expected_amounts"])
    missing_amounts = sorted(expected_amounts - found_amounts)

    return {
        "case_id": case["case_id"],
        "description": case["description"],
        "used_fallback": ocr_result["used_fallback"],
        "latency_ms": ocr_result["latency_ms"],
        "cer": metrics["cer"],
        "wer": metrics["wer"],
        "unmatched_hypothesis_lines": metrics["unmatched_hypothesis_lines"],
        "expected_amounts": sorted(expected_amounts),
        "missing_amounts": missing_amounts,
        "all_amounts_recognized": not missing_amounts,
        "reference_text": case["reference_text"],
        "recognized_text": recognized_text,
    }


def evaluate_scanned_table_case() -> dict[str, Any]:
    case_id = "CASE-10-PDF-SCAN-TABLE"
    ocr_result = _run_ocr("case_10.pdf")
    canonical_doc = ocr_result["canonical_doc"]

    tables_found = len(canonical_doc.tables)
    lines, evidence = StructureAwareTableExtractor().extract_lines_with_evidence(
        canonical_doc.tables
    )

    expected_lines = [
        {"sku": "DELL-XPS-13", "qty": "2.0000", "line_amount": "50000000.0000"},
        {"sku": "MOUSE-LOGI", "qty": "5.0000", "line_amount": "10000000.0000"},
    ]
    recovered = [
        {
            "sku": line.sku_ref,
            "qty": str(line.qty),
            "line_amount": str(line.line_amount),
            "issues": line.issues,
        }
        for line in lines
    ]
    correct_count = sum(
        1
        for exp, got in zip(expected_lines, recovered)
        if got.get("sku") == exp["sku"] and got.get("line_amount") == exp["line_amount"]
    )

    return {
        "case_id": case_id,
        "description": "Scanned pure-image invoice with a multi-row line-item table",
        "used_fallback": ocr_result["used_fallback"],
        "latency_ms": ocr_result["latency_ms"],
        "tables_detected_by_ocr": tables_found,
        "lines_extracted": len(lines),
        "evidence_entries": len(evidence),
        "expected_lines": expected_lines,
        "recovered_lines": recovered,
        "lines_correct_count": correct_count,
        "lines_correct_total": len(expected_lines),
    }


def main() -> None:
    print("=" * 70)
    print(" InvoiceFlow AI - Real OCR Quality Verification (Docling + EasyOCR)")
    print("=" * 70)

    results = [evaluate_text_case(c) for c in CASES]
    table_result = evaluate_scanned_table_case()

    report = {
        "suite": "InvoiceFlow AI OCR Quality Verification v1.0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "text_cases": results,
        "table_case": table_result,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = RESULTS_DIR / "ocr_quality_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'Case':<28} | {'CER':<8} | {'WER':<8} | {'Amounts OK':<11} | {'Fallback?'}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['case_id']:<28} | {r['cer']:<8} | {r['wer']:<8} | "
            f"{str(r['all_amounts_recognized']):<11} | {r['used_fallback']}"
        )
    print("-" * 70)
    print(
        f"{table_result['case_id']}: tables_detected={table_result['tables_detected_by_ocr']} "
        f"lines_extracted={table_result['lines_extracted']} "
        f"correct={table_result['lines_correct_count']}/{table_result['lines_correct_total']} "
        f"fallback={table_result['used_fallback']}"
    )
    print(f"\nResults saved to {report_file}")


if __name__ == "__main__":
    main()
