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
3. **Docling + EasyOCR Engine:** Bóc tách tài liệu dạng ảnh và scan chất lượng thấp bằng Docling kết hợp EasyOCR đa ngôn ngữ `["vi", "en"]`. Tự động nhận diện và chuẩn hóa góc xoay trang trước khi OCR.
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

> **Môi trường chạy:** Windows x64, Python 3.12, PyTorch CPU, Docling + EasyOCR (`vi`, `en`), Vision AI Provider: `https://api.modelapi.vn/v1` (`gpt-6.1-sol`).
> **Lệnh kiểm chứng:** `python scripts/run_application_qa.py`

### Bảng kết quả chi tiết từng chứng từ:

| Case ID | Loại chứng từ | Kết quả | Header Match | Line Items F1 | Độ trễ xử lý |
|---|---|:---:|:---:|:---:|---:|
| **CASE-01-XML-STANDARD** | `xml_standard` | **PASS** | 100.0% | 100.0% | 4.5 ms |
| **CASE-02-PDF-DIGITAL** | `pdf_digital` | **PASS** | 100.0% | 100.0% | 14,448.8 ms |
| **CASE-03-PDF-SCAN** | `pdf_scan` | **PASS** | 72.7% | 100.0% | 27,899.0 ms |
| **CASE-04-DISCREPANCY-PRICE** | `discrepancy_price` | **PASS** | 100.0% | 100.0% | 3,005.4 ms |
| **CASE-05-DISCREPANCY-QTY** | `discrepancy_qty` | **PASS** | 100.0% | 100.0% | 1.7 ms |
| **CASE-06-PDF-MULTI-LINE** | `pdf_digital_table` | **PASS** | 100.0% | 100.0% | 3,605.5 ms |
| **CASE-07-PDF-ROTATED-SCAN** | `pdf_scan_rotated` | **PASS** | 72.7% | 100.0% | 31,509.8 ms |
| **CASE-08-PDF-COMPLEX-AMOUNTS** | `pdf_digital_numeric` | **PASS** | 100.0% | 100.0% | 2,844.4 ms |
| **CASE-09-PDF-MIXED** | `pdf_mixed` | **PASS** | 72.7% | 100.0% | 2,781.7 ms |
| **CASE-10-PDF-SCAN-TABLE** | `pdf_scan_table` | **PASS** | 100.0% | 100.0% | 34,259.2 ms |

### Tổng hợp chỉ số toàn hệ thống:

- **Tỷ lệ vượt qua nghiệm thu (Overall Pass Rate):** **10/10 chứng từ (100.0%)**
- **Độ chính xác thông tin chung (Overall Header Match):** **91.8%**
- **Độ chính xác dòng hàng (Overall Line Items F1):** **100.0%**
- **Tính hợp lệ số học (Arithmetic Validity Rate):** **100.0% (Không có bất kỳ sai số số học nào)**
- **Phát hiện chênh lệch đối soát (Anomaly Detection F1):** **100.0% (Nhận diện chính xác 100% lệch giá và lệch lượng)**
- **Thời gian xử lý trung bình toàn pipeline:** **12,036.0 ms**

---

## 5. Quy trình Kiểm thử Tự động trong CI/CD

Quy trình kiểm chuẩn chất lượng ứng dụng được tích hợp tự động trong workflow CI GitHub Actions (`.github/workflows/ci.yml`):

1. **Static Analysis:** `ruff check` và `ruff format --check`.
2. **Unit & Integration Suite:** `python -m pytest` bao gồm:
   - Unit tests bóc tách XML, PDF, Regex, Bounding Box.
   - Integration tests cho Database, Ingestion, Review Service, Exporter.
   - Security tests chống XXE, Path Traversal, Malicious Uploads.
   - End-to-end integration test: `tests/integration/test_application_e2e_flow.py` kiểm chứng toàn bộ luồng `Upload -> Document AI -> JSON -> Review -> Approve -> Export`.
3. **Application QA Suite:** `python scripts/run_application_qa.py` chạy kiểm chuẩn trực tiếp trên 10 chứng từ thực tế.
4. **Frontend TypeScript & Build:** `pnpm build` tại thư mục `apps/web`.
