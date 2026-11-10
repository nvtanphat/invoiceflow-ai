# Implementation — Kế hoạch triển khai end-to-end

> Tài liệu giao việc có thể thực thi. **Không** giả định repository ứng dụng đã có các module bên dưới: lệnh và endpoint là **đặc tả cần xây dựng**, chỉ được ghi “đã chạy” khi có bằng chứng. Mỗi sprint có tiêu chí nghiệm thu (DoD) riêng. Không tự mở rộng thành nền tảng kế toán/ERP đầy đủ.

## 0. Chốt sản phẩm và người dùng

- **Tên:** InvoiceFlow AI — Accounts Payable Document Processing & Reconciliation.
- **Người dùng:** Kế toán công nợ (AP), nhân viên mua hàng, người duyệt, quản trị.
- **Nguồn vào:** XML hóa đơn điện tử Việt Nam, PDF có text, PDF scan/ảnh, PO/GRN CSV hoặc quản lý trong app.
- **Đầu ra:** record chuẩn + line items + evidence, cảnh báo, match result, review decision, export JSON/CSV/XLSX và audit trail.
- **In scope P0:** ingest an toàn, hàng đợi, XML parse, Docling/PDF, Gemini extraction có budget, validation, đối soát 2/3-way với PO/GRN demo, manual review, export, monitoring, benchmark.
- **P1:** incoming email connector, digital signature verification đúng chuẩn, tax authority integration có quyền truy cập chính thức, advanced vendor matching, batch-scale, model routing optimization, load tests.
- **Không thuộc P0:** auto pay/auto posting, khai thuế, nhận diện pháp lý tự động, gọi API thuế không có credentials, fine-tuning, chatbot, vector search.

### User journeys bắt buộc

1. **XML chuẩn:** upload XML → parse và validate schema → tạo invoice → duplicate/supplier check → PO/GRN match → review → export; **LLM calls = 0** nếu không cần inference.
2. **Digital PDF:** upload → detect text → Docling layout/table → structured field candidate → deterministic validation → người duyệt xác nhận → export.
3. **Scan khó:** upload → OCR/Vision fallback có giới hạn → thiếu evidence/không chắc → review, không auto-approve.
4. **Giá lệch PO hoặc thiếu GRN:** hiển thị line discrepancy, nguồn số liệu và tolerance; không tự sửa chứng từ hay bỏ qua.
5. **Trùng hóa đơn:** hash duplicate hoặc business key duplicate → cảnh báo/phản hồi rõ, không ghi hai dòng thanh toán.
6. **Worker lỗi/429:** job nằm trạng thái có thể hồi phục, retry có giới hạn, không duplicate output, không phát sinh ngân sách vô hạn.
7. **Cập nhật đồng thời:** reviewer A chỉnh xong, reviewer B submit revision cũ → `409`; không ghi đè im lặng.
8. **Tenant khác:** không thể tải file, xem invoice hoặc export của tenant khác ngay cả khi đoán được UUID.

## 1. Mô hình dữ liệu và business contract — hoàn thiện trước code

**Quy định khóa:** đặt UTC timestamps, UUID, `tenant_id`, `created_by`, `updated_at`, optimistic `revision`, audit event. Không lưu tiền bằng float. Không mặc định `supplier_tax_id` hoặc VAT luôn hiện diện; tên trường nào optional/required phải theo loại chứng từ và policy.

### Bảng và thứ tự migration

| Migration tranche | Bảng | Quy tắc dữ liệu |
|---|---|---|
| A | `tenants`, `users`, `memberships`, `vendors` | role/scope/tenant unique |
| B | `documents`, `document_sources`, `processing_jobs`, `processing_attempts`, `outbox_events` | file immutable, SHA, job state |
| C | `invoices`, `invoice_revisions`, `invoice_lines`, `field_evidence` | original vs edited, Decimal, provenance |
| D | `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `goods_receipt_lines` | quantity/price + links |
| E | `match_results`, `match_issues`, `review_decisions`, `audit_logs`, `idempotency_keys`, `exports`, `provider_calls` | policy version, approvals, costs |

**Indexes:** `processing_jobs(tenant_id,status,created_at)`, `invoices(tenant_id,supplier_tax_id,invoice_series,invoice_number)` where fields available and business policy applies; `document_sources(tenant_id,sha256)`, `match_issues(tenant_id,status)`, `audit_logs(tenant_id,aggregate_id,created_at)`; unique idempotency `(tenant_id,operation,key)`. Tenant references guarded in DB + service layer. Constraints designed so approved invoice cannot silently replace source revision.

### Entity schema và API field convention

```json
{
  "invoice_id": "<uuid>",
  "document_id": "<uuid>",
  "revision": 1,
  "status": "READY_FOR_REVIEW",
  "supplier": {"name": "Công ty mẫu", "tax_id": "<synthetic-id>"},
  "invoice_number": "INV-0001",
  "issue_date": "2026-11-08",
  "currency": "VND",
  "subtotal": "1000000.00",
  "tax_total": "100000.00",
  "amount_payable": "1100000.00",
  "line_items": [{"description": "Hàng mẫu", "qty": "2", "unit_price": "500000.00", "line_amount": "1000000.00"}],
  "evidence": [{"field_path": "amount_payable", "source_kind": "pdf", "page_index": 0, "bbox": [100,200,210,230], "raw_value": "1.100.000", "normalized_value": "1100000.00"}],
  "issues": [{"code": "REVIEW_REQUIRED", "severity": "warning"}]
}
```

Decimal đi qua HTTP là **string** để tránh JavaScript float rounding; date ISO; enum statuses documented. `bbox` kèm coordinate system + page dimensions trong schema đầy đủ. Pydantic `extra=forbid` ở payload quan trọng, create/update schema khác response schema, errors format thống nhất.

## 2. API contract — thiết kế OpenAPI trước frontend

| Method | Path | Công dụng | Error đáng kiểm thử |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | demo auth/scope | 401, 429 |
| `POST` | `/api/v1/documents` | upload streaming, idempotency | 400/413/415/422/409/429 |
| `GET` | `/api/v1/documents/{id}` | metadata và quyền | 403/404 |
| `GET` | `/api/v1/documents/{id}/preview` | signed proxy/URL ngắn hạn | 401/403/404 |
| `POST` | `/api/v1/documents/{id}/process` | tạo job nếu chưa có | 409/422/503 |
| `GET` | `/api/v1/jobs/{id}` | status, stage, attempts, progress | 403/404 |
| `GET` | `/api/v1/invoices` | filter, pagination, sort | 400/403 |
| `GET` | `/api/v1/invoices/{id}` | header + lines + evidence + `review_items` (chỉ các trường cần người quyết định, kèm lý do, nguồn, giá trị candidate Vision) | 403/404 |
| `POST` | `/api/v1/invoices/{id}/review` | `action`: `approve` / `reject` / `correct` / `resolve_field` (`field_path`, `decision` = `accept_extracted` / `accept_candidate` / `correct`, `value`); bắt buộc `If-Match`; chỉ khi `READY_FOR_REVIEW` | 400/403/409/428 |
| `PATCH` | `/api/v1/invoices/{id}/revisions` | reviewer sửa có `If-Match` | 409/422 |
| `POST` | `/api/v1/invoices/{id}/validate` | validation trên snapshot | 409/422 |
| `POST` | `/api/v1/invoices/{id}/match` | đối soát PO/GRN | 409/422 |
| `POST` | `/api/v1/invoices/{id}/approve` | phê duyệt revision cụ thể | 401/403/409/422 |
| `POST` | `/api/v1/invoices/{id}/reject` | từ chối, lý do | 401/403/409 |
| `GET` | `/api/v1/invoices/{id}/issues` | issue list + evidence | 403/404 |
| `POST` | `/api/v1/purchase-orders/import` | seed/import PO | 400/409/422 |
| `POST` | `/api/v1/goods-receipts/import` | seed/import GRN | 400/409/422 |
| `POST` | `/api/v1/exports` | chỉ hóa đơn `APPROVED`, sắp xếp `issue_date, invoice_number, id`, header `X-Export-SHA256`; không có tùy chọn xuất hóa đơn chờ duyệt | 403/422 |
| `GET` | `/api/v1/exports/{id}` | metadata + download link | 403/404 |
| `GET` | `/api/v1/audit-events` | audit filtered by auth scope | 403 |
| `GET` | `/api/v1/reports/processing-summary?days=1..90` | số liệu theo ngày UTC từ audit (nhận, auto-approve, chuyển review, duyệt, từ chối) + kỳ trước; tỷ lệ `null` khi chưa có quyết định — nguồn duy nhất cho Dashboard/Reports | 401/422 |
| `GET` | `/api/v1/documents/{id}/pages/{n}/render?dpi=36..300` | ảnh trang **đã chuẩn hóa góc xoay** đúng như trang OCR đã xử lý; `X-Page-Rotation` luôn `0` | 400/404/422 |
| `GET` | `/health/live`, `/health/ready` | liveness/readiness | 503 cho dependency fail |

**Response mẫu sau upload — async, không đợi OCR trong HTTP:**

```json
{
  "document_id": "<uuid>",
  "job_id": "<uuid>",
  "status": "QUEUED",
  "sha256": "<64-hex>",
  "status_url": "/api/v1/jobs/<uuid>"
}
```

HTTP `202 Accepted` với `Location`; `Idempotency-Key` trên POST có thay đổi state; problem-details (`type`, `title`, `status`, `code`, `detail`, `request_id`, `retryable`, `field_errors`), sanitize detail không lộ stack trace. Đặc tả OpenAPI phải có examples, auth scheme, pagination và deterministic sort. Phân biệt `409 duplicate` với `409 stale revision` bằng error code.

## 3. UI/UX — sản phẩm công khai được

| Màn hình | Thành phần chính | DoD |
|---|---|---|
| Sign in / demo workspace | user/role, tenant | không truy cập thẳng API trái quyền |
| Document inbox | drag-drop, file type, batch, stage | upload error/retry rõ; no fake progress |
| Processing jobs | stage, attempt, retry state, duration | trạng thái theo DB, refresh/SSE có backoff |
| Invoice review | PDF.js viewer trái; fields phải; click highlight bbox | sửa `If-Match`, support keyboard/tab |
| Exception queue | duplicate, mismatch, missing fields, unsupported PDF | severity/reason, filter, assign |
| PO/GRN matching | invoice lines vs PO/receipts, variances | định nghĩa tolerance hiển thị, nhiều GRN |
| Approvals | accept/reject, actor, version, comments | audit và authorization |
| Exports | CSV/JSON/XLSX generated from approved snapshot | consistent decimals and BOM/encoding |
| Observability | job metrics, provider errors, costs | không lộ raw PII |

Responsive desktop-first; loading/empty/error states rõ; mọi hành động thay đổi data có confirm; test pagination/search/sort toàn luồng. Không cần dashboard 15 biểu đồ vô nghĩa.

## 4. Kế hoạch Sprint và task card chi tiết

### Sprint 0 — Audit, nguồn tham khảo, freeze contract (2–3 ngày)

**Công việc:** kiểm repo tham khảo và giấy phép; liệt kê module dùng để học vs thực sự reuse; đóng băng flow P0, user stories và acceptance; thiết kế ERD, states, PO/GRN fixture; quyết định provider config (không tự chốt model ID không xác thực); thiết lập project skeleton theo `ARCHITECTURE.md`.

**Deliverables:** task list có dependency, `AGENTS.md`, OpenAPI draft, entity relationship, threat model, `README` sơ bộ; Docker resource budget.

**DoD:** không có thư mục/filename phiên bản/fix; mọi entity và endpoint có contract; các giả định nghiệp vụ được gắn `OPEN/ASSUMED/VERIFIED`.

### Sprint 1 — Foundation, Auth và database (tuần 1)

- Tạo Python package (`src` layout), FastAPI dependency-injection boundary, Settings, structured logging, exception mapping, versioned OpenAPI, migrations, Postgres connection health.
- RBAC: `admin`, `accountant`, `reviewer`, `viewer`; JWT/OIDC ở prod (cho MVP có seeded demo account, không hardcode credentials vào code). Password hash/exp, rate limiting, tenant checks.
- ORM + repositories, `audit_log` append-only, outbox and idempotency key scaffolding.
- Setup React typed API client, route guard; CI lint/type/unit/frontend build; pinned dependency locks.

**DoD:** migration up/down từ DB rỗng, fake tenant cross-read bị 403, API errors chuẩn; `docker compose up` DB/Redis/object store và API health pass.

### Sprint 2 — Secure upload + object store + job dispatch (tuần 2)

- Streaming upload, allowlist XML/PDF/PNG/JPEG, magic bytes, max size/page count/pixels, storage MIME, SHA-256; quarantine invalid; unique object key; malware scan hook.
- Raw source immutable; store metadata and `outbox_event` in same DB transaction; outbox dispatcher; Redis/Dramatiq worker; lease with fencing; `GET job` persisted state.
- Dedupe raw bytes (hash) và nghiệp vụ (supplier+series+number) là **hai tín hiệu khác nhau**, không xóa file chỉ vì cùng hash giữa tenants.
- Không dùng memory map toàn bộ file upload trong endpoint; không cho parser gọi network tùy tiện.

**DoD:** file hỏng/giả MIME/size vượt giới hạn bị từ chối, queue redelivery không tạo hai job output, restart redis/worker không làm mất nhiệm vụ đã commit.

### Sprint 3 — XML + PDF inspection + deterministic baseline (tuần 3)

- XML adapter: schema whitelist, namespace, `defusedxml` hoặc lxml hardened, cấm external entities, XInclude, schema remote; xác minh cấu trúc payload hiện hành từ nguồn hợp pháp.
- `PyMuPDF` preflight theo trang; digital/scan/mixed detection, PDF encryption/rotation, page/dpi limits.
- `Docling` adapter xuất CDR elements/tables/provenance, không chỉ Markdown; `SimpleTextRulesExtractor` tối thiểu cho benchmark rule baseline, không gán làm AI.
- `document_source` và parser lineage metadata: checksum, code commit, model version, config hash, date, stage timings.

**DoD:** XML chuẩn không gọi LLM; PDF parse có bbox/trang; fixtures mixed PDF không mất reading order; parser fail phân biệt schema mismatch, encrypted, corrupt, timeout.

### Sprint 4 — AI extraction và semantic provenance (tuần 4)

- `LLMProvider` port; Gemini adapter typed; request schema JSON; SDK pinned; backoff/rate limit/circuit breaker; token/cost metrics; budget per job/tenant.
- Constrained extraction header/line items, missing field null + reason, never invent. Prompt injection defense. Sử dụng CDR text + cropped page/bbox khi phù hợp; không gửi ảnh dư thừa.
- `EvidenceMapper` nối field với element IDs/text spans; tọa độ không tìm được → `unverified` và review.
- Quy tắc router config chọn `xml_direct`, `pdf_parse`, `scan_ocr`, `vision_fallback`; fallback max attempts, budget caps.

**DoD:** LLM output invalid được bắt, không đi vào production invoice; không có key vẫn chạy XML flow và trả `WAITING_PROVIDER` với PDF cần AI; Pydantic extra fields bị reject; prompt/content không bị log.

### Sprint 5 — Arithmetic, anomalies, PO/GRN matching (tuần 5)

- Normalize date/currency/ID/name; money Decimal. Verify line arithmetic, subtotal, discounts, tax, amount payable, unbalanced totals; không tự sửa số để khớp.
- Match invoice ↔ PO theo explicit references/line mapping; nhiều GRN; partial receipts, duplicated line, zero qty/price, different currency, tax, discounts; policy tolerance versioned.
- Issue codes deterministic: `MISSING_FIELD`, `NO_EVIDENCE`, `INVALID_TOTAL`, `DUPLICATE_DOCUMENT`, `DUPLICATE_BUSINESS_KEY`, `MISSING_PO`, `QUANTITY_VARIANCE`, `PRICE_VARIANCE`, `TAX_DISCREPANCY`, `UNSUPPORTED_LAYOUT`.

**DoD:** case lệch > tolerance thành review; missing PO/GRN không tự phán hóa đơn sai; test exact money and full line matching.

### Sprint 6 — Review, approval, audit, export (tuần 6)

- Review API với `If-Match`, field-level patch, reason, note, source highlight; immutable version chain. Duyệt/từ chối có RBAC + audit + policy checks.
- Snapshot approved invoice → JSON/CSV/XLSX export jobs; content type, checksum, download auth, file sanitation; CSV injection escaping/neutralization khi mở Excel.
- UI PDF.js + field editing + issue resolution + approval; keyboard/feedback/error states.

**DoD:** concurrent reviewers 409; export không lấy pending; source XML/PDF immutable; audit ai/sửa gì/khi nào/tại sao.

### Sprint 7 — Reliability + security hardening (tuần 7)

- Process failure drills: Redis down; DB transaction rollback; provider 429/5xx; malformed JSON; cold restart; retries exhausted; missing object; upload traffic.
- Dead-letter/review queue + scheduled reconciliation; job expiry/manual replay có operator permission; no duplicate side effects; safe worker `SIGTERM`.
- AuthZ tests on documents, preview, issue, export; CORS/headers, content security policy, per-role limits; secrets/config checks.
- Observability trace IDs (HTTP → job → parser → provider), metrics + alerts; verify logs do not store PII.

**DoD:** system returns sensible non-success states under error; retry bounded; upload is not a remote code execution avenue; runbook covers all incidents.

### Sprint 8 — Frozen evaluation và performance (tuần 8–9)

- Freeze dataset manifests/splits, GT, prompt+parser+model config, scoring implementation, seeds, commit hash.
- Chạy Application QA kiểm định chất lượng: XML parser, Docling + EasyOCR, Hybrid Router + targeted Vision AI fallback + deterministic validation, cùng bộ casebook tài liệu thực tế.
- Separate official DocILE protocol if using benchmark (KILE/LIR); không suy từ DocILE score sang accuracy invoice.
- Report field exact match, line F1, full-doc accuracy, review recall/precision, PO/GRN false approval, per-stage latency, cost/document; failure categories/CI.

**DoD:** results reproducible, no numbers invented, no test split used for tuning; immutable predictions+manifest+metrics; conclusions backed by evidence, trade-offs acknowledged.

### Sprint 9 — Portfolio release (tuần 10)

- Docker pinned, sample config and data redacted, seed fictional invoices+PO/GRN, production profile, health/readiness, backup/restore + rollback documented.
- GitHub Actions: lint, typecheck, tests, security scanners, image build, migration smoke, frontend build, E2E smoke.
- README diagram, 3–5 minute demo, failure demo, screenshots with synthetic data, benchmark tables + limitations, portfolio bullet claims measured.

**DoD:** reviewer clone repository (chỉ sample data) → startup → demo 8 journeys; CI green; source licenses/attribution correct; no secrets, raw customer data or unverified legal claims.

### P1 backlog — chỉ khi P0 hoàn thành

Batch import hàng nghìn docs, streaming event ingestion từ email, signature verifier, official tax API client có quyền, S3 production, Temporal (nếu cần durable orchestration nhiều ngày), tenant policies UI, PaddleOCR adapter (nếu prove win), multi-currency accounting, ERP integration sandbox. Mỗi hạng mục cần ADR cập nhật in-place và benchmark đối chứng.

## 5. Implementation DoD theo từng nhóm test

### HTTP/upload

- 202 async; `Location`/`job_id` đúng; MIME spoof, zero-byte, password PDF, 100+ page, corrupt trailer, XML entity; concurrent upload same hash across tenants.
- Empty/oversized page images refuse safely; duplicate ID behavior documented; signed URL expire; logs no file content.

### Parser/LLM

- PDF table spanning pages; rotated scan; mixed digital+scan; multiple invoices one file → split/review, không gộp thành 1 invoice giả.
- Source evidence required per important field; compare XML vs paired PDF, disagreement triggers issue. Provider timeout stops at budget.

### Business

- Invoice # duplicate across *different supplier* must not false-positive; same supplier number but different series/issuer handling policy.
- Partial receipts, multiple GRNs, returns, discount/surcharges, tax amount zero/absent, negative credit note, currency mismatch, rounding; test Decimal exact.

### Security/roles

- Accountant cannot approve own invoice if separation-of-duties policy enabled; viewer cannot PATCH; reviewer cannot read outside tenant.
- XXE, prompt injection in PDF, spreadsheet formula injection, path traversal, SSRF through malicious XML schema/PDF links.

### Operations

- Worker redelivery, DB restart, provider 429 → retry bounded, API 503 for dependency unready, cleanup temp files, replay with same idempotency key yields same output.

## 6. Những lệnh cần có khi source đã được tạo

Windows PowerShell — lệnh hướng dẫn theo các target **phải được implement**, không phải xác nhận đã tồn tại:

```powershell
# Tại root repo
Copy-Item .env.example .env
# Điền secret ở .env, không commit
uv sync --group dev --extra documents --extra gemini
pnpm --dir apps/web install --frozen-lockfile

docker compose up -d postgres redis objectstore
uv run alembic upgrade head
uv run python -m scripts.seed_demo

# Phát triển (terminal riêng)
uv run uvicorn invoiceflow.api.main:app --reload
uv run dramatiq invoiceflow.workers.actors --processes 1 --threads 2
pnpm --dir apps/web dev

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
pnpm --dir apps/web lint
pnpm --dir apps/web exec tsc --noEmit
pnpm --dir apps/web build
```

Nếu layout `src` chưa được install editable, khởi chạy package qua `uv run` sau `uv sync`; không tạm vá `PYTHONPATH` trong production scripts. `Docker Compose` services đặt đúng theo stack thực tế, volumes không xóa trong thao tác `down`. Không gợi ý dùng `docker compose down -v` để “fix” mất dữ liệu.

### CI gates gợi ý

- `quality`: Ruff, format, mypy, pytest unit/contract/security.
- `integration`: Postgres + Redis + objectstore, migration từ DB rỗng, worker, API, mock LLM response fixtures.
- `frontend`: ESLint + TS + build + core Playwright smoke.
- `security`: dependency scan, secret scan, Docker image scan, license report.
- `release`: build image immutable digest, deploy staging, E2E, migration compatibility; production promotion yêu cầu approval.

## 7. Quy định báo cáo tiến độ

Mỗi task báo:

```text
Scope:
Files touched:
Behavior and data contracts:
Root cause (nếu là bug):
Tests executed + exact result:
Benchmark effect (nếu có):
Security / migration / rollback:
Known gaps:
```

**Tránh:** “đã hoàn thành end-to-end” khi chỉ chạy API mock; “benchmark vượt trội” không có manifest; “production ready” chưa có backup, alert, auth, recovery. PR có diff nhỏ, docs cập nhật đúng heading; đổi code cũ cần test và dọn sạch trong source.
