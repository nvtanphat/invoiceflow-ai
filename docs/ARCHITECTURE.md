# Architecture — InvoiceFlow AI

## 1. Kiểu kiến trúc và nguyên tắc chọn

**Modular monolith + separate worker processes + ports/adapters.** API và worker dùng chung **một business core**, không sao chép logic. Process phân tách vì PDF/OCR tốn CPU và lời gọi LLM dài. Dùng Postgres làm nguồn sự thật; Redis là kênh thông báo việc cần chạy, **không phải authoritative state**. MinIO/S3 là lưu trữ bytes immutable.

```mermaid
flowchart TD
    U[React / PDF.js / Review UI] --> G[FastAPI + Auth/RBAC]
    G --> DB[(PostgreSQL)]
    G --> OBJ[(S3-compatible Object Store)]
    G --> Q[(Redis broker)]
    Q --> W[Dramatiq Worker]
    W --> D[Document Router]
    D --> X[Secure XML parser]
    D --> T[PyMuPDF text inspector + Docling]
    D --> O[OCR scan path]
    X --> C[Canonical Document + Evidence]
    T --> C
    O --> C
    C --> E[Structured Extractor]
    E --> L[Gemini adapter / configured provider]
    E --> V[Deterministic Validation]
    V --> M[PO/GRN Reconciliation]
    M --> DB
    G --> R[Review / Approve / Export]
    R --> DB
    W --> OBJ
```

**Không** chạy `Docling + PaddleOCR + Vision LLM` mặc định cho tất cả file. Chọn nhánh dựa trên loại tài liệu, đo evidence coverage; có fallback có điều kiện và budget.

## 2. Cây thư mục chuẩn để Coding Agent tạo (không tạo bản clone)

```text
invoiceflow/
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── .github/workflows/ci.yml
├── pyproject.toml               # lock bằng uv.lock
├── uv.lock
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.worker
├── Makefile                     # hoặc scripts/task.py trên Windows
├── docs/
│   ├── IMPLEMENTATION.md
│   ├── ARCHITECTURE.md
│   ├── QUALITY_BENCHMARK.md
│   ├── OPERATIONS.md
│   └── REFERENCES.md
├── apps/
│   └── web/
│       ├── package.json
│       ├── pnpm-lock.yaml
│       └── src/
│           ├── app/            # routes, providers, query client
│           ├── features/       # invoices, uploads, review, matching, admin
│           ├── components/     # shared UI primitives only
│           └── lib/            # typed API client and formatting
├── src/
│   └── invoiceflow/
│       ├── api/                # routers, HTTP dependencies, response mappers
│       ├── application/        # commands, queries, use cases, ports
│       │   ├── ingestion/
│       │   ├── processing/
│       │   ├── review/
│       │   └── reconciliation/
│       ├── domain/             # pure business invariants
│       │   ├── documents/
│       │   ├── invoices/
│       │   ├── purchasing/
│       │   └── policies/
│       ├── infrastructure/     # adapters, persistence and external SDKs
│       │   ├── database/
│       │   ├── storage/
│       │   ├── messaging/
│       │   ├── document/
│       │   └── llm/
│       ├── workers/            # actor entrypoints only
│       ├── prompts/            # named/versioned prompt source
│       └── config.py
├── migrations/                  # Alembic versions with generated revision IDs
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── e2e/
│   └── security/
├── benchmarks/
│   ├── configs/                 # immutable definitions in Git
│   ├── schemas/                 # GT / predictions JSON schemas
│   ├── scripts/                 # commands import same core pipeline
│   └── fixtures/                # tiny synthetic non-sensitive only
└── scripts/
    ├── seed_demo.py
    ├── preflight.py
    └── check_environment.py
```

**Chính sách chia file/folder:** route lớn → theo resource, use case lớn → một use case/file, parser → theo định dạng/chuyên môn. Không tạo `v2/fix/new`, `legacy` song song. Tên directory mới chỉ khi boundary rõ. Giữ `tests` mirrored theo module. Data gốc, labels, kết quả chạy và secrets ở external volume hoặc `.local/` gitignored, không rải trong repository.

## 3. Các boundary bắt buộc

| Port/Interface | Input | Output | Quy tắc |
|---|---|---|---|
| `ObjectStore` | byte stream, tenant, key | versioned URI + SHA256 | Immutability; signed download scope |
| `DocumentInspector` | object reference | per-page features | Không đoán theo `.pdf` extension |
| `DocumentParser` | object reference, route | canonical document | Return failure code, no silent empty success |
| `FieldExtractor` | canonical document, schema | invoice candidate + citations | Không tự ghi DB hoặc approve |
| `Validator` | candidate, policy | violations/review reasons | Pure; Decimal; deterministic |
| `Reconciler` | invoice, PO/GRN snapshots | match report | Không tự thanh toán/khấu trừ thuế |
| `ReviewService` | revision, patches, actor | approved/rejected revision | Optimistic concurrency; audit |
| `Exporter` | approved data snapshot | export artifact + manifest | Không xuất invoice chưa duyệt |

Chỉ **application service** giao tiếp với nhiều port để phối hợp; `domain` không import FastAPI, SQLAlchemy, Gemini SDK, Redis. Hạn chế model API thay đổi chỉ vào `infrastructure/llm`.

## 4. Routing XML, PDF và Document AI Core

1. **Preflight:** kiểm size, magic bytes, decode, file page count, max pixel, duplicate SHA, PDF encryption/corruption; **reject** unsupported content (không cố chuyển mọi thứ thành ảnh).
2. **XML:** secure parser, DTD/external entities/XInclude/network disabled, kiểm namespace và document type, map theo schema định dạng có tham chiếu. Lưu raw XML immutable + parsed tree/canonical data. Chữ ký số (nếu có) và trạng thái thuế là **trạng thái kiểm chứng tách biệt**: `not_checked`, `verified`, `failed`, `unknown`; `parsed_successfully` không đồng nghĩa `legally_valid`.
3. **Multi-Signal Hybrid Routing:**
   - Đánh giá đa chiều qua `PDFInspector`: phân loại trang (`native_text`, `scanned_image`, `blank`, `rotated`), mật độ text, số lượng bảng (`table_count`), phát hiện trang xoay (`has_rotated_pages`), độ khó (`is_difficult`), và ngân sách khả dụng (`budget_available`).
   - Phân luồng tất định:
     - `XML_DETERMINISTIC`: Xử lý trực tiếp file XML Thông tư 78 với độ trễ < 1ms, chi phí $0.
     - `PDF_DIGITAL`: PDF văn bản số tiêu chuẩn xử lý qua PyMuPDF và Docling layout extractor.
     - `DOCLING_OCR_STRUCTURED`: Tài liệu scan hoặc có bảng cấu trúc xử lý qua Docling kết hợp EasyOCR ("vi", "en"), chuẩn hóa thứ tự đọc không gian (spatial reading order) ở tầng adapter và `StructureAwareTableExtractor`.
     - `VISION_FALLBACK`: Chế độ dự phòng gọi Multimodal Vision LLM khi tài liệu bị biến dạng nặng hoặc có yêu cầu phức tạp ngoài khả năng parser cục bộ.
     - `MANUAL_REVIEW`: Điều hướng vào hàng đợi kiểm duyệt thủ công khi cạn ngân sách hoặc chứng từ bất thường.
4. **Structure-Aware Table Extraction & Column Semantic Mapping:**
   - **Semantic mapping:** Đối soát tiêu đề cột tiếng Việt chuẩn hóa (STT, Mã hàng SKU, Tên hàng hóa dịch vụ, Đơn vị tính, Số lượng, Đơn giá, Tiền chiết khấu, Thuế suất, Thành tiền). Chuẩn hóa tiền xử lý ký tự `Đ/đ` trước khi strip dấu Unicode NFKD để tránh nhầm lẫn.
   - **Continuation rows:** Tự động phát hiện các dòng bảng phụ chỉ chứa thông tin mô tả chi tiết hoặc bảo hành, gộp vào dòng cha liền trước thay vì tạo dòng rác.
   - **Tính nhất quán số học nội tại:** Kiểm tra điều kiện `Qty * UnitPrice == LineAmount` cho từng dòng hàng; nếu không khớp, đánh cờ nghi vấn thay vì tự ý điều chỉnh số liệu tài chính.
   - **Bảo toàn nguồn gốc tế bào (Cell-level Provenance):** Mọi dòng hàng trích xuất đều lưu giữ liên kết 1-1 tới danh sách cell nguồn kèm `BoundingBox` tọa độ trang gốc.
5. **Header totals & evidence grounding:**
   - Tổng tiền đọc theo từ vựng nhãn không dấu (`domain/invoices/field_labels.py`, `infrastructure/document/totals_extractor.py`): chịu được nhiều tổng trên một dòng OCR, lấy lần xuất hiện cuối (khối tổng kết), số dính ký tự (`6ooo0000`) là không đọc được. Không tìm thấy → issue `<FIELD>_NOT_FOUND` và verifier gán `MISSING` (giá trị 0 mặc định không bao giờ được coi là đã đọc).
   - `EvidenceMapper` định vị **mọi** trường header trong CDR theo giá trị (tiền theo Decimal qua định dạng VN/US, ngày qua nhiều định dạng in), ưu tiên phần tử mang nhãn của trường. Không định vị được → evidence `UNCERTAIN`, không bbox, `review_reason=no_direct_text_match`; không bao giờ trình bày như nguồn đã định vị.
   - Giá trị Vision luôn có evidence `vision_llm` (`model_proposed`), không ghi confidence tự báo của LLM.
   - Route ảnh: OCR chạy trên ảnh đã xử lý; bbox evidence được map ngược qua tỷ lệ trang PDF → deskew → perspective về **pixel ảnh gốc** (`coordinate_system=pixels`, kích thước ảnh gốc) vì viewer hiển thị ảnh gốc đã lưu.
   - **Bounded recovery trước Vision** (`application/processing/line_evidence_recovery.py`): (1) số lượng bị TableFormer gộp vào cuối ô mô tả chỉ được tách khi con số in trong ô và `qty × đơn giá − chiết khấu = thành tiền` (table extractor vẫn không tự đoán); (2) dòng hàng bố cục text được định vị trong khối của chính dòng đó (từ phần tử chứa SKU/mô tả đến dòng kế tiếp hoặc khối tổng kết, tối đa 4 phần tử) theo nhãn `field_labels.LINE_LABELS`; (3) thành tiền **không in** trên dòng chỉ được suy ra (`arithmetic_derivation`) khi qty và đơn giá đã định vị và tổng dòng khớp tiền hàng in trên chứng từ — gate chỉ chấp nhận nguồn này cho `line_amount`. Vision gọi tối đa 1 lần/tài liệu theo ngân sách; không dùng LLM để xác minh LLM.
   - Khác biệt định dạng (MST có khoảng trắng, ngày `dd/mm/yyyy`, `ngày … tháng … năm …`) được chuẩn hóa trước khi so OCR với Vision; ngày Vision không parse được không được điền (issue `VISION_ISSUE_DATE_UNPARSEABLE`).
   - **Review theo trường:** `evidence_gate.review_items` liệt kê đúng các trường chặn STP; reviewer giải quyết từng trường (`accept_extracted` / `accept_candidate` / `correct`) qua CAS revision + audit. Candidate bị bác ghi `human_rejected`, được chọn ghi `human_approved`; không còn thao tác "giải quyết tất cả xung đột" hàng loạt.
6. **Context-Aware Numeric Parsing & Ambiguity Disambiguation:** (`domain/documents/value_parsing.py`, một implementation dùng chung)
   - Phân giải dấu chấm phân cách hàng nghìn (`12.000.000`) và dấu phẩy thập phân theo thói quen kế toán Việt Nam.
   - Khi gặp giá trị gây mơ hồ ngữ cảnh (như `5,500` không có ngữ cảnh đơn giá/thành tiền rõ ràng), gán mã cảnh báo `AMBIGUOUS_NUMBER` để đưa vào luồng kiểm duyệt nhân sự, tuyệt đối không tự bịa giá trị.
7. **Mixed PDF & Orientation Handling:** per-page route và hợp nhất thứ tự/trang đúng; tự động nhận diện góc xoay 90/180/270 độ và xử lý OCR thích ứng. `page_index` 0-based trong API, frontend hiển thị 1-based.
8. **XML + PDF paired:** liên kết bằng business key có kiểm chứng và checksum; so field tương ứng, mismatch thành review issue. Không ghi đè XML bằng OCR không căn cứ.

### Canonical Document Representation (CDR)

Một `Document` chứa `document_id`, `tenant_id`, `kind`, `original_ref`, `checksum`, `pages`, `elements`, `tables`, `metadata`, `parser_runs`. Một element chứa `element_id`, `page_index`, `kind`, `text`, `bbox` (kèm `page_width`, `page_height`, `rotation`), `reading_order`, `confidence`. Table lưu danh sách `cells` gồm `row_index`, `col_index`, `row_span`, `col_span`, `text`, `bbox`. Bounding box luôn kèm `coordinate_system` và page dimensions; thiếu bbox ghi `null` và nguyên nhân, không bịa tọa độ.

```json
{
  "document_id": "<uuid>",
  "source_format": "pdf",
  "checksum": "sha256:...",
  "parser": {"name": "docling", "model_version": "rapidocr-v4", "config_hash": "<sha256>"},
  "elements": [{"id": "el-1", "page_index": 0, "kind": "text", "text": "Tổng cộng tiền thanh toán", "bbox": {"left": 30.0, "top": 520.0, "right": 250.0, "bottom": 540.0, "page_width": 595.0, "page_height": 842.0, "rotation": 0}}],
  "tables": [{"id": "tab-1", "page_index": 0, "row_count": 5, "column_count": 6, "cells": []}]
}
```

CDR là intermediate artifact cần versioned schema, gắn checksum source và parser config. Không thiết kế CDR phụ thuộc JSON nội bộ của Docling hoặc nhà cung cấp LLM: viết adapter chuyển đổi.

## 5. Schema nghiệp vụ chuẩn

### Invoice aggregate

- Identity: `invoice_id`, `tenant_id`, `document_id`, `revision`, `source_type`, `status`, `created_by`, timestamps.
- Header: `supplier_tax_id`, `buyer_tax_id`, `invoice_number`, `invoice_series`, `issue_date`, `currency`, `exchange_rate` (*chỉ khi có nguồn xác thực*), `invoice_kind`.
- Amounts: `subtotal`, `discount_total`, `tax_breakdown[]`, `tax_total`, `amount_payable`, `rounding_adjustment`; `Decimal`/DB `NUMERIC(20,4)` theo currency semantics, **không định sẵn VAT rate**.
- Lines: `line_no`, `sku_ref?`, `description`, `unit`, `qty`, `unit_price`, `discount`, `tax_rate?`, `tax`, `line_amount`, `purchase_order_line_id?`.
- Evidence: per-field `raw_value`, `normalized_value`, `source_kind`, `page_index`, `bbox`, `table_id?`, `cell_id?`, `element_ids`, `raw_xpath?`, `extractor`, `review_reason`, `verified_by`. Line-item fields trích bằng `StructureAwareTableExtractor` luôn gắn `table_id`/`cell_id` trỏ về đúng ô nguồn trong `DocumentTable`/`DocumentCell`, cho phép PDF Viewer highlight chính xác đến từng ô bảng.
- Legal/verification metadata tách: `signature_verification_status`, `tax_authority_check_status`, `document_validity_status`; trạng thái độc lập.

### Cơ sở dữ liệu tối thiểu

| Table | Key/ràng buộc bắt buộc |
|---|---|
| `tenants`, `users`, `memberships` | PK; (tenant,user) unique; RBAC |
| `documents`, `document_sources` | raw checksum, object ref, tenant scoping, MIME, immutable source |
| `processing_jobs`, `processing_attempts` | job status, source/config fingerprint, bounded attempts, timestamps |
| `invoices`, `invoice_revisions` | status; unique tenant + supplier tax ID + invoice series/number theo policy; revision chain |
| `invoice_lines`, `field_evidence` | invoice revision FK; amounts Decimal; source element pointer |
| `vendors`, `purchase_orders`, `purchase_order_lines` | vendor tax ID; expected price/qty |
| `goods_receipts`, `goods_receipt_lines` | received qty with PO line linkage; multiple receipts |
| `match_results`, `match_issues`, `review_decisions` | reason codes, policy version, approval actor, source revision |
| `outbox_events`, `idempotency_keys`, `audit_logs` | reliable delivery; unique `(tenant, operation, key)`; append-only audit |
| `exports`, `provider_calls` | immutable snapshot/output checksum; token/cost/runtime metrics, no prompt PII |

Use `NUMERIC` and Python `Decimal`; ISO 4217 currency; date local accounting logic documented; timestamps UTC. Unknown and not-applicable values distinct. Multi-tenant: composite FK or explicit tenant assertions **in every query**, not chỉ filter ở frontend.

## 6. State machine và reliability

```text
RECEIVED -> QUEUED -> INSPECTING -> PARSING -> EXTRACTING -> VALIDATING
            |           |            |           |             |
            +-----------+------------+-----------+-------------+--> RETRY_WAIT
                                                                  |
VALIDATING -> MATCHING -> READY_FOR_REVIEW -> APPROVED -> EXPORTED
                 |               |               |
                 +--> REJECTED   +--> REJECTED   +--> CANCELLED

Any non-terminal stage -> FAILED_PERMANENT / NEEDS_INPUT / WAITING_PROVIDER
```

- Đặt tên trạng thái chuẩn duy nhất trong enum và DB; trạng thái công việc riêng trạng thái hóa đơn. Tránh `PROCESSING` kéo dài không rõ stage.
- HTTP upload: begin DB transaction → lưu metadata `RECEIVED`, outbox event → commit → dispatcher gửi queue. Không publish Redis trước commit rồi để worker đọc bản ghi chưa commit.
- Actor nhận `job_id`, kiểm DB và lease/fencing token; compare-and-swap status/revision. Trước khi chạy gọi LLM tạo `attempt_id`, `request_fingerprint`; hoàn thành ghi CDR/candidate/validation cùng fingerprint. Delivery trùng **đọc lại kết quả và trả no-op**.
- Queue là **at-least-once**, không tự claim exactly-once; operations thay đổi tài nguyên được idempotent bằng unique key, transactions/outbox/verification.
- Retry chỉ lỗi tạm thời (`429`, `5xx`, network reset, object store transient), exponential backoff + jitter và giới hạn; invalid schema/file/policy → permanent/review. Không retry vô tận; không timeout rồi gửi lại provider không giới hạn cost.
- `WAITING_PROVIDER` không phải `COMPLETED` giả. Reconcile stuck jobs khi restart; message trùng phải an toàn.
- Review: `If-Match` hoặc `expected_revision`; đã đổi bản ghi thì HTTP `409 CONFLICT`, yêu cầu tải lại; audit actor/time/old/new/reason và mối liên hệ với source.
- **Ba quyết định tách biệt** (`application/reconciliation/stp_evaluator.py`, evidence rules ở `domain/invoices/evidence_gate.py`): `EXTRACTION_VERIFIED` (mọi trường trọng yếu có evidence nguồn tất định hoặc `human_approved`; không MISSING/UNCERTAIN/INVALID/CONFLICT/MODEL_PROPOSED; giá trị Vision không được tự xác minh bằng số học) → `MATCHING_CLEARED` (match report đã clear; thiếu PO chỉ được chấp nhận khi `po_required=false` và không còn issue khác) → `ACCOUNTING_APPROVED` (chỉ khi policy `auto_approval_enabled=true` và dưới `auto_approve_threshold`). Hệ thống chỉ ghi `APPROVED` khi cả ba qua; audit `AUTO_APPROVED_STP`/`ROUTED_TO_HUMAN_REVIEW` lưu `gates` + lý do. Ba gate hiện là kết quả quyết định trong audit, chưa phải trạng thái DB riêng.
- Duyệt thủ công: chỉ từ `READY_FOR_REVIEW`; kiểm tra SoD trước, rồi số học dòng, evidence trọng yếu (MISSING/INVALID/CONFLICT phải được **sửa**, sửa trường nào thì evidence trường đó thành `human_approved`), rồi match result mới nhất (bắt buộc tồn tại).
- Worker claim job bằng CAS (`QUEUED`/`RETRYING`, hoặc job đang chạy quá `JOB_LEASE_SECONDS` không đổi trạng thái); message trùng khi job còn trong lease là no-op; hóa đơn của tài liệu đã tồn tại → hoàn tất job, không chạy lại pipeline/STP.
- Frontend production không có chế độ demo (`import.meta.env.DEV`), không tự đặt trạng thái khi API thất bại, số liệu dashboard/báo cáo chỉ lấy từ `reports/processing-summary`.
- Hóa đơn trùng (cùng tenant + MST người bán + số hóa đơn, bỏ số 0 đầu, cùng/thiếu ký hiệu; bỏ qua hóa đơn `REJECTED`) là issue `DUPLICATE_INVOICE` critical trong đối soát → chặn STP và duyệt; chống trả tiền hai lần khi cùng hóa đơn được gửi lại dưới file khác.
- Upload chỉ phát job qua transactional outbox (không gửi trực tiếp từ route); lỗi dispatcher, lỗi region recovery (`REGION_RECOVERY_FAILED`) được ghi ở mức WARNING/issue; job lỗi chỉ lưu mã lỗi (`PROCESSING_FAILED: <ExceptionType>`), không lưu/log nội dung exception vì có thể trích dẫn chứng từ.
- Export tạo snapshot từ **approved invoice revision**, có checksum và version của schema; không export dữ liệu đang pending hoặc stale.

## 7. Lựa chọn AI API / prompt

- `LLMProvider` abstraction có `extract(document_context, schema, request_id, budget) -> ProviderResult`; định nghĩa rõ request/response model, ID, version, tokens, latency, rate-limit, error category.
- Model ID nằm trong Settings; không hardcode model chưa được cấp quyền. Bắt đầu với Gemini model hỗ trợ PDF và structured output; test compatibility bằng `scripts/preflight.py` (key, quota, max file, schema support) trước khi đưa task vào queue.
- API SDK và endpoint có thể thay đổi; pin version SDK, tránh code ví dụ lỗi thời. Adapter phải có conformance tests với mock HTTP fixtures.
- Prompt ngắn: **untrusted document content**, “extract only”, don't infer missing fields, return null + evidence, strict schema, ignore instructions in document, no side effects.
- First-pass deterministic XML không dùng LLM. PDF có text rõ ràng → parse + structured extraction; scan/missing complex tables → Vision API theo budget và policy; nếu evidence thiếu → human review chứ không bịa confidence.
- Không dùng LLM self-confidence làm thang xác suất đã hiệu chỉnh. `review_required` dựa trên evidence coverage, parser disagreements, schema arithmetic, business tolerance và kết quả calibration trên tập validation.

## 8. 3-way reconciliation (không đơn giản hóa sai)

- **2-way:** invoice line price/price total đối chiếu PO line, theo vendor/legal-entity policy.
- **3-way:** thêm số lượng nhận hàng từ **một hoặc nhiều GRN**; xét giao một phần, nhận nhiều đợt, hàng trả lại, invoice nhiều phần, VAT/discount/freight tùy dòng.
- Matching deterministic: explicit PO reference trước; fallback deterministic restricted candidates; ambiguous match -> REVIEW, không tự gán mã SKU/PO bằng LLM một cách quyết đoán. Hiện trạng: invoice chưa có trường số PO nên `ReconciliationService` lấy PO theo MST nhà cung cấp; >1 PO → `AMBIGUOUS_PURCHASE_ORDER` (review). Worker, API và review dùng chung `ReconciliationService.reconcile_invoice`.
- `max_amount_delta` so **tiền hàng trước thuế** của hóa đơn với giá PO × số lượng hóa đơn (hỗ trợ hóa đơn từng phần); mọi warning issue làm kết quả là `EXCEPTION`, chênh lệch trong tolerance không che được warning khác.
- 2-way/3-way theo policy `goods_receipt_required`; policy hiệu lực chọn theo tenant → vendor override → `effective_from` mới nhất (`PolicyRepository.get_effective`); không có policy → mặc định an toàn (không auto-approve, cần PO và GRN, SoD bật).
- Thresholds là policy per tenant/legal-entity/vendor/item, lưu version/approval; `amount_delta` và `percent_delta` tính Decimal, zero denominator xác định rõ.
- Không có PO/GRN không luôn đồng nghĩa hóa đơn sai: phân loại `NON_PO`, `PENDING_RECEIPT`, `MISSING_REFERENCE`, `UNMATCHED`, `MATCHED_WITHIN_TOLERANCE`, `EXCEPTION`.
- Không tự chuyển tiền, ghi sổ ERP/thuế. Export/webhook có approval và idempotency.

## 9. Quyết định triển khai và trade-offs

| Quyết định | Lý do | Khi nào xem xét lại |
|---|---|---|
| Modular monolith | nhỏ, dễ test/gỡ lỗi; tách process worker | team/scale chứng minh bounded contexts độc lập |
| Docling primary parser | table, reading order, bbox | failure audit cho thấy parser khác tốt hơn trên fixed set |
| XML deterministic first | chính xác, ít cost | schema mới cần adapter chính thức |
| Gemini provider via adapter | PDF multimodal + JSON | chi phí/accuracy/constraint vượt threshold |
| Redis + Dramatiq | MVP nhẹ hơn orchestration phức tạp | workflow dài có compensation/large scale -> đánh giá Temporal |
| PostgreSQL authoritative | ACID, uniqueness, audit | không thay bằng queue/LLM state |
| No LangGraph/RAG | tác vụ có state machine cố định | có bằng chứng workflow thực sự cần planning/tool autonomy |
| Auto-approval opt-in per policy (mặc định tắt) | extraction đúng ≠ match clear ≠ duyệt chi (Odoo/Dynamics tách matching và bill approval) | tenant có calibration cho thấy false auto-accept đạt ngưỡng đã duyệt |

**Tham khảo:** `docs/REFERENCES.md`; benchmark parser luôn theo `docs/QUALITY_BENCHMARK.md`. Khi thay decision, cập nhật **trực tiếp bảng này**, không tạo tài liệu `architecture_new`.

## 10. Pseudocode chuẩn hóa điểm dễ sai (cho Coding Agent)

### 10.1. Idempotent processing qua DB transaction và outbox

```python
# PSEUDOCODE — interface/transaction semantics, không phải code chạy độc lập.
async def accept_upload(tenant_id, stream, idempotency_key):
    object_ref, sha256 = await secure_store_stream(stream)  # bounded + scanned
    async with db.transaction() as tx:
        existing = await tx.find_idempotency(tenant_id, "upload", idempotency_key)
        if existing:
            return existing.response  # no new object/job side effect
        document = await tx.create_document(tenant_id, object_ref, sha256)
        job = await tx.create_job(document.id, state="RECEIVED")
        await tx.create_outbox(topic="document.received", aggregate_id=job.id)
        await tx.save_idempotency(tenant_id, "upload", idempotency_key, job)
    return job  # dispatcher publishes only committed outbox events
```

Code thực tế cần xử lý **file object được lưu trước DB commit nhưng DB fail**: object tạm có TTL/garbage collection, object version/etag ghi rõ. Tránh lỗ hổng `existing idempotency` chỉ được kiểm tra **sau** khi upload đã gây tốn storage: production nên pre-check key và thiết kế `upload_session`/multipart commit khi cần, nhưng DB uniqueness vẫn là source of truth trước race conditions.

```python
# PSEUDOCODE
async def process(job_id, delivery_id):
    async with db.transaction() as tx:
        job = await tx.lock_job(job_id)
        if job.is_terminal or job.result_exists_for_fingerprint():
            return  # redelivered message: no-op
        token = await tx.try_acquire_lease(job_id, ttl=config.lease_ttl)
        if token is None:
            return  # already running elsewhere

    candidate = await parse_extract_validate(job, budget=config.provider_budget)

    async with db.transaction() as tx:
        if not await tx.has_current_fencing_token(job_id, token):
            raise StaleWorkerError()
        await tx.upsert_result_by_fingerprint(candidate)
        await tx.append_audit_event(...)
        await tx.transition_job(job_id, expected_state="RUNNING", new_state="READY_FOR_REVIEW")
```

**Lưu ý:** `try_acquire_lease` không bảo đảm exactly-once gọi provider; khả năng request LLM bị thực hiện hai lần khi worker mất liên lạc phải được đo/giới hạn chi phí. Với side effects như export/webhook, dùng unique operation key bên nhận hoặc read-after-write verification.

### 10.2. Validation và policy không lệ thuộc model

```python
# PSEUDOCODE
amount = Decimal(raw_field)
policy = policy_repository.get_effective(
    tenant_id=tenant_id, legal_entity_id=legal_entity_id,
    vendor_id=vendor_id, effective_at=invoice.issue_date
)
issues = validate_invoice(candidate, policy)  # pure function
match = reconcile(invoice=candidate, po=po_snapshot, receipts=grn_snapshots, policy=policy)
decision = stp.evaluate(candidate, match, policy)  # extraction / matching / accounting gates
next_status = "APPROVED" if decision.accounting_approved else "READY_FOR_REVIEW"
# accounting_approved requires policy.auto_approval_enabled; never implied by the other gates
```

### 10.3. Secure XML parser contract

- Dùng parser hardened (`defusedxml` cho nhiều trường hợp; `lxml` với `resolve_entities=False`, `no_network=True`, không load external DTD). Reject DOCTYPE/XInclude và các XML size/depth quá giới hạn từ trước.
- XSD local được kiểm chứng nguồn và version; không `fetch` URL schema từ XML người dùng. Chữ ký XML phải được verify từ **raw canonical signature bytes** bằng thư viện chuyên dụng khi P1; không thể lấy content đã normalize rồi suy ra signature đúng.
- Kiểm unit tests XXE payload cả external entity file/network, recursive entity expansion, unexpected namespace, duplicate tags, alternate prefixes.

### 10.4. Retry classifier

```text
RETRYABLE: provider 429 with Retry-After, provider 5xx, transient object-store/DB/network
REVIEW: missing source field, ambiguous table, unresolved PO, conflicting XML/PDF
PERMANENT: unsupported input, malicious XML, invalid content, authorization denied
OPERATOR: provider auth revoked, model unavailable, storage exhaustion, policy misconfig
```

Mọi case có reason code có cấu trúc; không dùng `except Exception: return {}` hoặc `continue` che lỗi. Nếu vẫn phải catch broad exception tại job boundary, ghi sanitized diagnostic, để job chuyển trạng thái lỗi hợp lệ và báo alert.
