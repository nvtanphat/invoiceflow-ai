# InvoiceFlow AI End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai toàn bộ hệ thống InvoiceFlow AI — hệ thống bóc tách hóa đơn đầu vào AP (Accounts Payable), xác thực số học, đối soát 2/3-way PO/GRN, quản lý review/approval đồng thời, xuất dữ liệu và benchmark tái lập theo đúng kiến trúc Modular Monolith và quy tắc trong `AGENTS.md`.

**Architecture:** Modular monolith với ranh giới ports/adapters một chiều (`api -> application -> domain`, `infrastructure` triển khai ports). Nguồn sự thật lưu trữ tại PostgreSQL; lưu trữ tệp qua Object Storage; hàng đợi bất đồng bộ qua Redis + Dramatiq worker; AI suy luận ngữ nghĩa qua Gemini API có giới hạn ngân sách và evidence mapping; giao diện review và matching xây dựng bằng React 19 + TypeScript + Vite + PDF.js.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, Dramatiq + Redis, defusedxml/PyMuPDF, google-genai, openpyxl, pytest, React 19, TypeScript, Vite, TailwindCSS, TanStack Query, Docker Compose.

**Spec:** [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`docs/IMPLEMENTATION.md`](../IMPLEMENTATION.md), [`docs/QUALITY_BENCHMARK.md`](../QUALITY_BENCHMARK.md), [`docs/OPERATIONS.md`](../OPERATIONS.md), [`docs/REFERENCES.md`](../REFERENCES.md).

## Global Constraints

- Python 3.12, layout `src/invoiceflow`, quản lý gói bằng `uv` (`pyproject.toml`).
- Không commit API keys, secrets, tokens, mật khẩu, private data; dùng Pydantic `Settings` và `.env.example`.
- Tuyệt đối cấm hardcode model ID, timeouts, retries, thresholds, VAT rates; dùng `PolicyConfig` và `Settings`.
- Tiền tệ dùng `Decimal` / DB `NUMERIC(20,4)`; không dùng `float` cho tiền tệ; ngày tháng UTC trong DB.
- Cấm đặt tên file tạo nợ kỹ thuật: `*_v2`, `*_v3`, `*_new`, `*_old`, `*_fix`, `fix_*`, `*_final`.
- Code sạch, dễ đọc, cấm rải thanh phân cách `# ====================` hoặc `# --------------------`.
- Mọi bug fix phải có failing regression test trước, chỉ rõ root-cause trực tiếp và tham khảo dự án tương tự.
- Luôn đọc file `SKILL.md` của skill liên quan trong `.agents/skills/` trước khi code từng thành phần.

## Review Focus

1. **XXE & Malicious Uploads:** XML chứa entity nội/ngoại (`<!ENTITY>`), PDF mã hóa hoặc chứa file thực thi → bị chặn ngay tại tiền xử lý mà không sập worker.
2. **Race condition & Stale Review Submission:** Hai kế toán cùng duyệt một hóa đơn; người gửi sau với revision cũ phải nhận HTTP `409 CONFLICT` thay vì ghi đè im lặng.
3. **Floating Point Rounding & Currency Calculation:** Tổng tiền, tiền thuế, chiết khấu lẻ từng dòng được cộng dồn bằng `Decimal` chính xác tuyệt đối, không lệch 1 đồng do float IEEE-754.
4. **Tenant Isolation Breach:** Truy vấn dữ liệu của tenant A bằng UUID của tenant B phải trả `404` hoặc `403`, tuyệt đối không rò rỉ dữ liệu giữa các tenant.
5. **CSV Formula Injection:** Tên nhà cung cấp hoặc mô tả hàng chứa ký tự `=cmd|...` hoặc `@SUM` khi xuất file CSV/Excel phải được trung hòa an toàn.

---

### Task 1: Project Scaffolding, Environment & Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `docker-compose.yml`
- Create: `src/invoiceflow/__init__.py`
- Create: `src/invoiceflow/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings` Pydantic class (`src/invoiceflow/config.py`) cung cấp cấu hình ứng dụng: `DATABASE_URL`, `REDIS_URL`, `STORAGE_ENDPOINT`, `GEMINI_API_KEY`, `APP_ENV`, `JWT_SECRET`, v.v.

- [x] **Step 1: Write test for Settings configuration**
- [x] **Step 2: Run test to verify it fails**
- [x] **Step 3: Implement `pyproject.toml`, `.env.example`, `.gitignore`, `src/invoiceflow/config.py`**
- [x] **Step 4: Run test to verify it passes**
- [x] **Step 5: Verify environment with `uv sync`**

---

### Task 2: Domain Entities & Business Schemas

**Files:**
- Create: `src/invoiceflow/domain/documents/models.py`
- Create: `src/invoiceflow/domain/invoices/models.py`
- Create: `src/invoiceflow/domain/purchasing/models.py`
- Create: `src/invoiceflow/domain/policies/models.py`
- Test: `tests/unit/domain/test_invoice_domain.py`
- Test: `tests/unit/domain/test_matching_domain.py`

**Interfaces:**
- Produces:
  - `DocumentKind`, `DocumentStatus`, `CanonicalDocument`, `DocumentElement`, `DocumentTable`
  - `InvoiceStatus`, `InvoiceAggregate`, `InvoiceLine`, `FieldEvidence`, `TaxBreakdown`
  - `PurchaseOrder`, `POLine`, `GoodsReceipt`, `GRNLine`
  - `TolerancePolicy`, `MatchStatus`, `MatchIssue`, `IssueSeverity`

- [x] **Step 1: Write domain tests for Decimal arithmetic, invariant validation and status transitions**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement domain models in `src/invoiceflow/domain/`**
- [x] **Step 4: Run tests to verify all domain invariants pass**

---

### Task 3: Database Models, Migrations & Persistence Adapters

**Files:**
- Create: `src/invoiceflow/infrastructure/database/base.py`
- Create: `src/invoiceflow/infrastructure/database/models.py`
- Create: `src/invoiceflow/infrastructure/database/session.py`
- Create: `src/invoiceflow/infrastructure/database/repositories.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/001_initial_schema.py`
- Test: `tests/integration/test_database.py`

**Interfaces:**
- Consumes: Domain models từ `src/invoiceflow/domain/`
- Produces: SQLAlchemy ORM tables, Unit of Work, `TenantRepository`, `DocumentRepository`, `InvoiceRepository`, `MatchingRepository`, `AuditRepository`, `IdempotencyRepository`, `OutboxRepository`.

- [x] **Step 1: Write integration tests for database session, repositories, tenant filtering and optimistic locking**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement ORM models, session manager, Alembic migration and repositories**
- [x] **Step 4: Run tests against SQLite / PostgreSQL to verify repository operations pass**

---

### Task 4: Storage & Secure Ingestion Preflight

**Files:**
- Create: `src/invoiceflow/infrastructure/storage/service.py`
- Create: `src/invoiceflow/application/ingestion/preflight.py`
- Create: `src/invoiceflow/application/ingestion/service.py`
- Test: `tests/unit/test_preflight.py`
- Test: `tests/unit/test_storage.py`

**Interfaces:**
- Produces: `StoragePort` (Local + S3 compatible), `IngestionPreflight` (kiểm tra MIME signature, magic bytes, max size, max pages, hash SHA-256), `IngestionService` (tạo document, outbox event và idempotency).

- [x] **Step 1: Write unit tests for MIME spoofing, oversized files, duplicate SHA-256 and storage operations**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement storage adapter and ingestion preflight validator**
- [x] **Step 4: Run tests to verify all ingestion constraints pass**

---

### Task 5: Document Processing Pipeline (XML, PDF Digital, Layout & Tables)

**Files:**
- Create: `src/invoiceflow/infrastructure/document/xml_parser.py`
- Create: `src/invoiceflow/infrastructure/document/pdf_inspector.py`
- Create: `src/invoiceflow/infrastructure/document/layout_extractor.py`
- Create: `src/invoiceflow/application/processing/document_router.py`
- Test: `tests/unit/document/test_xml_parser.py`
- Test: `tests/unit/document/test_pdf_inspector.py`
- Test: `tests/unit/document/test_document_router.py`

**Interfaces:**
- Produces:
  - `SecureXMLParser`: hardened defusedxml parser cho hóa đơn điện tử VN (TT78/NĐ123/NĐ254), cấm XXE, trích xuất header + line items + digital signature status, zero LLM.
  - `PDFInspector`: phân tích PyMuPDF (số trang, độ phủ text, digital vs scan, mã hóa).
  - `LayoutExtractor`: chuyển đổi trang PDF sang `CanonicalDocument` với element bbox và table grid.
  - `DocumentRouter`: định tuyến xử lý tối ưu (XML direct, digital PDF parse, scan/fallback).

- [x] **Step 1: Write tests with sample XML, malicious XXE XML, digital PDF and scanned PDF fixtures**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement XML secure parser, PDF inspector, layout extractor and router**
- [x] **Step 4: Run tests to verify parsing accuracy, XXE prevention and canonical document creation**

---

### Task 6: AI Extraction Adapter & Semantic Evidence Mapping

**Files:**
- Create: `src/invoiceflow/infrastructure/llm/provider.py`
- Create: `src/invoiceflow/infrastructure/llm/gemini_adapter.py`
- Create: `src/invoiceflow/prompts/invoice_extraction.py`
- Create: `src/invoiceflow/application/processing/evidence_mapper.py`
- Test: `tests/unit/llm/test_gemini_adapter.py`
- Test: `tests/unit/llm/test_evidence_mapper.py`

**Interfaces:**
- Produces:
  - `LLMProviderPort`: interface trích xuất cấu trúc với schema JSON chặt chẽ, rate-limit, budget và fallback.
  - `GeminiAdapter`: adapter gọi Google GenAI SDK với JSON schema enforcement, prompt chống injection, xử lý timeout/429.
  - `EvidenceMapper`: ánh xạ các trường trích xuất với tọa độ bbox và ID phần tử trên tài liệu gốc.

- [x] **Step 1: Write unit tests for schema validation, evidence matching, prompt formatting and mock provider response**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement LLM provider port, Gemini adapter and evidence mapper**
- [x] **Step 4: Run tests to verify extraction contracts and error mapping**

---

### Task 7: Deterministic Arithmetic Verification & 3-Way Reconciliation

**Files:**
- Create: `src/invoiceflow/application/reconciliation/validator.py`
- Create: `src/invoiceflow/application/reconciliation/matching_engine.py`
- Create: `src/invoiceflow/application/reconciliation/service.py`
- Test: `tests/unit/reconciliation/test_validator.py`
- Test: `tests/unit/reconciliation/test_matching_engine.py`

**Interfaces:**
- Produces:
  - `InvoiceValidator`: kiểm tra tính đúng đắn số học (line amounts, subtotal, VAT per rate, total payable), phát hiện duplicate document / business key.
  - `MatchingEngine`: đối soát 2-way (Invoice ↔ PO) và 3-way (Invoice ↔ PO ↔ GRN) có cấu hình tolerance, xử lý giao hàng nhiều đợt (multiple GRNs), giao một phần (partial receipt).
  - `ReconciliationService`: phối hợp validation và matching, tạo báo cáo sai lệch chi tiết (`MatchReport`).

- [x] **Step 1: Write unit tests for exact Decimal calculation, tax discrepancies, PO variance and multi-GRN matching**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement validator, matching engine and reconciliation service**
- [x] **Step 4: Run tests to verify all test cases and tolerance checks pass**

---

### Task 8: Background Workers & Asynchronous Job Pipeline

**Files:**
- Create: `src/invoiceflow/infrastructure/messaging/broker.py`
- Create: `src/invoiceflow/workers/actors.py`
- Create: `src/invoiceflow/application/processing/coordinator.py`
- Test: `tests/integration/test_worker_pipeline.py`

**Interfaces:**
- Produces:
  - Dramatiq actors / async background task handler: `process_document_job` với leasing, fencing token, compare-and-swap state transition (`RECEIVED -> QUEUED -> INSPECTING -> PARSING -> EXTRACTING -> VALIDATING -> MATCHING -> READY_FOR_REVIEW`).
  - Idempotent execution: nhận lại job cùng fingerprint trả kết quả an toàn (no-op).

- [x] **Step 1: Write integration tests for job lifecycle, lease renewal, crash recovery and retry handling**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement broker config, worker actors and job coordinator**
- [x] **Step 4: Run tests to verify end-to-end async document processing**

---

### Task 9: FastAPI Backend REST API, Auth/RBAC & Export Services

**Files:**
- Create: `src/invoiceflow/api/dependencies.py`
- Create: `src/invoiceflow/api/routers/auth.py`
- Create: `src/invoiceflow/api/routers/documents.py`
- Create: `src/invoiceflow/api/routers/jobs.py`
- Create: `src/invoiceflow/api/routers/invoices.py`
- Create: `src/invoiceflow/api/routers/matching.py`
- Create: `src/invoiceflow/api/routers/exports.py`
- Create: `src/invoiceflow/api/routers/health.py`
- Create: `src/invoiceflow/api/main.py`
- Create: `src/invoiceflow/application/review/service.py`
- Create: `src/invoiceflow/infrastructure/storage/exporter.py`
- Test: `tests/contracts/test_api_endpoints.py`
- Test: `tests/security/test_security.py`

**Interfaces:**
- Produces: Complete OpenAPI v1 API endpoints với JWT auth, RBAC, streaming upload, `If-Match` revision concurrency, review approval/rejection, CSV/JSON/XLSX export (an toàn trước formula injection).

- [x] **Step 1: Write API contract tests for all endpoints, 409 conflict, auth protection and export generation**
- [x] **Step 2: Run tests to verify failure**
- [x] **Step 3: Implement API routers, review service, export generator and FastAPI application**
- [x] **Step 4: Run API contract tests to verify all HTTP contracts pass**

---

### Task 10: Demo Data Seeding & Preflight Health Scripts

**Files:**
- Create: `scripts/seed_demo.py`
- Create: `scripts/preflight.py`
- Create: `scripts/check_environment.py`
- Test: `tests/integration/test_seed_demo.py`

**Interfaces:**
- Produces:
  - `seed_demo.py`: tạo tenants, users (admin, accountant, reviewer, viewer), vendors, sample POs, sample GRNs, synthetic invoices (XML, digital PDF, discrepancy cases) để demo 8 user journeys.
  - `preflight.py`: kiểm tra DB connection, Redis, storage, Gemini API credentials và limits.

- [x] **Step 1: Write test to verify seeding idempotency and data integrity**
- [x] **Step 2: Implement seed script and preflight diagnostics**
- [x] **Step 3: Run seeding test to confirm database populated cleanly**

---

### Task 11: Frontend Application (React 19 + TypeScript + Vite)

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/index.html`
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/app/App.tsx`
- Create: `apps/web/src/lib/api-client.ts`
- Create: `apps/web/src/features/inbox/DocumentInbox.tsx`
- Create: `apps/web/src/features/review/InvoiceReview.tsx`
- Create: `apps/web/src/features/review/BBoxViewer.tsx`
- Create: `apps/web/src/features/matching/ReconciliationPanel.tsx`
- Create: `apps/web/src/features/exports/ExportModal.tsx`
- Test: `apps/web/src/test/api-client.test.ts`

**Interfaces:**
- Consumes: FastAPI endpoints từ `/api/v1`
- Produces: Responsive accounting UI (Document Inbox, Job Status Tracker, Dual-pane Review with PDF/BBox highlight, 3-way Matching Discrepancy view, Approval/Rejection actions, Export download).

- [x] **Step 1: Scaffold Vite + React 19 + TypeScript + Tailwind project**
- [x] **Step 2: Implement typed API client and state management with TanStack Query**
- [x] **Step 3: Implement UI screens: Inbox, Review with BBox highlight, Reconciliation, Export**
- [x] **Step 4: Run frontend typecheck and build (`pnpm build`) to verify zero errors**

---

### Task 12: Benchmark Suite & Frozen Evaluation

**Files:**
- Create: `benchmarks/schemas/ground_truth.json`
- Create: `benchmarks/schemas/prediction.json`
- Create: `benchmarks/fixtures/casebook_manifest.json`
- Create: `benchmarks/fixtures/samples/` (synthetic VN AP cases)
- Create: `benchmarks/scripts/evaluator.py`
- Create: `benchmarks/scripts/run_benchmark.py`
- Test: `tests/unit/test_benchmark_evaluator.py`

**Interfaces:**
- Produces:
  - Benchmark protocol đo lường B0 (XML/rule direct), B1 (Digital PDF parser), B2 (Vision LLM), B3 (Hybrid router + deterministic validation).
  - Metrics: Field Exact Match (header, lines, tax), Precision/Recall for anomalies, False Approval Rate, Stage Latency, Cost per document.
  - Immutable manifest và kết quả tái lập được (reproducible).

- [x] **Step 1: Define GT schema and write unit test for evaluation scorer**
- [x] **Step 2: Implement synthetic benchmark dataset manifest and evaluation runner**
- [x] **Step 3: Execute benchmark runner and produce validated results artifact**

---

### Task 13: Containerization, CI/CD & Production Verification

**Files:**
- Create: `Dockerfile.api`
- Create: `Dockerfile.worker`
- Create: `.github/workflows/ci.yml`
- Create: `scripts/run_all_checks.py`
- Modify: `docs/QUALITY_BENCHMARK.md` (cập nhật kết quả benchmark thực tế)
- Modify: `docs/OPERATIONS.md` (cập nhật hướng dẫn vận hành)
- Modify: `README.md` (cập nhật demo và hướng dẫn khởi chạy)

- [x] **Step 1: Implement Dockerfiles for API and Worker**
- [x] **Step 2: Implement GitHub Actions CI pipeline**
- [x] **Step 3: Run comprehensive verification: Ruff lint, Ruff format, Mypy typecheck, Pytest suite, Frontend build**
- [x] **Step 4: Verify Docker Compose build and readiness**
- [x] **Step 5: Document verified results and portfolio evidence**
