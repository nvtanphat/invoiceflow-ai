# Quality & Benchmark — Protocol tái lập, không thổi phồng kết quả

> Mọi số trong tài liệu này là **quy mô/mốc kế hoạch**, không phải kết quả thực nghiệm. Benchmark là bằng chứng chất lượng ứng dụng AI; không đổi GT, test split, scorer để đạt điểm tốt.

## 1. Phân biệt bốn bài toán đo lường

| Track | Bài toán | Data/GT | Metric chính | Không được suy diễn |
|---|---|---|---|---|
| T1 Document parsing | OCR/layout/table/bbox/reading order | DocILE subset, fixtures nội bộ | location F1/AP hoặc table structure/word accuracy | Không kết luận invoice extraction tốt chỉ từ Markdown similarity |
| T2 Invoice extraction | vendor, tax ID, invoice #, amount, date, lines | International 181 synthetic + VN frozen | header exact match, line item F1, full doc | Không trộn data synthetic quốc tế với Vietnam corpus |
| T3 AP reconciliation | invoice vs PO vs GRN, duplicate/review/approval | scenario fixtures có source-of-truth | decision accuracy, unsafe pass rate, exception precision/recall | OCR accuracy không chứng minh giao dịch đúng |
| T4 Production reliability | concurrency, retries, crashes, cost/latency | synthetic workload, failure injection | success, duplicate effects, p50/p95, throughput | unit tests không thay thế load/E2E |

**Quan trọng:** `fully correct invoice` không có nghĩa `legally valid invoice`; `signature verified` và `tax authority checked` cần kiểm tra riêng, có integrations thực sự. Không báo chỉ số “accuracy hệ thống” bằng phép cộng các track khác nhau.

## 2. Dữ liệu đã đối chiếu và cách sử dụng

### A. Invoice Extraction Benchmark — 181 documents (synthetic international)

Nguồn: https://github.com/DrewKraken/invoice-extraction-benchmark

- 181 tài liệu synthetic, JSON answer keys và scorer công khai; có digital PDF, ảnh scan, scan hư, handwritten, currencies, VAT, multi-page; tạo bởi nhà cung cấp InvoiceParser Pro, **không phải bộ độc lập**.
- Code scorer/generator MIT; corpus/examples CC BY 4.0; ghi attribution và license trong báo cáo. Không lấy điểm nhà cung cấp làm baseline do mình chạy.
- Chạy scorer chính chủ không sửa logic để so sánh bên ngoài; giữ `predictions.json`, `scores.json`, `scores.md`, manifest, config, code SHA, per-doc errors. Không dùng cùng GT để prompt-engineer rồi công bố như unseen test.
- Hạn chế: mostly English/non-Vietnam, synthetic từ một layout engine, số lượng mỗi category nhỏ; thêm báo cáo theo nhóm.

**Ví dụ sau khi clone benchmark riêng, với dự đoán thật:**

```bash
python -m scorer.evaluate predictions.json --markdown scores.md --out scores.json
```

### B. DocILE — KILE/LIR (benchmark document understanding)

Nguồn: https://github.com/rossumai/docile

- Official evaluation đòi vị trí `page/bbox/fieldtype` và với LIR phải group line items; không chỉ exact-string JSON extraction. Official evaluation `docile_evaluate` trên validation; test chính thức phải theo quy trình benchmark.
- **Chỉ chạy nếu đã implement bbox/line-item linkage tương thích**. Nếu không, ghi “not evaluated”, đừng đặt chỉ số tạm giống official F1.
- Giữ nguyên scorer/metric; lưu experiment tag track `DOCILE_KILE`/`DOCILE_LIR` và per-document errors; không gộp T1 với T2.

### C. Vietnam AP Casebook (nội bộ, synthetic/được cấp phép)

**Mục tiêu:** tập tài liệu doanh nghiệp đúng định dạng Việt Nam và các case invoice/PO/GRN, không đưa thông tin thật ra repo. Thiết kế tối thiểu 200–240 case khi có nguồn lực; MVP nhỏ hơn phải ghi rõ giới hạn độ tin cậy.

**Đề xuất stratification 8 nhóm** (định hướng, không biến thành KPI giả):

1. XML chuẩn một hóa đơn, nhiều tax rates/line items.
2. PDF digital có bảng/ô gộp/chiết khấu/nhiều trang.
3. PDF scan/ảnh có xoay, mờ, noise, dấu tiếng Việt.
4. PDF và XML của một hóa đơn, sai khác field hoặc thiếu file.
5. Trùng theo file hash; trùng theo business key nhưng file khác.
6. PO price variance/discount/freight tolerance; thiếu PO.
7. GRN split deliveries, partial receipts, returns, over-invoice, missing GRN.
8. Invalid/ambiguous: missing tax ID, invalid date, credit note, wrong currency, multi-invoice file, malicious prompt injection, unsupported document.

**GT mỗi case:** source files SHA, expected invoice JSON with line items/evidence if applicable, expected issue codes, expected review decision, linked PO/GRN rows, expected no-side-effect decisions. Cùng một business case có thể có XML/PDF/scan variants → group cùng split để ngăn leakage.

### D. Real vendor invoices (nếu được doanh nghiệp cho phép)

- Phải có quyền dùng dữ liệu rõ ràng, mục đích, cách xử lý PII, hạn lưu trữ, nhà cung cấp API được phép nhận dữ liệu hay không. Không đăng raw thật trên GitHub, Hugging Face hoặc free API tier nếu không có quyền.
- GT do hai người kiểm độc lập với adjudication cho disagreement, lưu label source/redaction method/annotation guideline; báo riêng chất lượng GT và sự khác biệt với synthetic.
- Không claim “real-world robust” chỉ vì có 10 hóa đơn thực tế chọn tay.

## 3. Freeze split & chống data leakage

- `train/dev`: dùng để thiết kế schema/routing/prompt/threshold, không công bố kết quả tổng quát hóa.
- `validation`: chọn configuration và hiệu chỉnh review thresholds. Nhóm cùng vendor/template/generator seed vào cùng một partition; hash, near-duplicate, PDF+XML pairs cùng group.
- `test/holdout`: khóa sau khi tạo, không đọc labels để điều chỉnh; chỉ mở cho lần chạy cuối của ứng viên đã chốt; nếu lỡ dùng để tune, tạo holdout mới và công bố lý do.
- Freeze `dataset_manifest.json` với files SHA, source/license, split, group ID, GT SHA; `experiment.json` với commit SHA, dependency lock hash, parser/model/prompt/policy, concurrency, seed, OS/CPU/RAM, API quota, price table timestamp.
- Source docs và labels riêng; output prediction không được nhập GT vào prompt. Deterministic routing decision chạy **trên observation thực tế**, không đọc `expected_*` của fixture.
- Với benchmark 181, scorer và file gold được đánh giá offline sau khi predictions hoàn tất; production worker tuyệt đối không có path tới GT.

## 4. Baselines & Ablations — Đo đạc độc lập, không trộn lẫn dữ liệu

### Bộ 6 Baselines thẩm định chuẩn (B0–B5)

| ID | Pipeline | Mô tả kỹ thuật | Mục đích đánh giá |
|---|---|---|---|
| **B0** | `B0_XML_DIRECT` | XML parser bảo mật, trích xuất tất định Thông tư 78 | Upper baseline cho input định dạng cấu trúc chuẩn |
| **B1** | `B1_PYMUPDF_RULES` | PyMuPDF text extraction + heuristic regex rules | Baseline CPU tốc độ cao cho PDF văn bản số |
| **B2** | `B2_DOCLING_TEXT_RULES` | Docling canonical structure (không OCR) + regex rules | Đo lường giá trị của mô hình cấu trúc layout Docling |
| **B3** | `B3_DOCLING_OCR_STRUCTURED` | Docling + RapidOCR Vietnamese + `StructureAwareTableExtractor` | Baseline Document AI cục bộ bóc tách bảng cấu trúc |
| **B4** | `B4_PURE_VISION_LLM` | Multimodal Vision API trực tiếp từ ảnh rendered | Đo lường độ phụ thuộc và chi phí/độ trễ khi dùng model thuần |
| **B5** | `B5_INVOICEFLOW_HYBRID` | Multi-signal router + Docling OCR Structured + 3-way matching | Ứng viên hệ thống hoàn chỉnh (production candidate) |

### Bộ 6 Thử nghiệm suy biến cấu trúc (Ablation Studies A0–A5)

| ID | Biến thể | Loại bỏ thành phần nào? | Mục tiêu kiểm chứng |
|---|---|---|---|
| **A0** | `A0_FULL_HYBRID_SYSTEM` | Không (hệ thống đầy đủ) | Baseline chuẩn đối chiếu toàn diện |
| **A1** | `A1_NO_TABLE_EXTRACTOR` | Bỏ `StructureAwareTableExtractor` | Kiểm chứng vai trò bóc tách bảng cấu trúc so với regex phẳng |
| **A2** | `A2_NO_OCR` | Bỏ RapidOCR trên tài liệu scan/ảnh/xoay | Đo lường suy giảm chính xác khi thiếu OCR cục bộ |
| **A3** | `A3_NO_VALIDATION` | Bỏ kiểm tra số học và đối soát 3 chiều | Đo lường rủi ro sai lệch tài chính bị lọt lưới kiểm toán |
| **A4** | `A4_NO_VISION_FALLBACK` | Bỏ Vision LLM fallback | Đánh giá khả năng tự vận hành độc lập 100% offline |
| **A5** | `A5_NO_HYBRID_ROUTING` | Bỏ Document Router (ép chạy đồng nhất 1 đường) | Chứng minh vai trò phân luồng đa tín hiệu đối với độ chính xác |

Luôn cùng document IDs, same model version, cùng concurrency/caching policy, API retries, ngày và giá. Khi model API không pin được snapshot, ghi model release ID thực tế + timestamp, nêu giới hạn lặp lại.

## 5. Metric — định nghĩa trước khi chạy

### Trích xuất các trường

- `Field exact match`: đúng sau canonical normalization đã công bố cho loại field; `invoice_number`, `tax_id` giữ leading zeros; dates ISO 8601; currency ISO 4217; monetary exact sau quantization hợp lệ theo nghiệp vụ; **không fuzzy đối với tiền/ID/tax**.
- `Micro P/R/F1`: các `(document_id, field_path, occurrence, value)` ghép theo schema và matching policy khóa trước. Phải tính cả false positive khi GT null, missing key, duplicates. Macro per-field và per-document riêng để tránh trường thường gặp lấn át.
- `Header all-correct`: fraction documents mà **tất cả key headers** đúng; tính trên cả tài liệu failed/abstained, và báo coverage riêng.
- `Line item F1`: khớp 1-to-1 bằng bipartite assignment/Hungarian theo exact amount + normalized description + qty/price trong tolerance pre-registered; tránh một predicted line match nhiều GT lines. Báo group/bbox if required.
- `Unsupported value rate`: các predicted non-null fields không có evidence in document hoặc xung đột XML; false-evidence and wrong-bbox rates riêng. LLM tự nói confidence 0.99 không chứng minh calibrated probability.

### Đối soát và kiểm duyệt

- `False-safe-approval rate` = cases flagged risky in GT nhưng hệ thống cho auto-pass / tổng risky cases; metric an toàn trọng yếu.
- `Issue precision/recall/F1` cho từng code (duplicate, price, quantity, missing PO/GRN).
- `Review burden` = review-required documents / total; `auto-accepted correctness` = accurate approvals among auto-accepted; tính latency và chi phí sau review, không chỉ inference.
- `Wrong business write` = bất kỳ sai khác DB/export ngoài expected transition; **mục tiêu P0 là 0 trên bộ adversarial tests**, không công bố 0 toàn bộ thế giới.
- Dữ liệu mới sau review là corrected final, **không** dùng nó để che accuracy automatic extraction.

### Hệ thống và hiệu năng

- Latency `p50/p95/p99` riêng upload acknowledgment, queue wait, parse, provider, validation, review, export; wall-clock E2E.
- Throughput `docs/min` và `pages/min`, concurrency/worker counts, RAM peak, CPU, API rate limit; nêu warm/cold cache.
- `Cost/doc` = billed tokens (text + image/pages) * price-per-token applicable + provider extras; ghi currency/time; tính failed calls/retries và rate limit (nếu bị tính phí).
- Reliability: error/retry/DLQ %, idempotency duplicate effect count, tenant breach count, extraction stale revision count.

## 6. Thống kê và điều kiện kết luận

- Per-document paired comparison B1/B2/B3/B4 trên **cùng IDs**; bootstrap percentile 95% CI resample theo document/group (không theo field độc lập khi fields cùng tài liệu), seed recorded, >= 1,000 resamples nếu n đủ.
- Nêu sample count, missing/failed cases, per-category count, CI; không nói “better” chỉ bởi một lần chạy chênh 0.2 điểm.
- Nêu khả năng supplier/template memorization, image damage synthetic, API stochasticity, quota và token caching; báo median của ít nhất 3 lần cho latency/cost khi phù hợp, tách batch/warm-up.
- Metric safety không được trung bình với OCR F1 để ra một điểm tổng tùy tiện. Config B4 final được chọn trên validation, đánh giá test một lần.

## 7. Protocol chạy tiêu chuẩn và artifact format

```text
1. audit source/permissions/GT; validate manifest and hashes
2. freeze split by vendor/layout/template/business group
3. run preflight of parser/LLM capabilities (no raw PII)
4. run B1/B2/B3/B4 on same eligible document IDs
5. export prediction JSONL per document and errors; no GT fed to inference
6. run official scorer (when supported) plus own invoice/business scorer
7. compute stratified scores, paired CI, failure taxonomy, latency/cost
8. manual inspect 20-30 failed docs with evidence and compare pipelines
9. publish result tables + data provenance + limitations
10. choose production B4 only if quality, safety and budget acceptance met
```

**Mỗi run (trong gitignored artifacts, immutable):**

```text
runs/<run_id>/
  manifest.json            # repo commit, config hash, dataset/license, hardware, provider model and costs
  predictions.jsonl        # per-document candidate outputs, masked identifiers
  metrics.json             # per-field/category/system incl denominators/CI
  errors.jsonl             # stage-specific error class and taxonomy
  stage_timings.jsonl      # per-stage latency with warmed/cold tag
  cost.json               # token accounting and pricing timestamp
  analysis.md              # errors, qualitative examples (synthetic), caveats
```

`run_id` là ID artifact bất biến, khác với tên file source. Model benchmark CLI **import** modules production, không fork logic sang `benchmark_parser_fix.py`. Có thể export metric summary (không dữ liệu nhạy cảm) vào `reports/` nếu báo cáo công khai; không commit raw customer docs.

## 8. Test matrix thực thi

| Type | Example | Expected outcome |
|---|---|---|
| Unit | money Decimal 0.1+0.2, VAT variable, negative credit | no floating error, correct policy |
| Parser | XML with DTD external entity | rejected, no network/file access |
| Parser | mixed PDF pages + rotated scan | per-page routing, bbox accurate or marked missing |
| Contract | Gemini invalid JSON / extra field | validated error, no write |
| Source | XML != paired PDF | discrepancy review, do not auto-overwrite |
| Security | prompt inject in document asks to ignore rules | treated as untrusted data |
| Authorization | tenant A guesses tenant B invoice ID | 403/404 per policy, zero data leak |
| Idempotency | queue same message twice | single effective artifact/write |
| Worker | crash after DB commit before queue ack | reconciled job, no duplicate export |
| Approval | stale `If-Match` | 409 conflict |
| AP | two partial GRNs sum to invoice qty | correct 3-way match |
| AP | price delta above tolerance | issue requiring review |
| E2E | upload -> process -> correct -> approve -> export | completed, trace/evidence/audit all linked |
| Load | 25/100/500 docs and limited CPU | bounded memory, queue backlog visible, graceful degradation |

## 9. Release acceptance thresholds (targets, not measurements)

Mọi threshold phải được chốt **trước test**, dựa trên requirement/prioritization:

- P0 business safety: **zero unauthorized actions/exports, zero duplicated paid-side effects** trên test suite adversarial đã định nghĩa.
- Critical false-safe-approval: mục tiêu zero trên golden exceptions; nếu có case bị pass sai → NO-GO và cần root cause.
- Schema validity: 100% accepted records conform Pydantic; invalid outputs never silently accepted.
- Evidence: critical fields thiếu nguồn phải `needs_review`; không có bbox giả.
- Reliability: simulated provider timeout, worker restarts, Redis failure recover theo runbook; no stuck without alert.
- Performance: chốt budget theo máy 16 GB và API limits sau pilot; không chọn số p95 “đẹp” vô căn cứ.
- Documentation: toàn bộ claims đo đạc phải có manifest và per-document predictions; no benchmark if no source.

## 10. Báo cáo ngắn cho CV

**Bảng bắt buộc:** (1) Dataset/source/split; (2) 4 baselines trên same docs; (3) per-field exact/F1; (4) line items; (5) issue recall/false approval; (6) errors; (7) p95/throughput/cost; (8) ablations. Không dùng một biểu đồ màu để che mẫu nhỏ hoặc số liệu không được đo.

**Nguồn và license:** xem `REFERENCES.md`. Luôn ghi benchmark 181 synthetic là vendor-created, không phải dữ liệu doanh nghiệp Việt Nam thật.

## 11. Kết quả thực nghiệm đo đạc thực tế (Frozen Benchmark & Ablation Results)

> **Cập nhật 2026-11-08 (reengineering lần 2):** phiên bản trước của bảng này có hai lỗi đo lường nghiêm trọng đã được sửa, không phải cải thiện mô hình: (1) `table_f1` được tính bằng cách gọi lại chính hàm `compute_line_items_f1`, nên **luôn luôn bằng hệ Line Item F1 một cách tuyệt đối** — bảng cũ cho thấy hai cột giống hệt nhau ở mọi hàng, đó là bằng chứng của lỗi, không phải sự trùng hợp. (2) `arithmetic_validity_rate` mặc định về `1.0` khi không có dữ liệu nào để kiểm tra, khiến các trường hợp "không đo được gì" bị báo cáo thành "100% đúng". Cả hai lỗi đã được sửa tại `benchmarks/scripts/evaluator.py` (xem `compute_table_structure_f1`, `average_arithmetic_validity`) với test hồi quy tại `tests/unit/test_benchmark_evaluator.py`. Xem thêm `docs/decisions/2026-11-08-document-ai-core-reengineering.md`.

Bộ case cũng được mở rộng từ 8 lên **10 chứng từ** để có phủ sóng thật cho PDF hỗn hợp (mixed, 1 trang digital + 1 trang scan) và PDF scan thuần chứa bảng nhiều dòng hàng — hai tình huống trước đó hoàn toàn vắng mặt trong bộ đóng băng dù tài liệu benchmark đã mô tả chúng. So sánh trước/sau bên dưới dùng **đúng 8 case gốc** để đảm bảo apples-to-apples; bảng B0–B5/A0–A5 chính dùng toàn bộ 10 case hiện hành.

Dữ liệu thô và chi tiết từng dự đoán được lưu trữ bất biến tại:
- Báo cáo Benchmark (sau sửa, 10 case): `benchmarks/results/benchmark_report.json`, `benchmarks/results/benchmark_summary.csv`, `benchmarks/results/predictions.jsonl`
- Báo cáo Ablation (sau sửa, 10 case): `benchmarks/results/ablation_report.json`, `benchmarks/results/ablation_summary.csv`
- Snapshot **trước khi sửa** (commit `bd18953`, 8 case, evaluator cũ còn lỗi tautology): `benchmarks/results/before_fix/`
- Bằng chứng OCR thực (CER/WER, nhận dạng số tiền, cấu trúc bảng dưới OCR): `benchmarks/results/ocr_quality_report.json`
- Bằng chứng BBox evidence grounding (ảnh render thật): `benchmarks/results/evidence/case_06_bbox_evidence.png`

### Bảng 1: Kết quả so sánh 6 Baselines (B0–B5), 10 chứng từ hiện hành

| Pipeline Baseline | Header EM | Line Item F1 | Table F1 | Tính hợp lệ số học | Anomaly F1 | Độ trễ TB | Chi phí / 1k HĐ |
|---|---|---|---|---|---|---|---|
| **B0: XML Direct Parser** | 20.0% | 20.0% | 20.0% | 100.0% | 80.0% | 0.4 ms | $0.00 |
| **B1: PyMuPDF Rules** | 31.8% | 20.0% | 58.0% | 100.0% | 80.0% | 10.0 ms | $0.00 |
| **B2: Docling Text Rules** | 70.0% | 60.0% | 60.0% | 100.0% | 80.0% | 3,604.0 ms | $0.00 |
| **B3: Docling OCR Structured** | 81.8% | 65.0% | 70.0% | 73.8% | 80.0% | 3,669.5 ms | $0.00 |
| **B4: Pure Vision LLM** | 0.0% | 0.0% | 0.0% | N/A (không có dòng nào để kiểm) | 80.0% | 5,312.9 ms | $0.00 |
| **B5: InvoiceFlow Hybrid** | **81.8%** | 65.0% | 70.0% | 73.8% | 76.7% | 3,321.7 ms | $0.00 |

**Table F1 ≠ Line Item F1** ở B1 (58.0% so với 20.0%) và lệch ở B3/B5 — bằng chứng trực tiếp rằng hai chỉ số nay được tính độc lập (xem Mục 12.3). `arithmetic_validity_rate` của B3/B5 giảm từ con số 100.0% (cũ, giả) xuống 73.8% (thật) vì nay hệ thống thực sự tạo ra các dòng có `qty` bị thiếu do cell-merge và trung thực đánh dấu thay vì bịa `qty=1`.

*Ghi chú về B4:* Header EM = 0% là **tồn tại từ trước khi sửa** (xem `benchmarks/results/before_fix/benchmark_report.json`, B4 cũng 0.0% trên bộ 8 case cũ) — không phải regression do 4 nhiệm vụ này gây ra, và nằm ngoài phạm vi (Vision LLM pipeline không thuộc Table Extraction/OCR/Evidence Grounding/Benchmark). Cần điều tra riêng ở backlog khác.

---

### Bảng 1b: So sánh trước/sau sửa trên đúng 8 case gốc (apples-to-apples)

| Baseline | Header EM (trước→sau) | Line F1 (trước→sau) | Table F1 (trước→sau) | Arith Validity (trước→sau) |
|---|---|---|---|---|
| B0 | 25.0% → 25.0% | 25.0% → 25.0% | 25.0% → 25.0% | 100% → 100% |
| B1 | 68.2% → 36.4% | 72.5% → 25.0% | 72.5% → 72.5% | 100% → 100% |
| B2 | 68.2% → 77.3% | 72.5% → 75.0% | 72.5% → 75.0% | 100% → 100% |
| **B3** | 75.0% → **83.0%** | 72.5% → 75.0% | 72.5% → 75.0% | 100% (giả) → **77.8% (thật)** |
| B4 | 0.0% → 0.0% | 0.0% → 0.0% | 0.0% → 0.0% | N/A → N/A |
| **B5** | 75.0% → **83.0%** | 72.5% → 75.0% | 72.5% → 75.0% | 100% (giả) → **77.8% (thật)** |

B1 giảm Header EM/Line F1 vì `compute_line_items_f1` cũ cho khớp quá dễ (so khớp OR giữa sku-substring và amount-equal — xem Mục 12.3); con số cũ 72.5% là **khớp giả**, con số mới 25.0% phản ánh đúng việc B1 (PyMuPDF text thuần + regex) thật sự không trích xuất đúng line item trên phần lớn case. B3/B5 tăng Header EM vì bug sku/sku_ref và bug phân loại cột (Mục 12.3) trước đây khiến `StructureAwareTableExtractor` luôn trả về 0 dòng trên case_06, kéo cả pipeline rơi vào nhánh fallback kém chính xác hơn.

---

### Bảng 2: Kết quả thử nghiệm suy biến kiến trúc (Ablation Studies A0–A5), 10 chứng từ hiện hành

| Biến thể kiến trúc | Header EM | Line F1 | Table F1 | Arith Validity | Anomaly F1 | Độ trễ TB |
|---|---|---|---|---|---|---|
| **A0: Full Hybrid System** | 81.8% | 65.0% | **70.0%** | 73.8% | 76.7% | 4,479.3 ms |
| **A1: No Table Extractor** | 81.8% | 66.7% | **66.7%** | 100.0% | 100.0% | 3,334.1 ms |
| **A2: No Local OCR** | 70.0% | 60.0% | 60.0% | 77.8% | 86.7% | 2,456.1 ms |
| **A3: No Validation** | 81.8% | 65.0% | 70.0% | 73.8% | 80.0% | 3,328.1 ms |
| **A4: No Vision Fallback** | 81.8% | 65.0% | 70.0% | 73.8% | 76.7% | 3,324.9 ms |
| **A5: No Hybrid Routing** | 51.8% | 40.0% | 40.0% | 66.7% | 76.7% | 2,332.4 ms |

**Phát hiện chính (Mục 12.1):** trước khi sửa, A0 và A1 **giống hệt nhau trên mọi chỉ số** (`benchmarks/results/before_fix/ablation_report.json`) — bằng chứng trực tiếp `StructureAwareTableExtractor` không hề đóng góp gì đo lường được. Sau khi sửa, A0 (bật table extractor) đạt Table F1 70.0% so với A1 (tắt) 66.7% — chênh lệch thật, lần đầu tiên đo được giá trị gia tăng của tầng trích xuất bảng cấu trúc.

---

### 12. Phân tích chi tiết các phát hiện kỹ thuật (Engineering Deep Dive)

#### 1. `StructureAwareTableExtractor` trước khi sửa không đóng góp gì đo lường được (A0 ≡ A1)
Trước khi sửa, bật/tắt table extractor (A0 vs A1) cho **kết quả giống hệt nhau ở mọi chỉ số** — bằng chứng cho thấy tầng trích xuất bảng chưa bao giờ thực sự chạy trên dữ liệu thật trong benchmark. Truy vết trực tiếp trên `case_06.pdf` (bảng 3 dòng hàng thật từ Docling TableFormer) cho thấy ba lỗi gốc rễ tại `table_extractor.py`:

- **Lỗi phân loại cột:** `_detect_column_headers` (bản cũ) duyệt `COLUMN_PATTERNS` theo thứ tự dict và dừng ở khớp đầu tiên. Tiêu đề gộp "Ten hang hoa, dich vu / SKU" chứa cả `"sku"` lẫn `"ten hang"`; vì `"sku"` được kiểm tra trước, cột mô tả hàng hóa bị gán nhầm thành cột SKU trên **mọi dòng**, xóa sổ trường `description` của toàn bộ bảng.
- **Lỗi rơi dòng âm thầm:** điều kiện chốt dòng cũ yêu cầu `current_line.get("description")` phải truthy, nếu không dòng bị **âm thầm xóa, không cờ cảnh báo**. Vì lỗi phân loại cột ở trên luôn khiến `description` rỗng, toàn bộ 3 dòng hàng của `case_06.pdf` bị rơi mất → `extract_invoice_lines` trả về 0 dòng bất kể table extractor bật hay tắt.
- **Merged cell (colspan) không được xử lý:** TableFormer đôi khi gộp ô "mô tả" và "số lượng" liền kề thành một ô colspan=2 (quan sát thật trên dòng 2 của `case_06.pdf`). Code cũ không phát hiện việc này, dẫn tới cột `qty` bị thiếu dữ liệu hoàn toàn cho dòng đó.

**Đã sửa** (`table_extractor.py`): phân loại cột theo khớp dài nhất/đặc hiệu nhất thay vì khớp đầu tiên theo thứ tự dict; chốt dòng dựa trên "có bất kỳ định danh nào" (description/sku/line_amount) thay vì riêng `description`; phát hiện ô merge qua colspan/rowspan và gắn cờ `CELL_MERGE_SUSPECTED` thay vì bịa số liệu từ văn bản tự do (xem thử nghiệm `tests/unit/document/test_table_extractor.py::test_combined_header_with_inline_sku_keyword_does_not_hijack_description_column`, `::test_colspan_merged_data_cell_is_flagged_not_fabricated`). Kết quả thật trên `case_06.pdf` sau sửa: 3/3 dòng được trích xuất với SKU/mô tả/đơn giá/thuế suất đúng; dòng 2 (bị TableFormer gộp ô) đúng đắn nhận `qty=0` kèm cờ `CELL_MERGE_SUSPECTED` thay vì một con số bịa ra.

#### 1b. Cơ chế tự "sửa" `qty=0` → `1` đã bị gỡ bỏ
Code cũ có dòng `qty=qty if qty > 0 else Decimal("1.0000")`, âm thầm thay mọi số lượng 0 (dù là giá trị thật trên hóa đơn, hay do parse lỗi) thành 1 — vi phạm trực tiếp nguyên tắc "không tự sửa số liệu kế toán". Đã gỡ bỏ; `qty=0` thật nay được giữ nguyên kèm cờ `QTY_ZERO_OR_MISSING` để kế toán xác minh (`tests/unit/document/test_table_extractor.py::test_zero_quantity_is_preserved_and_flagged_not_rewritten_to_one`).

#### 2. Vai trò sống còn của Multi-signal Hybrid Router (Kiểm chứng qua A5)
Khi loại bỏ router thông minh và ép toàn bộ chứng từ chạy qua đường digital duy nhất (A5): Header EM sụp đổ xuống 51.8%, Table F1 xuống 40.0% — chứng từ scan/XML bị đọc sai đường, mất trắng dữ liệu dòng hàng. Document Router dựa trên phân loại trang (`PDFInspector`) vẫn là thành phần bảo vệ tính toàn vẹn bắt buộc của pipeline, không đổi so với lần đo trước.

#### 3. `table_f1` và `lines_f1` nay là hai chỉ số độc lập, không còn là một phép tính nhân đôi
`benchmarks/scripts/evaluator.py` trước đây định nghĩa `compute_table_extraction_quality` bằng cách **gọi lại chính `compute_line_items_f1`** — nên `table_f1` tuyệt đối bằng `lines_f1` ở mọi trường hợp, không đo được gì về cấu trúc bảng độc lập với độ đúng ngữ nghĩa của dòng hàng. Đã thay bằng `compute_table_structure_f1`: đo tỷ lệ dòng có đủ các ô cấu trúc số (`qty`/`unit_price`/`line_amount`) được điền theo đúng vị trí, hoàn toàn tách biệt khỏi việc giá trị bên trong có đúng về nghiệp vụ hay không. Phép khớp dòng hàng (`compute_line_items_f1`) trước đây cũng quá dễ dãi — khớp OR giữa "sku chứa substring của nhau" (kể cả substring rất ngắn) **hoặc** "amount bằng nhau", nghĩa là hai dòng khác hẳn nhau nhưng trùng giá tiền vẫn được tính là khớp đúng. Nay yêu cầu **AND**: phải vừa khớp định danh (sku chính xác, hoặc containment với độ dài tối thiểu 4 ký tự) **vừa** khớp amount trong dung sai 1 VNĐ. Bằng chứng số liệu: Bảng 1b cho thấy B1's Line F1 giảm từ 72.5% (khớp giả) xuống 25.0% (khớp thật) sau khi siết lại luật so khớp. `arithmetic_validity_rate` cũng không còn mặc định `1.0` khi không có dữ liệu để kiểm (`total_checked == 0`) mà trả về `None`/"N/A" trung thực — xem cột B4 ở Bảng 1.

#### 4. Đánh đổi đã biết: cờ `CELL_MERGE_SUSPECTED` đúng đắn làm giảm nhẹ Anomaly F1 ở B5/A0
So với A1 (tắt table extractor, Anomaly F1 = 100.0%), A0 (bật, Anomaly F1 = 76.7%) thấp hơn. Nguyên nhân: dòng hàng thứ 2 của `case_06.pdf` bị TableFormer gộp ô (Mục 12.1), nay đúng đắn có `qty=0` kèm cờ cảnh báo thay vì bịa `qty=5`; khi đối soát 3 chiều với PO, `qty=0` khác `ordered_qty=5` nên hệ thống **đúng đắn** phát sinh `QUANTITY_MISMATCH` dù ground-truth tổng hợp không kỳ vọng sai lệch này (ground truth giả định table-structure-recognition hoàn hảo). Đây là đánh đổi có chủ đích, ưu tiên an toàn dữ liệu kế toán hơn là điểm số đẹp trên bộ test tổng hợp — **không sửa** `MatchingEngine` để che giấu việc này vì nằm ngoài phạm vi 4 nhiệm vụ cốt lõi hiện tại; ghi nhận làm backlog riêng: cân nhắc để `MatchingEngine` coi dòng có cờ `CELL_MERGE_SUSPECTED`/`QTY_ZERO_OR_MISSING` là "không đủ dữ liệu để đối soát" thay vì "số lượng bằng 0".

#### 5. Evidence Grounding: mỗi trường/dòng hàng nay liên kết được tới `table_id`/`cell_id`/`page_index`/BBox
`DocumentCell.id`/`table_id` trước đây không bao giờ được gán giá trị (luôn `None`) dù schema đã có sẵn trường này — không có cách nào truy vết ngược từ một field về ô bảng nguồn. `evidence_mapper.py` cũng chỉ map evidence cho 4 trường header, chưa từng tạo evidence cho dòng hàng. Đã sửa: `docling_adapter.py`/`layout_extractor.py` gán `id`/`table_id` xác định cho mỗi `DocumentCell`; `StructureAwareTableExtractor.extract_lines_with_evidence()` phát sinh `FieldEvidence` (`table_id`, `cell_id`, `bbox`, `page_index`) cho từng trường của từng dòng hàng; `FieldEvidence` ORM + migration `002_field_evidence_table_cell_provenance` lưu hai cột mới; API `/invoices/{id}` trả về `table_id`/`cell_id` cho PDF Viewer. Bằng chứng trực quan: `benchmarks/scripts/render_bbox_evidence.py` render `case_06.pdf` với khung BBox đỏ vẽ đúng vị trí từng trường đã trích xuất (lưu tại `benchmarks/results/evidence/case_06_bbox_evidence.png`); dòng 2 cột `qty` bị merge **không có khung** — bằng chứng trực quan cho việc hệ thống từ chối bịa bbox cho dữ liệu không trích xuất được.

#### 6. OCR thực tế (Docling + RapidOCR, không chỉ test fallback)
Đo trực tiếp bằng `benchmarks/scripts/evaluate_ocr_quality.py` trên 4 chứng từ ảnh thuần (không text layer): PDF scan thường (`case_03`), PDF scan xoay 90° (`case_07`), PDF hỗn hợp digital+scan (`case_09`, mới thêm), PDF scan chứa bảng nhiều dòng hàng (`case_10`, mới thêm). Toàn bộ 4 case xác nhận chạy OCR RapidOCR thật (`used_fallback=False`, engine `onnxruntime`, log `[RapidOCR] Using engine_name: onnxruntime`), không rơi vào nhánh fallback do lỗi import.

| Case | CER | WER | Số tiền nhận dạng đủ? | Ghi chú |
|---|---|---|---|---|
| CASE-03 (scan thẳng) | 23.2% | 59.7% | Không (dòng tổng cộng bị OCR nhiễu thành ký tự rác) | Lỗi OCR cụ thể, không tương quan với góc xoay |
| CASE-07 (scan xoay 90°) | 7.3% | 31.5% | Có | Tốt hơn CASE-03 dù bị xoay |
| CASE-09 (trang scan đính kèm trong PDF hỗn hợp) | 1.9% | 5.6% | Có | |
| CASE-10 (bảng scan nhiều dòng) | — | — | 1 bảng được nhận diện, 2 dòng trích xuất, 1/2 đúng hoàn toàn | Dòng 2 bị cùng lỗi cell-merge như Mục 12.1, đúng đắn gắn cờ thay vì bịa |

**Phát hiện quan trọng:** RapidOCR (model mặc định `ch_PP-OCRv4`, gốc huấn luyện cho tiếng Trung/Anh) đọc đúng mọi ký tự ASCII và toàn bộ chữ số tiền, nhưng **không nhận diện được dấu thanh tiếng Việt** — ví dụ "Công ty" → "Cong ty", "Vệ sinh" → "Ve sinh" — vì bộ từ điển ký tự của model không chứa các glyph tiếng Việt có dấu. Đây là giới hạn của model OCR, không phải lỗi pipeline; cần model OCR có hỗ trợ tiếng Việt (hoặc fine-tune) nếu muốn khắc phục, nằm ngoài phạm vi 4 nhiệm vụ hiện tại.

**Một phát hiện hạ tầng quan trọng khác (đã sửa):** `benchmarks/fixtures/generate_documents.py` trước đây dùng font Base-14 `"helv"` của PyMuPDF để chèn text tiếng Việt — font này không có ToUnicode CMap đúng cho ký tự có dấu, khiến **ngay cả văn bản số (không qua OCR)** bị hỏng khi trích xuất lại (`"Máy tính"` → `"M�y t�nh"`), và ảnh scan render từ trang này cũng hiển thị glyph sai hình dạng. Đã sửa bằng cách nhúng font Unicode thật (`arial.ttf`) qua `page.insert_font(fontfile=...)`; đồng thời phát hiện và xử lý một tác dụng phụ của việc nhúng font: PyMuPDF âm thầm thay dấu gạch ngang ASCII bằng soft-hyphen (U+00AD) khi chèn qua font nhúng — đã thêm `text_normalization.py` để khôi phục lại dấu gạch ngang thật, vì mã SKU/số hóa đơn phụ thuộc vào ký tự này.

#### 7. Chi phí vận hành $0 / 1.000 hóa đơn ở chế độ tự chủ (không đổi)
Vẫn đúng như lần đo trước: **RapidOCR ONNX Runtime** chạy CPU kết hợp **Docling Canonical Pipeline** xử lý hoàn chỉnh cả PDF điện tử và scan xoay mà không phát sinh chi phí API LLM ($0.00/1.000 hóa đơn).
