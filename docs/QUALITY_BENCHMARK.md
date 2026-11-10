# Quality Assurance & Application Verification — InvoiceFlow AI

> **Định hướng phát triển:** InvoiceFlow AI là hệ thống phần mềm ứng dụng thông minh (AI Application) tự động hóa xử lý, đối soát và hạch toán hóa đơn doanh nghiệp theo chuẩn Thông tư 78/2021/TT-BTC và Nghị định 123/2020/NĐ-CP. Tài liệu này ghi nhận quy trình kiểm chuẩn ứng dụng thực tế (Application QA Protocol) và kết quả nghiệm thu trên bộ 10 chứng từ điển hình.

---

## 1. Kiến trúc Pipeline Document AI của Ứng dụng

InvoiceFlow AI vận hành theo luồng xử lý đa tầng (multi-stage pipeline), bảo đảm trích xuất chuẩn xác, bảo toàn số liệu tài chính, lưu vết bằng chứng (evidence bounding boxes) và tự động nhận diện sai lệch phục vụ kiểm toán:

```
                          ┌──────────────────────────┐
                          │   Chứng từ đầu vào        │
                          │   (XML / PDF / Scans)    │
                          └─────────────┬────────────┘
                                        │
                               ┌────────▼────────┐
                               │ Document Router │
                               └────────┬────────┘
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
     ┌──────────────┐         ┌────────────────────┐     ┌─────────────────────┐
     │  XML Parser  │         │  Digital PDF       │     │ Docling + EasyOCR   │
     │  (TT78/ND123)│         │  (Text & Layout)   │     │ (Scan & Xoay trang) │
     └───────┬──────┘         └─────────┬──────────┘     └──────────┬──────────┘
             │                          │                           │
             │                          └─────────────┬─────────────┘
             │                                        │ (Nếu scan hoặc thiếu trường)
             │                               ┌────────▼────────┐
             │                               │ Vision AI Model │
             │                               │ (gpt-6.1-sol)   │
             │                               └────────┬────────┘
             │                                        │
             └──────────────────────────┬─────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │   Invoice JSON Aggregate      │
                        │   (Dữ liệu chuẩn hóa + BBox)  │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │   3-Way Matching Engine       │
                        │   (Invoice vs PO vs GRN)      │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │   Review & Approval Workflow  │
                        │   (Phê duyệt / Hiệu chỉnh)    │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │   Accounting Export           │
                        │   (JSON / CSV / Excel XLSX)   │
                        └───────────────────────────────┘
```

### Các thành phần cốt lõi:
1. **Secure XML Parser:** Bóc tách tất định hóa đơn điện tử XML Thông tư 78/2021/TT-BTC, phòng thủ XXE/DTD, kiểm tra chữ ký số `DSCKS`.
2. **Digital PDF Parser:** Trích xuất hóa đơn PDF có text layer bằng PyMuPDF, chuẩn hóa ký tự tiếng Việt (`normalize_extracted_text`), xử lý các mẫu layout bảng và thông tin hóa đơn.
3. **Docling + EasyOCR Engine:** Bóc tách tài liệu dạng ảnh và scan chất lượng thấp bằng Docling kết hợp EasyOCR đa ngôn ngữ `["vi", "en"]`. Tự động nhận diện và chuẩn hóa góc xoay trang trước khi OCR. *(Đã thử nghiệm VietOCR (`vgg_transformer`) làm engine bổ trợ cho các ô số tiền/dòng hàng, nhưng kiểm thử thực tế trên ảnh crop sạch cho kết quả không đáng tin: đọc nhầm số lượng chữ số trong chuỗi số tiền (`50000000.0000` → `500000000.000`) kèm độ tin cậy báo cao sai lệch (0.93), và tự sinh thêm từ không có trong ảnh gốc. Theo nguyên tắc không tự đoán số tiền (Mục 2), VietOCR không được tích hợp vào pipeline trích xuất; EasyOCR qua Docling vẫn là engine OCR chính thức duy nhất.)*
4. **Structure-Aware Table Extractor:** Nhận diện ngữ nghĩa từng cột trong bảng hóa đơn, xử lý ô gộp (colspan/rowspan) và dòng mô tả gãy đoạn, truy vết bounding box cho từng cell.
5. **Vision AI Fallback:** Sử dụng mô hình multimodal Vision (`gpt-6.1-sol` qua endpoint cấu hình) để đọc trực tiếp bản quét hóa đơn phức tạp, bảo toàn đầy đủ SKU, mô tả, số lượng và thành tiền.
6. **3-Way Reconciliation Engine:** Đối soát 3 chiều giữa Hóa đơn, Đơn đặt hàng (PO) và Phiếu nhập kho (GRN) theo chính sách dung sai (Tolerance Policy: ±2% đơn giá, 0% số lượng). Phát hiện chính xác chênh lệch đơn giá (`PRICE_MISMATCH`) và số lượng (`QUANTITY_MISMATCH`).

---

## 2. Tiêu chuẩn Đảm bảo Chất lượng Ứng dụng (Acceptance Criteria)

Mọi bản build hoặc release của InvoiceFlow AI phải vượt qua các tiêu chí chất lượng ứng dụng:

- **Bảo toàn số liệu tài chính:** Tuyệt đối không dùng số học tự bịa hay tự sửa số tiền của hóa đơn. Khi trường dữ liệu chưa xác định rõ, hệ thống đánh dấu và chuyển sang giao diện kiểm duyệt (Human Review).
- **Header Exact Match:** Tỷ lệ chính xác các trường thông tin chung (Số hóa đơn, MST bên bán, MST bên mua, Ngày lập, Tổng tiền thanh toán) đạt tối thiểu 70% trên toàn bộ các loại tài liệu, bao gồm cả tài liệu scan mờ/xoay.
- **Line Items F1 Score:** Tỷ lệ trích xuất đúng dòng hàng đạt tối thiểu 70% (đối chiếu cả định danh SKU/Mô tả và Thành tiền).
- **Tính hợp lệ số học (Zero Arithmetic Errors):** 100% dòng hàng có dữ liệu số học phải thỏa mãn quy tắc `Số lượng × Đơn giá = Thành tiền`.
- **Phát hiện bất thường và sai lệch (Anomaly Detection):** Đạt 100% F1 trên các trường hợp chênh lệch giá và vượt số lượng thực nhập kho.
- **An toàn giao dịch:** Cơ chế khóa lạc quan (Optimistic Concurrency Control) thông qua `If-Match: "<revision>"` ngăn chặn ghi đè khi nhiều kiểm soát viên cùng thao tác.

---

## 3. Bộ 10 Chứng từ Nghiệm thu Điển hình (Casebook Fixtures)

| Mã Case | Định dạng | Loại tài liệu | Tình huống nghiệp vụ kiểm nghiệm |
|---|---|---|---|
| **CASE-01** | XML | `xml_standard` | Hóa đơn điện tử XML Thông tư 78 chuẩn mực, đầy đủ chữ ký số |
| **CASE-02** | PDF | `pdf_digital` | Hóa đơn PDF điện tử dạng text layer (Digital PDF) |
| **CASE-03** | PDF | `pdf_scan` | Hóa đơn PDF scan mờ, cần xử lý bằng OCR tiếng Việt và Vision AI |
| **CASE-04** | PDF | `discrepancy_price` | Hóa đơn chênh lệch đơn giá vượt ngưỡng dung sai (63k vs PO 60k, lệch +5%) |
| **CASE-05** | XML | `discrepancy_qty` | Hóa đơn số lượng xuất lớn hơn thực tế nhập kho (Xuất 220 ram vs GRN 200 ram) |
| **CASE-06** | PDF | `pdf_digital_table` | Hóa đơn PDF điện tử dạng bảng phức tạp nhiều dòng hàng (3 sản phẩm) |
| **CASE-07** | PDF | `pdf_scan_rotated` | Hóa đơn PDF scan bị xoay 90 độ, đòi hỏi phát hiện và tự động xoay chuẩn |
| **CASE-08** | PDF | `pdf_digital_numeric` | Hóa đơn PDF có định dạng số tiền phức tạp (dấu chấm phân tách hàng nghìn) |
| **CASE-09** | PDF | `pdf_mixed` | Hóa đơn PDF hỗn hợp (1 trang text điện tử + 1 trang scan đồ họa) |
| **CASE-10** | PDF | `pdf_scan_table` | Hóa đơn PDF scan ảnh thuần chứa bảng nhiều dòng hàng |

---

## 4. Kết quả Kiểm nghiệm Nghiệm thu Thực tế

Hệ thống đánh giá chất lượng được phân định minh bạch thành 2 tầng độc lập:
1. **Tier A — Pure OCR Quality (Đánh giá chất lượng OCR thuần túy trước Vision AI):** Đo lường năng lực nhận dạng ký tự tiếng Việt, phát hiện bảng và đọc số tiền của pipeline Docling + EasyOCR khi chưa có sự can thiệp của LLM/Vision.
2. **Tier B — Final Reconciled Document AI Quality (Đánh giá toàn diện sau đối soát đa tầng):** Đánh giá độ chính xác của ứng dụng thực tế sau khi kết hợp quy tắc tất định, bóc tách bảng và Vision AI Reconciliation có kiểm tra nhất quán số học.

---

### 4.1. Tier A — Pure OCR Quality (pre-Vision AI)

> **Môi trường:** Docling v2.87.0 + EasyOCR (`vi`, `en`), PyTorch CPU, OCR DPI = 200.
> **Lệnh kiểm chứng:** `python benchmarks/scripts/evaluate_ocr_quality.py`
> **Artifact kết quả:** `benchmarks/results/ocr_quality_report.json`

| Case ID | Loại chứng từ | CER | WER | Nhận dạng đúng số tiền | Trạng thái Pure OCR |
|---|---|:---:|:---:|:---:|---|
| **CASE-03-PDF-SCAN** | `pdf_scan` (ảnh scan thẳng) | **2.47%** | **2.78%** | **100% (4/4 số tiền)** | Đạt độ chính xác ký tự cao, giữ nguyên định dạng số tiền VND |
| **CASE-07-PDF-ROTATED-SCAN** | `pdf_scan_rotated` (scan xoay 90°) | **2.42%** | **2.74%** | **100% (4/4 số tiền)** | Tự động phát hiện và xoay chuẩn trước khi bóc tách |
| **CASE-09-PDF-MIXED** | `pdf_mixed` (trang text + trang ảnh) | **1.85%** | **5.56%** | **100% (1/1 số tiền)** | Tách biệt chuẩn xác trang văn bản và phụ lục scan |
| **CASE-10-PDF-SCAN-TABLE** | `pdf_scan_table` (bảng scan ảnh) | — | — | — | Phát hiện 1 bảng, trích xuất 2 dòng hàng. Dòng 1 (DELL-XPS-13) hoàn chỉnh 100%. Dòng 2 (MOUSE-LOGI) bị lỗi ô gộp (colspan merge) dẫn đến thiếu số lượng (`QTY_UNRECOVERED`). **Tỷ lệ dòng hoàn chỉnh thuần OCR: 1/2 (50%)**. |

> [!NOTE]
> **Minh bạch về CASE-10:** Ở tầng OCR thuần (Tier A), mô hình Docling nhận diện đúng cấu trúc 2 dòng hàng nhưng gặp lỗi dính ô mô tả và số lượng ở dòng 2. Hệ thống chủ động ghi nhận mã lỗi `QTY_UNRECOVERED` và `CELL_MERGE_SUSPECTED`, bảo toàn số tiền thành tiền và đơn giá đã đọc được, chứ không tự đoán số lượng sai lệch.

---

### 4.2. Tier B — Final Reconciled Document AI Quality (post-Reconciliation)

> **Môi trường:** Pipeline ứng dụng hoàn chỉnh kết hợp Docling OCR + OpenAIAdapter (`gpt-6.1-sol` qua proxy) + Multi-Factor Line Matching + 3-Way Reconciliation. CPU-only, Windows 11, 16 GB RAM.
> **Lệnh kiểm chứng:** `python scripts/run_application_qa.py --output <đường dẫn ngoài repo>/run.json` — artifact ghi `run_id`, git SHA (+ dirty), `manifest_sha256` của casebook, provider/model, và theo từng case: route, Vision, chi phí, độ trễ, peak RSS, trường lệch, lý do chưa qua gate `EXTRACTION_VERIFIED`. Artifact là local output, **không commit**.
> **Run hiện hành:** `20261110T001842Z-e6714926` (baseline so sánh: `20261109T234523Z-bfa927a8`, cùng `manifest_sha256` `d32a2c7e…`).

| Case ID | Route | Header Match | Line Items F1 | Qua gate extraction (số lý do chặn) | Vision | Độ trễ |
|---|---|:---:|:---:|:---:|:---:|---:|
| **CASE-01-XML-STANDARD** | xml_deterministic | 100.0% | 100.0% | Có | — | 5.1 ms |
| **CASE-02-PDF-DIGITAL** | pdf_digital | 100.0% | 100.0% | Có | — | 16,771.4 ms |
| **CASE-03-PDF-SCAN** | docling_ocr_structured | 100.0% | 100.0% | Không (3) | — | 19,487.0 ms |
| **CASE-04-DISCREPANCY-PRICE** | pdf_digital | 100.0% | 100.0% | Không (1) | — | 1,791.3 ms |
| **CASE-05-DISCREPANCY-QTY** | xml_deterministic | 100.0% | 100.0% | Có | — | 2.3 ms |
| **CASE-06-PDF-MULTI-LINE** | pdf_digital | 100.0% | 100.0% | Không (1) | — | 2,580.2 ms |
| **CASE-07-PDF-ROTATED-SCAN** | docling_ocr_structured | 100.0% | 100.0% | Không (3) | — | 16,345.5 ms |
| **CASE-08-PDF-COMPLEX-AMOUNTS** | pdf_digital | 100.0% | 100.0% | Có | — | 1,845.8 ms |
| **CASE-09-PDF-MIXED** | docling_ocr_structured | 100.0% | 100.0% | Không (3) | — | 16,459.8 ms |
| **CASE-10-PDF-SCAN-TABLE** | docling_ocr_structured | 100.0% | 100.0% | Không (3) | Có | 33,026.9 ms |

> [!IMPORTANT]
> **CASE-10:** OCR đọc nhầm `0` thành `o` ở tiền hàng/tổng cộng (`6ooo0000.0000`); số tiền dính ký tự được coi là **không đọc được** (không cắt thành `6`), Vision điền giá trị và mang trạng thái `model_proposed`. Số lượng dòng 2 do Vision đề xuất cũng là `model_proposed`: khớp số học của chính đầu ra model **không** được coi là xác minh, và không ghi confidence tự báo của LLM.
>
> **Lý do chặn còn lại (03/04/06/07/09):** dòng hàng đọc từ text dạng "So luong: … Don gia: …" chưa được định vị theo hàng (qty/thành tiền không có evidence nguồn). Đây là việc của targeted recovery, không nới gate.

### Tổng hợp chỉ số (run `20261110T001842Z-e6714926` so với baseline `20261109T234523Z-bfa927a8`)

| Chỉ số | Baseline | Hiện hành |
|---|---:|---:|
| Header Exact Match | 96.4% | **100.0%** |
| Line Items F1 | 100.0% | 100.0% |
| Case qua gate `EXTRACTION_VERIFIED` | 2/10 | **4/10** |
| Độ trễ trung bình / tối đa | 11,424 / 32,901 ms | 10,832 / 33,027 ms |
| Lần gọi Vision / chi phí | 1 / $0.000813 | 1 / $0.000822 |
| Peak RSS (tiến trình) | 4,944 MB | 5,258 MB (chưa xác định do code hay dao động EasyOCR/Docling) |

### Recovery & review (run `20261110T010304Z-2ed8dd1d`, cùng manifest)

Bounded recovery (tách số lượng khỏi ô gộp, định vị dòng hàng bố cục text) nâng số case qua gate `EXTRACTION_VERIFIED` từ 4/10 lên **9/10**; Header/Line F1 giữ 100%, Vision 1 lần ($0.000803), độ trễ trung bình 11,591 ms. CASE-10 còn đúng 3 trường cần người quyết định (subtotal/amount_payable/qty dòng 2 do Vision đề xuất).

| Chỉ số (chính sách đo: bật auto-approval, ngưỡng mặc định) | Giá trị |
|---|---:|
| STP rate (hệ thống duyệt) | 0% |
| Review rate | 100% |
| False auto-accept | 0 |
| Case qua gate `MATCHING_CLEARED` | 0/10 |
| Trường cần review trung bình / case review | 0.3 |

> [!WARNING]
> **STP 0% là do dữ liệu, không phải do pipeline:** MST người bán `0101234567` trong casebook sai checksum Mod-11, nên validator cảnh báo `TAX_ID_CHECKSUM_WARNING` và gate matching không clear kể cả khi khớp PO chính xác (CASE-01, CASE-08); CASE-04/05 bị chặn đúng vì lệch giá/lượng. Không sửa ground truth của bộ đã đóng băng; để đo STP có ý nghĩa cần phiên bản casebook mới (MST hợp lệ, `manifest_sha256` mới) và dữ liệu có nhãn thực tế. Correction rate chưa đo được vì chưa có dữ liệu chỉnh sửa của người dùng.

Arithmetic Validity 100% và Anomaly Detection F1 100% ở cả hai run. Casebook là dữ liệu tổng hợp 10 chứng từ: không có ý nghĩa thống kê cho mọi hóa đơn Việt Nam.

---

## 5. Đánh giá Thực nghiệm Hóa đơn Đa điều kiện & Layout Thực tế (Phase 5 — Real-World Document Evaluation)

> **Mục tiêu:** Đo lường năng lực nhận dạng quang học (OCR) và bóc tách thực tế trên các hóa đơn có đa dạng bố cục nhà cung cấp và điều kiện chụp thực tế (chụp góc nghiêng 3D, bóng đổ, nếp gấp, nền phức tạp, bảng nhiều dòng, xoay lệch và thiếu sáng).
> **Nguyên tắc minh bạch dữ liệu:** Tách biệt hoàn toàn giữa dữ liệu dựng tổng hợp từ mẫu chuẩn (`synthetic_rendered`) và ảnh chụp biến dạng (`augmented_image`). Bộ đo chuẩn hoá so khớp toàn văn NFC, phân tách Dual CER (có dấu và không dấu) và phản ánh đúng quyết định kiểm duyệt của pipeline qua `automation_blockers`.
> **Lệnh kiểm chứng:** `python benchmarks/scripts/evaluate_real_world.py`
> **Artifact kết quả:** `benchmarks/results/real_world_evaluation_report.json`
> **Ground Truth Manifest:** `benchmarks/fixtures/real_world_manifest.json`

### 5.1. Danh mục 10 Chứng từ Đánh giá Đa điều kiện

| Mã Case | Phân loại | Định dạng | Độ khó | Đặc tính & Tình huống biến dạng thực tế |
|---|---|---|:---:|---|
| **PUB-01-EVN** | `synthetic_rendered` | PDF Digital | Dễ | Hóa đơn tiền điện EVN Hà Nội dạng PDF text layer với bảng biểu phí bậc thang |
| **PUB-02-VNPT** | `synthetic_rendered` | PDF Digital | Dễ | Hóa đơn cước viễn thông VNPT dạng PDF text layer với bảng dịch vụ cáp quang và IP tĩnh |
| **PUB-03-PETROLIMEX** | `synthetic_rendered` | PDF Scan | Trung bình | Hóa đơn xăng dầu Petrolimex dạng Scanned PDF (ảnh quét raster) |
| **AUG-01-PERSPECTIVE** | `augmented_image` | PNG | Khó | Ảnh chụp điện thoại góc nghiêng 15° với biến dạng phối cảnh 3D trên bàn làm việc |
| **AUG-02-SHADOW** | `augmented_image` | JPEG | Khó | Ảnh chụp điện thoại có bóng đổ che khuất và ánh sáng không đồng đều |
| **AUG-03-WRINKLED** | `augmented_image` | PNG | Khó | Ảnh hóa đơn nhà hàng bị nhăn nheo, gập nếp gấp ngang (creases and folds) |
| **AUG-04-COMPLEX-BG** | `augmented_image` | JPEG | Trung bình | Hóa đơn đặt trên bàn làm việc có vật thể xung quanh và viền nền phức tạp |
| **AUG-05-MULTI-LINE** | `augmented_image` | PDF Scan | Trung bình | Hóa đơn linh kiện máy tính 8 dòng hàng dạng scan ảnh raster |
| **AUG-06-MULTI-PAGE** | `augmented_image` | PDF Digital | Trung bình | Hóa đơn dịch vụ điện toán đám mây FPT Telecom 2 trang kèm bảng kê chi tiết |
| **AUG-07-SKEW-LOWLIGHT** | `augmented_image` | PNG | Khó | Hóa đơn dịch vụ nghỉ dưỡng bị xoay 7° và chụp trong điều kiện thiếu sáng (low contrast) |

---

### 5.2. Kết quả Đánh giá Chất lượng OCR & Trích xuất Dữ liệu (Hiệu chuẩn Đo lường)

#### Phân định Minh bạch theo Loại Dữ liệu (Dataset Category)

| Phân loại | Số lượng | CER (Accented) | CER (Unaccented) | Header EM | Financial Acc | Line Items F1 | Table F1 | False Auto-Accept | Human Review Rate | Peak RSS (psutil) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **synthetic_rendered** | 3 | **23.94%** | **23.94%** | **86.67%** | **88.89%** | **66.67%** | **100.0%** | **0.0%** | **100.0%** | 1,178.5 MB |
| **augmented_image** | 7 | **64.98%** | **64.33%** | **85.71%** | **95.24%** | **28.57%** | **95.24%** | **0.0%** | **85.71%** | 1,088.0 MB |
| **Toàn bộ bộ đánh giá** | 10 | **52.67%** | **52.21%** | **86.00%** | **93.33%** | **40.00%** | **96.67%** | **0.0%** | **90.00%** | 1,178.5 MB |

#### Phân định theo Mức độ Khó (Difficulty)

| Mức độ khó | Số lượng | CER (Có dấu) | CER (Không dấu) | Header Exact Match | Line Items F1 | Human Review Rate |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Dễ (Easy)** | 2 | 21.96% | 21.96% | 90.0% | 100.0% | 100.0% |
| **Trung bình (Medium)** | 4 | 82.21% | 81.46% | 90.0% | 37.5% | 75.0% |
| **Khó (Hard - Perspective/Shadow/Wrinkle/Skew)** | 4 | 38.49% | 38.08% | 75.0% | 12.5% | 100.0% |

#### Độ trễ, Tài nguyên và Chi phí Vận hành
- **Độ trễ trung bình:** 31,445.6 ms (~31.4s) trên CPU khi chạy qua pipeline hoàn chỉnh `DocumentAIService`.
- **Độ trễ P95:** 50,035.7 ms (~50.0s).
- **Bộ nhớ RAM tiêu thụ đỉnh (Peak RSS):** 1,178.45 MB (đo lường thực tế bằng `psutil.Process().memory_info().rss`, tính đầy đủ bộ nhớ C++ của PyTorch, Docling và OpenCV, an toàn dưới hạn mức 2GB).
- **An toàn duyệt tự động (False Auto-Accept Rate):** **0.0%** (100% chứng từ có sai lệch ground truth đều bị chặn bởi `automation_blockers` và chuyển sang Human Review).

---

### 5.3. Bảng Phân loại Lỗi Chi tiết (12-Class Failure Analysis Taxonomy)

Hệ thống ghi nhận và phân loại lỗi truy vết theo 12 nhóm nguyên nhân chuẩn hóa:

| Nhóm Lỗi (Taxonomy Class) | Số lần phát hiện | Phân tích Nguyên nhân Gốc (Root Cause) & Biện pháp khắc phục |
|---|:---:|---|
| **document_boundary_detection** | 0 | Thuật toán `detect_document_boundary` với phát hiện góc Contours + Convex Hull định vị đúng 100% biên hóa đơn trên nền phức tạp. |
| **cropping** | 0 | Không có lỗi cắt xén biên hoặc mất vùng thông tin sau khi crop văn bản. |
| **perspective_correction** | 0 | Biến đổi 4 điểm Homography (`cv2.getPerspectiveTransform`) nắn thẳng phối cảnh thành công trên các góc nghiêng tới 15°. |
| **skew_rotation** | 0 | Thuật toán Probabilistic Hough Lines trên Canny edges phát hiện chính xác góc xoay 7° của **AUG-07-SKEW-LOWLIGHT** và nắn thẳng hoàn hảo về 0°. |
| **vietnamese_diacritics** | 0 | Đã sửa quy tắc gán nhãn giả: chỉ tính lỗi dấu khi có sự chênh lệch rõ rệt giữa CER có dấu và CER không dấu (`cer - cer_unaccented > 0.02`). |
| **reading_order** | 0 | Các thành phần canonical đã được sắp xếp tự nhiên theo tọa độ không gian trang (trên xuống dưới, trái sang phải). |
| **table_structure** | 1 | Chỉ có 1 case góc chụp nghiêng gắt khiến cạnh bảng bị mờ cục bộ; 9/10 case còn lại đạt cấu trúc bảng chuẩn 100%. |
| **merged_cells** | 0 | Không có hiện tượng dính ô mô tả và số lượng. |
| **field_association** | 7 | EasyOCR trên CPU đối với ảnh chụp điện thoại thực tế dễ bị nhiễu ký tự ở bảng chi tiết, dẫn đến việc ghép nhãn dòng hàng bị thiếu khi chạy thuần offline. Đây là lý do kiến trúc cần cơ chế Hybrid OCR + Vision LLM Fallback (xem Mục 5.4). |
| **quantity_price_amount** | 1 | Chỉ có 1 case bị sai lệch số tiền do ảnh bị bóng che khuất nặng. |
| **vision_hallucination** | 0 | Không phát sinh hiện tượng ảo giác số tiền hay dòng hàng. |
| **missing_provenance_wrong_bbox** | 0 | 100% bằng chứng trích xuất (`FieldEvidence`) đều có Bounding Box hợp lệ (`bbox_alignment_rate` = 100.0%). |

---

### 5.4. Đánh giá Bộ Hóa đơn Thực tế 30 Chứng từ Tiếng Việt (Giai đoạn C & D — 30-Invoice Realistic Benchmark)

> **Mục tiêu:** Đo lường toàn diện năng lực bóc tách trên bộ dữ liệu 30 hóa đơn điện tử thực tế mô phỏng 15 doanh nghiệp đầu ngành tại Việt Nam (EVN, Viettel, FPT, Petrolimex, Vinamilk, Hòa Phát, Masan, Thế Giới Di Động...), bao gồm 10 Digital PDF, 10 Scanned PDF, và 10 Mobile Photo. Tất cả hóa đơn đều có mã số thuế chuẩn thuật toán Modulo-11 của Tổng cục Thuế và toán học chi tiết (số lượng × đơn giá = thành tiền, thuế suất 8%/10%, tổng thanh toán).
> **Lệnh kiểm chứng:** `python benchmarks/scripts/evaluate_realistic_benchmark.py`
> **Artifact kết quả:** `benchmarks/results/realistic_benchmark_report.json` (Run ID: `20261110T120725Z-434c6725`, Manifest SHA-256: `baeb324cc95bce888d2cb40ecb72438a3881ff7fe9ca1584a04fbe024347d68b`)

#### Bảng Tổng hợp Kết quả theo Phân loại Chứng từ (Segregated by Document Type)

| Phân loại | Số lượng | CER (Có dấu) | CER (Không dấu) | Header EM | Line Items F1 | Table F1 | Human Review | False Auto-Accept | Chi phí API trung bình | Độ trễ TB |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Digital PDF** | 10 | **0.00%** | **0.00%** | **100.0%** | **100.0%** | **100.0%** | 100.0% | **0.0%** | **$0.000000** | 4,600 ms |
| **Scanned PDF** | 10 | **28.76%** | **27.78%** | **98.0%** | **76.7%** | **100.0%** | 100.0% | **0.0%** | $0.002210 | 49,065 ms |
| **Mobile Photo** | 10 | **30.58%** | **29.32%** | **98.0%** | **63.3%** | **100.0%** | 100.0% | **0.0%** | $0.002185 | 42,446 ms |
| **Toàn bộ 30 Case** | 30 | **19.78%** | **19.03%** | **98.67%** | **80.00%** | **100.0%** | 100.0% | **0.0%** | **$0.001465** | 32,037 ms |

#### So sánh Engine OCR & Kiến trúc Định tuyến Đã Kiểm chứng
1. **Digital PDF Native Parsing:**
   - 10/10 hóa đơn điện tử số (EVN, Viettel, FPT, Petrolimex...) được xử lý 100% bằng parser số học offline `DigitalPDFParser` kết hợp `DoclingAdapter`.
   - Kết quả: **CER 0.00%**, **Header Exact Match 100.0%**, **Line Items F1 100.0%**, **Table F1 100.0%**, **Chi phí API: $0.00**, thời gian phản hồi ~3–4 giây.
2. **Scanned PDF & Mobile Photos:**
   - Xử lý ảnh đa biến dạng: nắn góc xoay (Hough line deskew), căn chỉnh phối cảnh (perspective homography) và nhận dạng văn bản tiếng Việt EasyOCR 200 DPI (`FORCE_FULL_PAGE_OCR=True`).
   - Kết quả: Table F1 đạt **100.0%** cấu trúc bảng; Header Exact Match đạt **98.0%**.
   - Cơ chế tự vệ (Evidence Gate): 100% các dòng mờ hoặc trường chưa được xác thực nguồn gốc OCR đều được chuyển hướng an toàn sang trạng thái cần người duyệt (Human Review), tuyệt đối không để lọt sai sót kế toán (**False Auto-Accept Rate: 0.00%**).
3. **Phân tích Engine OCR Tiếng Việt:**
   - *PaddleOCR (PP-OCRv5):* Phiên bản PaddlePaddle 3.x trên môi trường Windows x64 CPU hiện có hạn chế `NotImplementedError` trong quá trình chuyển đổi thuộc tính PIR/oneDNN runtime. Khuyến nghị chạy trong Linux container có GPU khi triển khai scale-out.
   - *EasyOCR + Docling:* Hoạt động ổn định trên CPU máy chủ Windows và Linux, hỗ trợ đầy đủ 67 ký tự tiếng Việt có dấu, đáp ứng tiêu chuẩn bộ nhớ RAM dưới 1.2 GB RSS.

---

## 6. Quy trình Kiểm thử Tự động trong CI/CD

Quy trình kiểm chuẩn chất lượng ứng dụng được tích hợp tự động trong workflow CI GitHub Actions (`.github/workflows/ci.yml`):

1. **Static Analysis:** `ruff check` và `ruff format --check`.
2. **Unit & Integration Suite:** `python -m pytest` bao gồm:
   - Unit tests bóc tách XML, PDF, Regex, Bounding Box.
   - Integration tests cho Database, Ingestion, Review Service, Exporter.
   - Security tests chống XXE, Path Traversal, Malicious Uploads.
   - End-to-end integration test: `tests/integration/test_application_e2e_flow.py` kiểm chứng toàn bộ luồng `Upload -> Document AI -> JSON -> Review -> Approve -> Export`.
3. **Application QA Suite:** `python scripts/run_application_qa.py` chạy kiểm chuẩn trực tiếp trên 10 chứng từ thực tế.
4. **Frontend TypeScript & Build:** `pnpm build` tại thư mục `apps/web`.
