# Document AI Core Reengineering & Experimental Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tái cấu trúc và nâng cấp toàn diện lõi Document AI của InvoiceFlow AI: trích xuất bảng nhận biết cấu trúc (Structure-aware Table Extraction), tối ưu hóa Docling/OCR pipeline, tăng cường nguồn gốc bằng chứng (Provenance & CanonicalDocument), bóc tách hóa đơn dựa trên schema chuẩn Việt Nam, định tuyến lai thông minh (Intelligent Hybrid Routing), và xây dựng hệ thống benchmark mở rộng (B0–B5) kèm nghiên cứu loại trừ (ablation studies).

**Architecture:** Modular Monolith tuân thủ quy tắc một chiều (`api -> application -> domain`, `infrastructure` triển khai ports). Lõi Document AI chuyển đổi từ xử lý văn bản phẳng (flattened text) sang mô hình cấu trúc 2 chiều kết hợp: Bảng (`DocumentTable` / `DocumentCell`) + Bố cục (`DocumentElement` / `BoundingBox`) + Nguồn gốc chi tiết (`FieldEvidence`). Định tuyến lai (Hybrid Router) dựa trên tín hiệu quan sát đa chiều (độ phủ text, mật độ bảng, tính nhất quán số học, độ tin cậy OCR) để quyết định giữa trích xuất tất định (deterministic), OCR cục bộ (Docling/RapidOCR), hay suy luận nhắm đích (Targeted Vision LLM).

**Tech Stack:** Python 3.12, Docling 2.87+, RapidOCR 3.8+, PyMuPDF (fitz), Pydantic v2, FastAPI, SQLAlchemy 2, pytest, React 19, TypeScript.

**Spec:** [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`docs/IMPLEMENTATION.md`](../IMPLEMENTATION.md), [`docs/QUALITY_BENCHMARK.md`](../QUALITY_BENCHMARK.md), [`docs/OPERATIONS.md`](../OPERATIONS.md).

## Global Constraints

- Không commit API keys, secrets, tokens, mật khẩu, private data; dùng Pydantic `Settings`.
- Tuyệt đối cấm hardcode model ID, timeouts, retries, thresholds, VAT rates; dùng `PolicyConfig` và `Settings`.
- Tiền tệ dùng `Decimal` / DB `NUMERIC(20,4)`; không dùng `float` cho tiền tệ; ngày tháng UTC trong DB.
- Cấm đặt tên file tạo nợ kỹ thuật: `*_v2`, `*_v3`, `*_new`, `*_old`, `*_fix`, `fix_*`, `*_final`.
- Code sạch, dễ đọc, cấm rải thanh phân cách `# ====================` hoặc `# --------------------`.
- Mọi thay đổi / bug fix phải có regression test trước, chỉ rõ root-cause trực tiếp và tham khảo dự án tương tự.
- Giữ vững 100% CI xanh và tương thích ngược với API contracts và frontend hiện hữu.

## Review Focus

1. **Table Column Semantic Misclassification:** Bảng hóa đơn có cột "STT", "Mã hàng", "Tên hàng", "ĐVT", "Số lượng", "Đơn giá", "Thành tiền" nhưng tiêu đề cột bị viết tắt hoặc multi-line; mapper phải phân loại đúng mà không làm lệch cột số tiền sang số lượng.
2. **Floating-point & Locale Number Parsing Ambiguity:** Chuỗi số như `12.000.000`, `1.234,56`, `200.000`, `5.500` phải được phân giải chính xác theo locale VN vs US; nếu mơ hồ phải giữ raw value và tạo review issue, không tự ý làm tròn hay biến thành 0.
3. **Multi-page & Rotated Scanned PDF Crash / OOM:** PDF scan nhiều trang (10-20 trang) hoặc trang bị xoay 90/270 độ không được làm tràn bộ nhớ Windows 16GB RAM hoặc timeout worker.
4. **Evidence & Coordinate Mismatch:** Tọa độ BBox từ Docling (bottom-left origin) khi chuyển sang PDF Viewer (top-left origin) phải đồng nhất tuyệt đối, không làm highlight lệch vùng văn bản trên UI.
5. **LLM Cost & Token Spillover:** Không gửi toàn bộ PDF sang LLM khi chỉ cần trích xuất bảng đã có cấu trúc hoặc khi pipeline tất định đã đạt độ tin cậy cao.

---

### Task 1: Canonical Document & Provenance Data Model Enhancement

**Files:**
- Modify: `src/invoiceflow/domain/documents/models.py`
- Test: `tests/unit/domain/test_canonical_provenance.py`

**Interfaces:**
- Produces:
  - Mở rộng `BoundingBox` hỗ trợ `rotation`, `page_width`, `page_height`.
  - Mở rộng `DocumentElement` và `DocumentCell` hỗ trợ `raw_text`, `normalized_text`, `parent_id`, `table_id`, `row_index`, `col_index`, `confidence`.
  - Mở rộng `CanonicalDocument` hỗ trợ `source_checksum`, `page_rotations`, `Union[UUID, str]` cho document/tenant IDs, và serialization roundtrip không mất metadata.

- [ ] **Step 1: Write test for CanonicalDocument enhancement, serialization, and provenance**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement enhanced fields in `src/invoiceflow/domain/documents/models.py`**
- [ ] **Step 4: Run test to verify all provenance invariants pass**

---

### Task 2: Structure-Aware Table Extraction & Column Semantic Mapping

**Files:**
- Create: `src/invoiceflow/infrastructure/document/table_extractor.py`
- Test: `tests/unit/document/test_table_extractor.py`

**Interfaces:**
- Produces: `StructureAwareTableExtractor`
  - Nhận diện cột ngữ nghĩa hóa đơn Việt Nam: `line_no` (STT), `sku` (Mã hàng), `description` (Tên hàng hóa dịch vụ), `unit` (ĐVT), `qty` (Số lượng), `unit_price` (Đơn giá), `discount` (Chiết khấu), `tax_rate` (Thuế suất), `line_amount` (Thành tiền).
  - Phân tích không gian (spatial alignment), gom nhóm hàng nhiều dòng (multi-line wrapped descriptions).
  - Trích xuất đủ 100% dòng hàng tương ứng trong bảng kèm liên kết source cell và BBox.
  - Phân biệt số lượng/đơn giá/thành tiền qua numeric consistency (`qty * unit_price ~= line_amount`).

- [ ] **Step 1: Write comprehensive test for table header semantic mapping and multi-line row grouping**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `StructureAwareTableExtractor` in `src/invoiceflow/infrastructure/document/table_extractor.py`**
- [ ] **Step 4: Run test to verify all test cases pass**

---

### Task 3: Context-Aware Numeric Parsing & Ambiguity Disambiguation

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/digital_pdf_parser.py`
- Test: `tests/unit/document/test_numeric_parsing.py`

**Interfaces:**
- Produces: `ContextAwareNumericParser`
  - Chuẩn hóa số học phân biệt: `12.000.000`, `12,000,000`, `1.234,56`, `1,234.56`, `200.000`, `200,000`, `5.5`, `5,500`.
  - Giữ nguyên `raw_value` và candidate `normalized_value`, gắn nhãn `AMBIGUOUS_NUMBER` hoặc `PARSE_ERROR` khi không chắc chắn.
  - Sử dụng `Decimal` tuyệt đối cho toàn bộ dữ liệu tài chính.

- [ ] **Step 1: Write tests for edge-case Vietnamese and international numeric formats**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Refactor numeric parsing logic in `digital_pdf_parser.py`**
- [ ] **Step 4: Run test to verify all numeric test cases pass**

---

### Task 4: Docling & OCR Pipeline Optimization (Orientation, Caching & Resource Guard)

**Files:**
- Modify: `src/invoiceflow/infrastructure/document/docling_adapter.py`
- Modify: `src/invoiceflow/infrastructure/document/pdf_inspector.py`
- Test: `tests/unit/document/test_docling_ocr_pipeline.py`

**Interfaces:**
- Produces:
  - Phân loại trang: Native text, Scanned image, Mixed, Rotated, Low-quality scan.
  - Khử xoay (page orientation analysis & rotation correction) trước khi OCR.
  - Quản lý bộ nhớ đệm model và giải phóng bộ nhớ (cleanup temp files, lazy converter caching) phù hợp Windows 16GB RAM.
  - Giới hạn trang an toàn qua settings `DOCLING_MAX_PAGES` và DPI cấu hình `DOCLING_OCR_DPI`.

- [ ] **Step 1: Write test for page classification, orientation correction, and resource bounding**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement enhancements in `docling_adapter.py` and `pdf_inspector.py`**
- [ ] **Step 4: Run test to verify accurate OCR and resource safety**

---

### Task 5: Intelligent Hybrid Routing & Pipeline Coordination

**Files:**
- Modify: `src/invoiceflow/application/processing/document_router.py`
- Modify: `src/invoiceflow/application/processing/coordinator.py`
- Modify: `src/invoiceflow/application/processing/evidence_mapper.py`
- Test: `tests/unit/document/test_hybrid_router.py`
- Test: `tests/integration/test_worker_pipeline.py`

**Interfaces:**
- Produces:
  - `DocumentRouter.decide_route`: Đánh giá tín hiệu đa chiều (độ phủ text, mật độ bảng, tính đầy đủ của trường bắt buộc, tính nhất quán số học).
  - Tích hợp `StructureAwareTableExtractor` vào luồng `_process_pdf` của `DocumentCoordinator`.
  - Ánh xạ bằng chứng (`evidence_mapper`) liên kết chính xác `source_page`, `source_element_id`, `source_table_id`, `source_cell_id`, `bounding_box`.

- [ ] **Step 1: Write tests for multi-signal routing decisions and coordinator table integration**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Update `document_router.py`, `coordinator.py`, and `evidence_mapper.py`**
- [ ] **Step 4: Run tests to verify end-to-end integration passes**

---

### Task 6: Expanded Benchmark Suite (B0–B5), Ablation Studies & Evaluation Runner

**Files:**
- Create: `benchmarks/fixtures/samples/synthetic_cases_expanded.json`
- Modify: `benchmarks/fixtures/casebook_manifest.json`
- Modify: `benchmarks/scripts/evaluator.py`
- Modify: `benchmarks/scripts/run_benchmark.py`
- Create: `benchmarks/scripts/run_ablation.py`
- Test: `tests/unit/test_benchmark_evaluator.py`

**Interfaces:**
- Produces:
  - Mở rộng tập test từ 5 chứng từ lên tập benchmark đa dạng (digital PDF, scan OCR, bảng phức tạp, hóa đơn nhiều thuế suất, tài liệu xoay).
  - Định nghĩa rõ 6 Baselines:
    - B0: XML Direct Parser
    - B1: PyMuPDF + Rule Heuristics
    - B2: Docling Text + Rules
    - B3: Docling OCR + Structured Tables
    - B4: Pure Vision LLM
    - B5: InvoiceFlow Hybrid Document AI
  - Bổ sung metrics: Table Structure F1, Header EM, Line F1, CER/WER, Latency p50/p95, Cost/1k.
  - Nghiên cứu loại trừ (Ablations): Without Table Structure, Without OCR, Without Validation, Without Vision Fallback.

- [ ] **Step 1: Expand ground truth fixtures and manifest**
- [ ] **Step 2: Update evaluator metrics (Table F1, CER, Exact Match)**
- [ ] **Step 3: Implement B0–B5 baselines in `run_benchmark.py` and ablation runner in `run_ablation.py`**
- [ ] **Step 4: Execute benchmarks and generate empirical results artifact**

---

### Task 7: Comprehensive Regression Verification, Documentation & CI Acceptance

**Files:**
- Modify: `docs/QUALITY_BENCHMARK.md` (cập nhật kết quả benchmark thực tế và bảng ablation)
- Modify: `docs/ARCHITECTURE.md` (cập nhật kiến trúc Document AI mới)
- Run: `scripts/run_all_checks.py`

- [ ] **Step 1: Run complete test suite (unit + integration + security + e2e + benchmarks)**
- [ ] **Step 2: Update documentation in-place**
- [ ] **Step 3: Commit, push to GitHub, and verify 100% Green CI**
