# Document AI Core Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Document AI Core into a structured, accurate, evidence-traceable, and production-ready invoice processing pipeline on Windows CPU environments without breaking existing business services (Auth, Ingestion, 3-Way Matching, Human Review, CAS Approval, Accounting Export).

**Architecture:** Modular monolith with ports and adapters. Entrypoint `DocumentAIService` coordinates inspection, classification, routing, deterministic XML / PyMuPDF digital parsing, Docling + EasyOCR scanned processing with adapter-level spatial reading-order normalization, structured table extraction, and evidence-grounded Vision AI fallback with strict financial integrity checks.

**Tech Stack:** Python 3.12, Docling 2.87.0, EasyOCR 1.7.2, PyMuPDF (fitz) 1.27.2, Pydantic v2, FastAPI, SQLAlchemy 2 (asyncpg/aiosqlite), Dramatiq, React + Vite.

**Spec:** Document AI Core Rebuild Specification (`P0` through `P8`).

## Global Constraints

- **No Monkey-Patching:** Do not patch internal site-packages or Docling private methods (`LayoutPostprocessor._sort_cells`, `PageAssembleModel.__call__`). Use official Docling pipeline options and perform layout/reading-order normalization at the adapter layer after conversion.
- **Classification Contract:** Exact classifications: `xml_invoice`, `digital_pdf`, `scanned_pdf`, `mixed_pdf`, `invalid_document`.
- **Coordinate Integrity:** PDF points coordinate system throughout; BBoxes must match physical viewer coordinates; support 0°, 90°, 180°, 270° without double rotation or loss of digital text layers.
- **Financial Precision:** Absolute `Decimal` precision for all money and quantity calculations; no floating-point arithmetic.
- **Preserve Valid OCR:** Never overwrite valid positive OCR quantities or prices with Vision proposals; record conflicting candidates with provenance and trigger Human Review.
- **Missing Value Semantics:** Clearly distinguish `VALID`, `ZERO`, `MISSING`, `INVALID`, `UNCERTAIN`, `CONFLICT`. Never convert missing data into zero without issue flags.
- **Hardware Profile:** Optimized for Windows CPU, 16 GB RAM; lazy-load weights, cache converters thread-safely.
- **Code Hygiene:** Strictly adhere to `AGENTS.md` (no `*_v2`, `*_new`, `*_fix` filenames, no decorative banners `# ===`).

## Review Focus

1. **Unpatched Docling Layout Normalization:** Scanned documents must have words and lines assembled in natural top-to-bottom, left-to-right reading order without monkey patching.
2. **Rotated PDF Text Layer Preservation:** Digital PDFs with non-zero `/Rotate` must not be rasterized into scanned images; text layer must remain pristine.
3. **Hyphenated SKU Preservation:** SKUs with dashes (e.g. `PAPER-A4-80`, `LAP-DELL-5520`, `MOUSE-LOGI`) must never be truncated.
4. **Cell Merge Handling:** Table rows with merged cells (like CASE-10 row 2) must keep unrecovered fields flagged (`QTY_UNRECOVERED`) until verified by arithmetic reconciliation or reviewer.
5. **Human Review / Approval Gate:** Invoices with unresolved candidate conflicts or arithmetic mismatches must strictly block approval.

---

## Tasks

### Task 1: P0 — Rebuild DoclingAdapter (Remove Monkey-Patch & Implement Adapter-Level Spatial Reading Order)

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/docling_adapter.py`
- Modify: `tests/unit/document/test_docling_reading_order.py`
- Modify: `tests/unit/document/test_docling_adapter.py`

**Steps:**
- [x] Remove `_patch_docling_reading_order`, `_patch_status`, `_patch_lock`, and all monkey-patching of `LayoutPostprocessor` and `PageAssembleModel`.
- [x] Configure official `DocumentConverter` with official `PdfPipelineOptions`, `EasyOcrOptions(lang=['vi', 'en'])`, and official `table_structure_options`.
- [x] Implement adapter-level post-conversion spatial reading-order normalization in `DoclingAdapter.extract_canonical()`: extract elements and text from `res.pages[p].predictions.layout.clusters` using `spatial_group_cells()`, preserving layout bands and Vietnamese diacritics.
- [x] Update unit tests in `test_docling_reading_order.py` and `test_docling_adapter.py` to verify official conversion without monkey-patching.
- [x] Run unit tests to confirm green.

### Task 2: P0 — Document Classification & Mixed PDF Per-Page Inspection

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/pdf_inspector.py`
- Modify: `src/invoiceflow/application/processing/document_router.py`
- Modify: `src/invoiceflow/application/processing/service.py`
- Test: `tests/unit/document/test_pdf_inspector.py`
- Test: `tests/unit/document/test_document_router.py`

**Steps:**
- [x] Update `PDFInspector` to classify `digital_pdf`, `scanned_pdf`, `mixed_pdf`, `invalid_document` with backward-compatible aliases for existing callers.
- [x] Implement per-page inspection and classification for mixed PDFs (`page_classifications: {0: "digital", 1: "scanned", ...}`).
- [x] Ensure digital pages are never routed to heavy OCR needlessly, and scanned pages are never routed to empty digital extraction.
- [x] Update router and service to accept the standardized classification types.
- [x] Run `pytest tests/unit/document/test_pdf_inspector.py tests/unit/document/test_document_router.py` to confirm.

### Task 3: P0 & P1 — PDF Rotation Normalization, Coordinate Systems & Preprocessing

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/docling_adapter.py`
- Modify: `src/invoiceflow/application/processing/service.py`
- Create: `tests/integration/test_pdf_rotation_coordinates.py`

**Steps:**
- [x] Implement safe rotation normalization that inspects page type: if digital text exists, preserve native text layer without rasterization; if scanned image, normalize orientation cleanly into upright raster.
- [x] Ensure bounding boxes are converted to standardized PDF points matching PDF Viewer coordinate origins (top-left vs bottom-left consistency).
- [x] Write integration test `tests/integration/test_pdf_rotation_coordinates.py` testing BBoxes on 0°, 90°, 180°, and 270° pages.
- [x] Run test to verify coordinate alignment.

### Task 4: P2 — Structure-Aware Table Extraction & Line Item Parsing

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/table_extractor.py`
- Modify: `src/invoiceflow/infrastructure/document/digital_pdf_parser.py`
- Test: `tests/unit/document/test_table_extractor.py`
- Test: `tests/unit/document/test_digital_pdf_parser.py`

**Steps:**
- [x] Ensure hyphenated SKUs (`PAPER-A4-80`, `LAP-DELL-5520`, `MOUSE-LOGI`) are preserved in both table extractor and digital parser regexes.
- [x] Support robust cell mapping: detect merged cells, continuation rows, and assign semantic column roles based on header analysis.
- [x] For merged cells (e.g. CASE-10), flag `QTY_UNRECOVERED` and `CELL_MERGE_SUSPECTED` rather than creating synthetic values.
- [x] Run unit tests for table extraction and digital parsing.

### Task 5: P3 & P4 — Missing Value Semantics & Vision AI Evidence-Based Fallback

**Files:**
- Modify: `src/invoiceflow/domain/invoices/models.py`
- Modify: `src/invoiceflow/application/processing/service.py`
- Test: `tests/unit/document/test_service_reconciliation.py`

**Steps:**
- [x] Add explicit `FieldVerificationState` enum (`VALID`, `ZERO`, `MISSING`, `INVALID`, `UNCERTAIN`, `CONFLICT`, `ARITHMETICALLY_CONSISTENT`, `MODEL_PROPOSED`, `HUMAN_APPROVED`).
- [x] Ensure missing numeric values retain missing/uncertain semantics without converting to zero unless marked.
- [x] Refine multi-factor line matching and Vision fallback in `DocumentAIService`: keep OCR and Vision candidates distinct; resolve quantities only when arithmetic passes; flag conflicts for Human Review.
- [x] Run `pytest tests/unit/document/test_service_reconciliation.py`.

### Task 6: P5, P6, P7 & P8 — Verification, Benchmarking, Performance & Final Acceptance

**Files:**
- Modify: `benchmarks/scripts/evaluate_ocr_quality.py`
- Modify: `scripts/run_application_qa.py`
- Documentation: `docs/IMPLEMENTATION.md`, `docs/ARCHITECTURE.md`, `docs/QUALITY_BENCHMARK.md`

**Steps:**
- [x] Run Tier A Pure OCR evaluation (`python benchmarks/scripts/evaluate_ocr_quality.py`) and verify CER/WER.
- [x] Run Tier B Application QA (`python scripts/run_application_qa.py`) across all 10 casebook documents.
- [x] Run full Pytest test suite (`pytest -q`).
- [x] Run frontend build (`npm --prefix apps/web run build`).
- [x] Update documentation in-place (`IMPLEMENTATION.md`, `ARCHITECTURE.md`, `QUALITY_BENCHMARK.md`).
- [x] Final git status check and ready-to-merge summary.
