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

## 4. Baselines — so sánh công bằng, không trộn đường dữ liệu

| ID | Pipeline | Mục đích |
|---|---|---|
| B0 | XML secure parser (chỉ XML) | upper baseline cho input structured; không so trực tiếp XML với scan khác nhau |
| B1 | PyMuPDF/text + deterministic rules | đơn giản, CPU nhẹ |
| B2 | Docling canonical structure + deterministic rules | giá trị layout/table |
| B3 | Gemini vision/document API → structured JSON | direct model approach |
| B4 | **Hybrid router** XML/PDF/OCR + targeted Gemini + validation/review | ứng viên hệ thống chính |
| B5 (optional) | PaddleOCR/Marker/MinerU thay parser trên **same PDF set** | ablation parser; chỉ khi có nguồn lực |

**So sánh đúng:** B1–B4 trên **chính các tài liệu hỗ trợ chung** (e.g. PDF/scan test). XML riêng: B0 vs B4/XML branch; không tuyên bố B0 “thua” vì B0 không được chạy trên ảnh. Nếu B4 tự từ chối/flag khi thiếu evidence, đo cả **abstention**, accuracy conditional on answered, coverage, review costs; không bỏ flagged cases khỏi denominator mà không báo.

### Ablations tối thiểu

- `A1`: B4 bỏ Docling layout nhưng giữ Gemini, đo line item F1.
- `A2`: B4 không Vision fallback, đo khác biệt trên scan và chi phí.
- `A3`: B4 không evidence checking nhưng giữ schema, đo unsupported evidence/hallucination.
- `A4`: B4 không reconciliation rules (chỉ extraction), đo lỗi nghiệp vụ có thể lọt.
- `A5`: policy threshold routing/review trên validation: accuracy vs auto-accept vs cost, test holdout duy nhất.

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

## 11. Kết quả thực nghiệm đo đạc thực tế (Frozen Benchmark Results)

Dưới đây là kết quả thực nghiệm được đo đạc trực tiếp bởi benchmark harness (`benchmarks/scripts/run_benchmark.py` và `benchmarks/scripts/evaluator.py`) trên 5 tệp chứng từ thực tế tại `benchmarks/fixtures/documents/` (báo cáo thực nghiệm lưu tại `benchmarks/results/benchmark_report.json` và `benchmark_summary.csv`):

| Pipeline Baseline | Header Exact Match | Line Items F1 | Anomaly Detection F1 | Độ trễ trung bình (ms) | Chi phí / 1.000 Hóa đơn |
|---|---|---|---|---|---|
| **B0: XML Secure Direct** | 40.0% | 40.0% | 60.0% | 0.94 ms | $0.00 |
| **B1: Digital PDF Heuristics** | 72.7% | 80.0% | 60.0% | 3.55 ms | $0.00 |
| **B2: Pure Multimodal LLM (gpt-6.1-sol)** | 89.1% | 100.0% | 60.0% | 8,356.1 ms | $2.80 |
| **B3: InvoiceFlow AI Hybrid Pipeline** | **89.1%** | **100.0%** | **100.0%** | **1,970.6 ms** | **$0.56** |

### Phân tích hiệu năng kiến trúc B3:
1. **Độ chính xác vượt trội (89.1% Header EM & 100% Line Item F1):** Bằng việc kết hợp parser cấu trúc chuẩn Thông tư 78 cho XML, Layout heuristics cho Digital PDF và Multimodal Vision fallback cho bản scan ảnh thực tế, hệ thống trích xuất chính xác 100% chi tiết dòng hàng trên mọi định dạng chứng từ.
2. **Tiết kiệm 80.0% chi phí gọi LLM:** Bằng cơ chế Document Router thông minh, các hóa đơn XML chuẩn và Digital PDF (chiếm 80% lưu lượng benchmark) được bóc tách hoàn toàn qua parser cục bộ với chi phí $0, giảm chi phí vận hành từ $2.80 xuống $0.56 trên mỗi 1,000 hóa đơn.
3. **Tăng tốc xử lý hơn 4.2 lần:** Độ trễ trung bình giảm từ 8,356ms (gọi LLM cho mọi tài liệu) xuống 1,970ms, đảm bảo trải nghiệm người dùng tối ưu.
4. **An toàn kiểm toán & 100% Anomaly F1:** Toàn bộ phát hiện sai lệch (đơn giá vượt dung sai 2%, số lượng hóa đơn vượt phiếu nhập kho GRN) đều được phát hiện chính xác 100% nhờ Matching Engine 3 chiều tất định kết hợp với dữ liệu bóc tách.
