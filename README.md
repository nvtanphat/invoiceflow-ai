# InvoiceFlow AI — Nền tảng Tự động hóa & Đối soát Hóa đơn Tài chính AP

> **InvoiceFlow AI** là hệ thống Intelligent Document Processing (IDP) chuyên sâu cho hóa đơn tài chính doanh nghiệp Việt Nam theo chuẩn **Nghị định 123/2020/NĐ-CP** và **Thông tư 78/2021/TT-BTC**. Hệ thống tích hợp xử lý đa định dạng (XML, PDF điện tử, PDF scan, ảnh chụp thực tế), tự động đối soát 3 chiều (**3-Way Matching: Hóa đơn ↔ PO ↔ GRN**), tối đa hóa tỷ lệ xử lý tự động (**Straight-Through Processing - STP**) và bảo toàn tính toàn vẹn tài chính theo chuẩn Clean Architecture.

---

## 1. Kiến trúc Tổng thể (System Architecture)

InvoiceFlow AI được thiết kế theo mô hình **Modular Monolith + Async Worker** với kiến trúc phân tầng một chiều (`API -> Application -> Domain <- Infrastructure`), phân tách rõ ràng giữa Ingestion, Preflight, Preprocessing, Routing, Extraction, Verification, Matching và Review.

```mermaid
flowchart TD
    Client["Client / Kế toán viên (React 19 + TypeScript)"] -->|Upload XML / PDF / Image| Ingestion["Ingestion & Preflight Service"]
    
    subgraph CoreBackend["Backend Modular Monolith (FastAPI)"]
        Ingestion -->|Verify Magic Bytes, Block XXE/DTD, Reject Encrypted PDF| Storage["Local / S3 Storage"]
        Ingestion -->|Enqueue Job with Tenant Context| Queue["Redis Broker (Dramatiq)"]
        
        Queue --> Worker["Async Document Processing Worker"]
        
        subgraph Pipeline["Multi-Stage Intelligent Processing Pipeline"]
            Worker --> Preprocessor{"Image Preprocessor"}
            Preprocessor -->|Image / Phone Photo| CV["Computer Vision Preprocessing<br/>(Blur/Contrast Check, 4-Point Warp, Deskew, CLAHE)"]
            Preprocessor -->|Native PDF / XML| Router{"Document Router"}
            CV --> Router
            
            Router -->|XML TT78 / ND123| XMLParser["Hardened DefusedXML (0 Cost, ~1ms)"]
            Router -->|Digital PDF| DoclingParser["Docling Adapter & PyMuPDF (BBox & Layout Extraction)"]
            Router -->|Scanned / Complex PDF| EasyOCR["EasyOCR Pipeline + Page Rotation Normalization"]
            
            DoclingParser --> RegionRecovery{"Missing Qty / Cell Merge?"}
            EasyOCR --> RegionRecovery
            RegionRecovery -->|Local Anomalies| CropRetry["Targeted High-DPI Crop OCR<br/>(250 DPI + CLAHE + Arithmetic Validation)"]
            RegionRecovery -->|Standard| Canonical["Canonical Document (CDR)"]
            CropRetry --> Canonical
            
            Canonical --> VisionGate{"Unresolved Ambiguities?"}
            VisionGate -->|Evidence Complete| Verifier["Multi-Signal Verifier (9 Verification States)"]
            VisionGate -->|Critical Missing Fields| VisionFallback["Vision Multimodal LLM (Strict Schema Budget Gate)"]
            VisionFallback --> Verifier
            XMLParser --> Verifier
            
            Verifier --> Validator["Deterministic Accounting Validator<br/>(MST Mod-11 Checksum, VAT Statutory Rates, Duplicate Detection)"]
            Validator --> Engine["3-Way Matching Engine<br/>(Invoice Lines ↔ PO ↔ GRN with UoM Synonyms & Tolerances)"]
            Engine --> STPEval["Straight-Through Processing Evaluator"]
        end
        
        STPEval -->|Zero Critical Risk & Exact Match| AutoApprove[("Auto-Approved STP (Audit Logged)")]
        STPEval -->|Discrepancy / Candidate Conflict| HumanReview[("Routed to Human Review (Ready for Review)")]
        
        AutoApprove --> Database[("PostgreSQL / SQLite Storage")]
        HumanReview --> Database
        Database --> ReviewService["Review Service (Optimistic Locking If-Match)"]
        ReviewService --> Exporter["Export Engine (OWASP Sanitized CSV, XLSX, JSON)"]
    end
```

---

## 2. Năng lực Kỹ thuật Cốt lõi (Key Engineering Capabilities)

### 2.1. Tiếp nhận & Bảo mật Chủ động (Hardened Ingestion & Preflight)
- **Xác thực Magic Bytes:** Phát hiện và ngăn chặn giả mạo phần mở rộng tệp tin (MIME-type spoofing).
- **Chặn đứng XML XXE & DTD Injection:** Vô hiệu hóa phân giải external entities, DTD và XInclude thông qua `defusedxml` theo khuyến nghị OWASP.
- **Bảo vệ Worker:** Từ chối ngay lập tức tệp tin PDF hỏng (corrupted) hoặc có cài đặt mật khẩu mã hóa (`doc.is_encrypted`), ngăn ngừa treo/crash tác vụ nền.
- **Redaction Dữ liệu Nhạy cảm (PII Redaction):** Tự động bóc tách và che giấu Bearer tokens, API keys, mật khẩu và số thẻ ngân hàng trong toàn bộ logs hệ thống.

### 2.2. Xử lý Ảnh Chụp Thực tế bằng Computer Vision
- **Đánh giá Chất lượng Tự động:** Kiểm tra độ mờ nhòe (Laplacian variance), độ sáng trung bình và độ tương phản histogram trước khi đưa vào OCR.
- **Nắn thẳng & Khử Nghiêng (Perspective Correction & Deskew):** Nhận diện 4 góc chứng từ (`approxPolyDP`), thực hiện phép biến đổi phối cảnh 4 điểm (`warpPerspective`) và cân chỉnh góc nghiêng ($\pm 15^\circ$) bằng MinAreaRect.
- **Khử Bóng & Tăng cường Độ tương phản:** Ứng dụng thuật toán CLAHE (Contrast Limited Adaptive Histogram Equalization) trên kênh màu L của không gian Lab.
- **Bảo toàn Tọa độ Hai chiều (Bidirectional Coordinate Mapping):** Ánh xạ chuẩn xác tọa độ Bounding Box từ ảnh đã xử lý ngược về ảnh gốc để kế toán viên dễ dàng đối chiếu.

### 2.3. Bóc tách Độc lập Bố cục & Tự phục hồi OCR Cục bộ
- **Trích xuất Bảng Linh hoạt:** Tự động loại bỏ các hàng tổng kết trung gian/cuối bảng (*"Cộng tiền hàng"*, *"Tổng cộng tiền thanh toán"*, *"Tiền thuế GTGT"*); hỗ trợ gom nhóm mô tả hàng hóa nhiều dòng (multi-line continuation) kèm hợp nhất BBox động.
- **Chuẩn hóa Ngữ cảnh Tiếng Việt:** Phân tích ngày tháng tự nhiên (*"Ngày... tháng... năm..."*), phân biệt MST bên bán vs. bên mua theo vị trí xuất hiện, loại trừ nhầm lẫn số hóa đơn với ký hiệu mẫu số.
- **Tự phục hồi Vùng mờ (Targeted High-DPI Region OCR Recovery):** Khi phát hiện ô bị lỗi gộp (`CELL_MERGE_SUSPECTED`) hoặc khuyết số lượng (`QTY_ZERO_OR_MISSING`), hệ thống cắt riêng vùng ô ở độ phân giải cao (250 DPI), tăng cường cục bộ và nhận diện lại. Nếu kết quả thỏa mãn số học (`Số lượng * Đơn giá = Thành tiền`), hóa đơn được phục hồi thành công mà **không cần gọi Vision LLM đắt đỏ**.

### 2.4. Xác minh Đa Tín hiệu & Kiểm soát Tính Toàn vẹn Tài chính
- **9 Trạng thái Xác minh Trường Chuẩn hóa (`FieldVerificationState`):** `VALID`, `ZERO`, `MISSING`, `INVALID`, `UNCERTAIN`, `CONFLICT`, `ARITHMETICALLY_CONSISTENT`, `MODEL_PROPOSED`, `HUMAN_APPROVED`.
- **Kiểm tra Thuật toán Mã số Thuế (MST):** Xác thực định dạng 10 số hoặc 13 số (`^\d{10}(?:-\d{3})?$`) kèm thuật toán kiểm tra số kiểm tra Modulo-11 theo quy định của Tổng cục Thuế Việt Nam.
- **Xác thực Thuế suất Luật định:** Áp dụng danh mục thuế suất GTGT hợp lệ (0%, 5%, 8%, 10%, không chịu thuế KCT), đối chiếu chéo số tiền thuế từng dòng và bảng phân bổ thuế suất.
- **Phát hiện Trùng lặp Hóa đơn:** Rà soát tự động trong phạm vi từng tenant theo bộ 3 khóa nhận dạng: MST Nhà cung cấp + Ký hiệu Mẫu số/Hóa đơn + Số hóa đơn.
- **Độ chính xác Tài chính Tuyệt đối:** Sử dụng 100% kiểu dữ liệu `Decimal` cho toàn bộ các phép tính tiền tệ, loại bỏ hoàn toàn sai số làm tròn của số thực (`float`).

### 2.5. Tự động Hóa Quy trình (Straight-Through Processing - STP) & Human Review
- **Đánh giá Rủi ro Đa yếu tố (`STPEvaluator`):** Tự động phê duyệt các hóa đơn có tổng tiền trong hạn mức cho phép, khớp 3 chiều hoàn toàn với PO/GRN (hoặc hóa đơn XML hợp lệ), không có xung đột trường dữ liệu và số học cân bằng 100%.
- **Chặn Phê duyệt Bất hợp lệ (Separation of Duties):** Nghiêm cấm phê duyệt tự động khi tồn tại bất kỳ đề xuất xung đột nào từ Vision AI (`*.candidate_vision`) hoặc sai lệch số học dòng hàng chưa được kế toán viên xác nhận.
- **Kiểm soát Cạnh tranh Lạc quan (Optimistic Concurrency Control):** Sử dụng cơ chế Compare-And-Swap (CAS) dựa trên phiên bản (`revision`) và HTTP Header `If-Match`, ngăn chặn tình trạng ghi đè dữ liệu khi nhiều kế toán viên thao tác đồng thời.

---

## 3. Cấu trúc Thư mục Dự án (Clean Architecture)

```text
invoiceflow/
├── apps/
│   └── web/                                    # Frontend React 19 + Vite + TypeScript + Tailwind CSS
│       └── src/
│           ├── features/processing/            # BBox Overlay, ExtractionPanel, AuditSection
│           └── lib/api/                        # Typed API Client
├── src/
│   └── invoiceflow/
│       ├── api/                                # REST Routers & Request/Response Contracts
│       │   └── routers/                        # documents, invoices, health, auth
│       ├── application/                        # Use Cases, Ports & Orchestration
│       │   ├── ingestion/                      # Preflight Security & Validation
│       │   ├── processing/                     # Coordinator, Router, Service, MultiSignalVerifier
│       │   ├── reconciliation/                 # MatchingEngine, Validator, STPEvaluator
│       │   └── review/                         # ReviewService (Optimistic Locking & Conflict Resolution)
│       ├── domain/                             # Pure Invariants, Enums & Financial Aggregate Models
│       │   ├── documents/                      # Canonical Document Representation (CDR), BBox
│       │   └── invoices/                       # InvoiceAggregate, InvoiceLine, VerificationStates
│       ├── infrastructure/                     # Adapters, SDKs & Persistence
│       │   ├── database/                       # SQLAlchemy 2.0 ORM & Repositories
│       │   ├── document/                       # ImagePreprocessor, DoclingAdapter, TableExtractor, RegionRecoverer
│       │   ├── logging/                        # PIIRedactingFilter & Structured Telemetry
│       │   └── llm/                            # Vision Multimodal LLM Adapters
│       └── workers/                            # Dramatiq Async Job Actors
├── tests/
│   ├── unit/                                   # 144 Unit Tests (Domain, Processing, Reconciliation, Security)
│   ├── contracts/                              # 2 Contract Tests (API Endpoints & Auth)
│   └── integration/                            # 21 Integration Tests (Image Preprocessing, E2E Flow, OCR Quality)
└── scripts/                                    # Environment check, Seed Demo & Quality Harnesses
```

---

## 4. Kiểm định Chất lượng & Bằng chứng Thực tế (Quality Benchmark)

Được đo lường và xác thực toàn diện qua test harness và benchmark thực tế:

| Tiêu chuẩn Nghiệm thu | Kết quả Thực tế | Yêu cầu Kỹ thuật (SLA) | Trạng thái |
|---|---|---|---|
| **Độ chính xác Dòng hàng (Line Items F1)** | **100.0%** | $\ge 70.0\%$ | **PASS** (Bóc tách đầy đủ dòng hàng, đơn giá, số lượng, thành tiền) |
| **Tính hợp lệ Số học (Arithmetic Validity)** | **100.0%** | $100.0\%$ | **PASS** (Kiểm tra khớp tuyệt đối $\text{Số lượng} \times \text{Đơn giá} - \text{Chiết khấu} = \text{Thành tiền}$) |
| **Phát hiện Bất thường Đối soát (Anomaly F1)** | **100.0%** | $100.0\%$ | **PASS** (Phát hiện chính xác 100% lệch giá PO và thiếu hụt hàng GRN) |
| **Khớp Thông tin Tiêu đề (Header Exact Match)**| **94.5%+** | $\ge 70.0\%$ | **PASS** (MST, Ký hiệu, Số hóa đơn, Ngày lập, Tổng thanh toán) |
| **Nhận dạng Số tiền OCR Tiếng Việt (EasyOCR)** | **100.0%** | $100.0\%$ | **PASS** (Nhận diện chính xác 100% số tiền cả trên bản scan nghiêng/xoay) |
| **Test Suite Tự động Backend** | **167/167 Passed** | $100.0\%$ | **PASS** (144 Unit + 2 Contract + 21 Integration Tests) |
| **Kiểm tra Chuẩn Mã nguồn (Ruff Linter/Format)**| **0 Errors** | 0 Cảnh báo | **PASS** (110 files chuẩn hóa PEP 8 & Typing) |
| **Biên dịch Frontend Web (TypeScript & Vite)** | **0 Errors** | Build thành công | **PASS** (`tsc --noEmit` & `vite build` 100% thành công) |

---

## 5. Hướng dẫn Khởi chạy Nhanh (Quickstart Guide)

### Yêu cầu Tiên quyết:
- **Python:** 3.12+
- **Node.js:** 20+ & `pnpm` hoặc `npm`
- **Bộ nhớ RAM:** Tối thiểu 8 GB (khuyến nghị 16 GB cho tác vụ OCR/Docling)

### Các bước Cài đặt:

```bash
# 1. Clone repository và chuẩn bị biến môi trường
git clone https://github.com/nvtanphat/invoiceflow-ai.git
cd invoiceflow-ai
cp .env.example .env

# 2. Cài đặt dependencies Python
pip install -e .

# 3. Khởi tạo cơ sở dữ liệu và nạp dữ liệu mẫu đối soát (PO/GRN/Invoices)
python scripts/seed_demo.py

# 4. Khởi chạy Backend API Server (Terminal 1)
uvicorn invoiceflow.api.main:app --host 0.0.0.0 --port 8000 --reload

# 5. Khởi chạy Async Processing Worker (Terminal 2)
dramatiq invoiceflow.workers.actors --processes 1 --threads 2

# 6. Cài đặt và khởi chạy Frontend Web (Terminal 3)
npm --prefix apps/web install
npm --prefix apps/web run dev
```

### Điểm cuối Truy cập (Endpoints):
- **Giao diện Web Kế toán:** `http://localhost:3000`
- **Tài liệu API Tương tác (Swagger UI):** `http://localhost:8000/docs`
- **Health Check & Memory Metrics:** `http://localhost:8000/api/v1/health/metrics`

### Tài khoản Kiểm thử Demo Mặc định:
| Vai trò (Role) | Email Đăng nhập | Mật khẩu Mặc định | Quyền hạn |
|---|---|---|---|
| **Quản trị viên (Admin)** | `admin@invoiceflow.vn` | `DemoPassword@123` | Toàn quyền cấu hình tenant & tài khoản |
| **Kế toán viên (Accountant)** | `accountant@invoiceflow.vn` | `DemoPassword@123` | Tải lên chứng từ, chỉnh sửa dữ liệu bóc tách |
| **Kiểm soát viên (Reviewer)** | `reviewer@invoiceflow.vn` | `DemoPassword@123` | Rà soát bất thường, xác nhận giải quyết xung đột |
| **Giám đốc duyệt (Approver)** | `viewer@invoiceflow.vn` | `DemoPassword@123` | Phê duyệt hóa đơn thanh toán cuối cùng |

---

## 6. Bộ Lệnh Kiểm thử & Đảm bảo Chất lượng (Testing & Verification)

```bash
# Chạy toàn bộ 144 bài Unit Tests
python -m pytest tests/unit/ -v

# Chạy kiểm thử API Contracts
python -m pytest tests/contracts/ -v

# Chạy kiểm thử tích hợp luồng xử lý ảnh thực tế
python -m pytest tests/integration/test_image_invoice_processing.py -v

# Chạy kiểm thử đối soát layout hóa đơn đa dạng
python -m pytest tests/integration/test_diverse_invoice_layouts.py -v

# Chạy kiểm định chất lượng nhận dạng OCR (Benchmark)
python -m pytest tests/integration/test_ocr_quality.py -v

# Kiểm tra cú pháp và định dạng mã nguồn Python
python -m ruff check src tests
python -m ruff format --check src tests

# Kiểm tra kiểu dữ liệu và build ứng dụng Frontend Web
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

---

## 7. Tuân thủ Pháp lý & Bảo mật Doanh nghiệp

- **Nghị định 123/2020/NĐ-CP & Thông tư 78/2021/TT-BTC:** Hỗ trợ chuẩn hóa định dạng hóa đơn điện tử có mã và không có mã của cơ quan Thuế; xác thực tính hợp lệ của số hóa đơn, ký hiệu mẫu số và chữ ký điện tử.
- **Nguyên tắc Phân tách Nhiệm vụ (Separation of Duties - SoD):** Nghiêm cấm một tài khoản tự lập và tự duyệt cùng một hóa đơn thanh toán; mọi thay đổi trường dữ liệu đều được ghi nhận vào `AuditLog` bất biến (Immutable Audit Trail).
- **OWASP API & File Security:** Lọc sạch công thức CSV khi xuất file (`=`, `+`, `-`, `@`) để chống CSV Formula Injection; giới hạn tài nguyên tính toán và bộ nhớ trên mỗi worker process.
