# Operations, Security & Troubleshooting

> Checklist vận hành thực tế cho Windows/PowerShell (RAM 16 GB, CPU-only) và Docker Compose. Các file source/Compose/.env nêu ở đây là **mục tiêu cần tạo theo `IMPLEMENTATION.md`**, không ngụ ý đã có ứng dụng để chạy. Dev demo dùng dữ liệu synthetic. Không dùng production customer invoices với API/free tier nếu chưa có quyền và chính sách dữ liệu phù hợp.

## 1. Resource profiles và deployment topology

### Developer laptop (Windows 16 GB, không GPU)

- Docker Desktop + WSL2; PostgreSQL + Redis + objectstore chạy Docker, FastAPI/worker có thể chạy native trong PowerShell để debug CPU và path dễ hơn.
- Worker: **1 process/1–2 threads** khi parse/OCR CPU-heavy; không chạy đồng thời nhiều Docling + embedding/PaddleOCR; dùng giới hạn CPU/memory/timeout. Không preload mọi model nặng ở startup API.
- Docling/OCR CPU có thể tốn RAM; mở bằng feature flag/config, xử lý từng trang/chunk nếu hỗ trợ; fallback Gemini API cho trang quá khó có budget. Không tự khẳng định phần mềm phù hợp mọi PDF 1000 trang trên máy 16 GB.
- Volume object store, PostgreSQL, Redis bền vững; temp files có TTL, cleanup theo retention. Local `DATA_DIR` và `MODEL_CACHE_DIR` qua config, không hardcode `C:\...` hoặc `D:\...`.
- LLM key qua `.env` dev; production secret manager; không tạo key trong tài liệu hoặc prompt. Dùng **free tier chỉ cho dữ liệu synthetic** nếu điều khoản data-use cho phép.

### Staging/production nhỏ

- HTTPS reverse proxy → API (readiness, auth) + web; worker tách service, PostgreSQL managed nếu có, Redis broker, object storage private; egress allowlist chỉ provider được duyệt.
- DB migrations bằng job độc lập trước promote API, backward-compatible expand/contract. Không cho `alembic upgrade head` từ tất cả API replicas khi startup.
- API containers non-root, read-only filesystem, ephemeral `/tmp` bounded, no Docker socket, restricted Linux caps, network egress controls cho parser; worker concurrency theo measured RSS.
- Config: `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `OBJECT_STORE_ENDPOINT`, `BUCKET`, `JWT_ISSUER`, `JWT_AUDIENCE`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_CALLS_PER_JOB`, `LLM_MAX_COST_USD_PER_JOB`, `DOCUMENT_MAX_BYTES`, `DOCUMENT_MAX_PAGES`, `DOCUMENT_RENDER_MAX_PIXELS`, `WORKER_CONCURRENCY`, `MATCH_POLICY_ID`.
- **Không dùng `latest` image tags**; pin digest/semantic version phù hợp và ghi SBOM/license review. Định kỳ update dependency có regression.

## 2. End-to-end environment setup từng bước

### Prerequisite check

PowerShell (điều chỉnh phù hợp máy; không tải từ nguồn lạ):

```powershell
python --version            # mục tiêu 3.12 cho package đang chốt
node --version              # LTS còn được hỗ trợ
pnpm --version
uv --version
docker --version
docker compose version
git --version
```

**Kiểm trước:** đủ disk (Docling image/model cache có thể nhiều GB), Docker Desktop/WSL2 chạy ổn, ports không bị chiếm, network truy cập provider nếu chọn API. Nếu không có Docker, có thể chạy Postgres/Redis với môi trường thay thế nhưng runbook này dùng Docker làm đường chuẩn.

### Dependency installation policy

`pyproject.toml` của ứng dụng cần định nghĩa `dependency-groups.dev` và optional extras `documents` (Docling + PyMuPDF), `gemini` (Google SDK), `ocr` (fallback nặng, optional), `benchmark` (scoring). **Không** dùng `--all-extras` mặc định trên máy 16 GB; điều này có thể tải các engine OCR/GPU không cần thiết. Nếu chỉ thử XML flow, `uv sync --group dev` là đủ. Cấu hình và lockfile phải được tạo/kiểm chứng khi coding.

### Bootstrap sau khi coding agent tạo repository

```powershell
# Tại project root
Copy-Item .env.example .env
# Chỉnh các secret local: không commit .env
uv sync --group dev --extra documents --extra gemini
pnpm --dir apps/web install --frozen-lockfile

docker compose config
# Hạ tầng (service names phải khớp compose file được implement)
docker compose up -d postgres redis objectstore

docker compose ps
docker compose logs --tail 100 postgres redis objectstore
uv run alembic upgrade head
python scripts/preflight.py
python scripts/seed_demo.py
python scripts/run_all_checks.py
```

Kiểm: DB connect, migration history sạch, MinIO bucket policy private, Redis ping, provider key/quota optional, migrations idempotent ở môi trường dev. `seed_demo` tạo data synthetic deterministic, tránh đổi bất ngờ trạng thái mỗi lần chạy; có `--reset` riêng chỉ dùng dev có confirm.

### Chạy API/worker/web ở 3 terminal (dev)

```powershell
# T1
uv run uvicorn invoiceflow.api.main:app --reload --host 127.0.0.1 --port 8000

# T2
uv run dramatiq invoiceflow.workers.actors --processes 1 --threads 2

# T3
pnpm --dir apps/web dev
```

Kiểm `http://localhost:8000/docs`, `http://localhost:8000/health/live`, `http://localhost:8000/health/ready`, web dev URL từ Vite. Trường hợp auth token/CSRF/cookie tùy cách triển khai phải đúng CORS và secure flags.

### Khởi chạy qua Compose (mục tiêu sau sprint 7)

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f --tail=100 api worker
```

Không tuyên bố `docker compose up` là production deployment đầy đủ; production cần HTTPS, secrets, backups, monitoring và rate limits. **Cấm xử lý lỗi DB bằng `docker compose down -v`** vì xóa volumes dữ liệu.

## 3. Runbook kiểm tra E2E bằng dữ liệu không nhạy cảm

1. Seed demo workspace: 1 tenant, reviewer, accountant, 3 vendors, 3 PO, 4 GRN (có split delivery), 6 invoices XML/PDF/scan (trong fixtures được tạo và cấp phép).
2. Login, upload XML sample → `202`, lấy `job_id`; poll cho tới `READY_FOR_REVIEW`, xác nhận **0 LLM calls**.
3. Upload digital PDF → Docling parse; click field `amount_payable` highlight đúng bbox; kiểm line items giữ hàng/cột.
4. Upload scan with missing value → review issue; không tự approved; xem raw source và lý do.
5. Đối soát 2-way/3-way: một pass, một `PRICE_VARIANCE`, một `QUANTITY_VARIANCE` với partial receipts.
6. Reviewer sửa giá trị trên revision mới → audit chứa old/new/reason; reviewer khác submit stale version → `409`.
7. Approve hợp lệ → export CSV/JSON/XLSX; verify checksum, account links, decimal formatting, tenant isolation.
8. Tắt worker lúc đang xử lý, bật lại → job resumed/reconciled hoặc permanent failure có thông báo; không tạo invoice duplicated.
9. Test provider 429/timeout bằng stub, verify retry bounded, state `WAITING_PROVIDER/RETRY_WAIT` hoặc actionable error.
10. Chạy suite CI/evaluation trên same frozen input, xuất artifacts; không dùng demo 6 docs để chứng minh accuracy trên tổng thể.

## 4. Bảng xử lý lỗi theo triệu chứng (actionable)

| Symptom / mã | Nguyên nhân có thể | Kiểm tra trước | Hành động đúng | Trạng thái / anti-pattern |
|---|---|---|---|---|
| 413 `FILE_TOO_LARGE` | file quá size policy | config + Content-Length + bytes streamed | reject, hướng dẫn chia file hợp lệ | **không** tăng limit vô hạn |
| 415 `UNSUPPORTED_MEDIA` | MIME spoof/extension lạ | magic bytes/decoder | reject, ghi audit; chỉ allowlist | **không** tin client MIME |
| 422 `CORRUPT_PDF` | PDF hỏng/truncated/encrypted | parser error/classification, password | mark permanent/needs-password; upload lại | không gửi lặp LLM |
| `XML_UNSAFE` | DTD/XXE/schema remote | DTD/external resolver logs sanitized | reject before parsing, security event | không bật `resolve_entities=True` |
| `XML_SCHEMA_UNKNOWN` | namespace/format mới | mapping/XSD version, source | add schema adapter with fixtures/ADR | không sửa XPath hardcode cho một mẫu |
| `PDF_NO_TEXT` | PDF scan/ảnh | per-page text density | route OCR; bounded memory | không trả empty thành success |
| `TABLE_STRUCTURE_ERROR` | bảng gộp/multi-page | CDR cells/bbox and rendered crop | targeted Vision fallback or review; collect case | không bịa line items |
| `LLM_RATE_LIMIT` 429 | quota/requests | retry-after, provider quota, logs | bounded retry+jitter; global token bucket | không infinite retry/key rotation |
| `LLM_TIMEOUT` | provider latency/upload | timeout; request ID | status retry with budget, avoid duplicate billing; operator replay when uncertain | không 200 false success |
| `LLM_SCHEMA_INVALID` | non-JSON/schema deviation | raw response hashed securely; version | strict parse; single bounded repair if policy allows, else review | không regex hack JSON tùy tiện |
| `PROVIDER_AUTH_FAILURE` 401/403 | key revoked/permission | env/secret store/provider access | stop retry, alert admin, rotate key | không log key |
| `OBJECT_NOT_FOUND` | object metadata/storage inconsistency | key/version/checksum, storage health | quarantine job, reconcile uploads | không reconstruct empty file |
| `DB_UNAVAILABLE` | Postgres down/connection pool | `/health/ready`, logs, pool, disk | restore DB; reconcile pending outbox | không xóa DB volumes |
| `REDIS_UNAVAILABLE` | broker down | queue health and outbox backlog | persist outbox; dispatcher retry; alert | không publish trước DB commit |
| `WORKER_STUCK` | CPU/memory/parser hang | heartbeat, stage duration, RSS | timeout/kill sandbox, release lease, classify stage | không restart vô hạn |
| `DUPLICATE_HASH` | cùng bytes upload lại | checksum + tenant + idempotency | same response/no-op or explicit duplicate policy | không tự xóa record khác tenant |
| `DUPLICATE_INVOICE` | same supplier+number+series | legal entity + business fields | flag review, link originals | không assume hash equality |
| `MONEY_MISMATCH` | rounding/discount/tax | raw evidence, policy/currency units | mark issue, manual review | không tự ép số tổng khớp |
| `PO_NOT_FOUND` | thiếu PO hoặc non-PO | import/foreign ref | `MISSING_REFERENCE` hoặc `NON_PO` | không tự coi hóa đơn gian lận |
| `GRN_QUANTITY_VARIANCE` | nhận thiếu/nhiều đợt | GRN linked qty, returns | compute sum with policy; review | không lấy last GRN duy nhất |
| 409 `STALE_REVISION` | concurrent edit | ETag/revision | reload/diff; apply user edits consciously | không force overwrite |
| 403 `PERMISSION_DENIED` | role/tenant mismatch | user scope, tenant audit | reject; security review if suspicious | không disable RBAC để demo |
| `EXPORT_NOT_APPROVED` | invoice pending | aggregate current revision status | block until approval | không auto approve |
| `EXPORT_DUPLICATE` | repeated queue message | idempotency ledger, output hash | return existing artifact | không emit second webhook |
| `STORAGE_FULL` | disk, large cache/retention | disk usage, volume; temp | stop ingestion, cleanup approved temp, expand disk | không xóa raw audit mà chưa có policy |
| `HIGH_COST_PER_DOC` | repeated fallback/pages | token counts, page routing, cache | tighten budgets, crop/route, evaluate on validation | không bỏ quality kiểm chứng |

**Mọi incident** phải có `request_id`, `job_id`, tenant ID được hash/masked trong logs, stage, exception class và retryability; log message có redaction. Có thể nêu file name đã sanitize, không nêu raw nội dung hóa đơn.

### Decision tree lỗi nhanh

```text
Request failed?
  -> authentication/authorization? return 401/403, no side effects
  -> malformed/unsupported input? 4xx permanent, safe diagnostics
  -> dependency unavailable? 503 + retryable indicator; DB/outbox remains authoritative
  -> provider transient? bounded delayed retry (budget) and observation
  -> parser crash? sandbox timeout, quarantine/review; no repeated endless parse
  -> business mismatch? REVIEW_REQUIRED, never auto-repair financial values
  -> stale data? 409 revision conflict, reload and deliberate re-approve
  -> unknown? mark FAILED with incident ID; retain input + evidence, operator triage
```

## 5. Security baseline / threat model

| Threat | Impact | Control cần implement và test |
|---|---|---|
| malicious PDF/scan exploiting parser | remote code/memory exhaustion | pinned deps, non-root isolated worker, no outbound access, max pages/CPU/RAM/time, quarantine, scan |
| XML XXE/XInclude/schema SSRF | server file exfiltration | disable DOCTYPE/entities/XInclude/network, no remote schema, hostile XML tests |
| unauthorized IDOR/download | khách xem chứng từ khác | tenant scoping + RBAC at query and signed URL, TTL, audit |
| prompt injection embedded PDF | LLM đổi nhiệm vụ/phản hồi sai | role separation, treat source as data; constrained output + validation, no tools with side effects |
| PII disclosure to AI provider | legal/privacy risk | terms/consent/data-classification, redaction where possible, provider policy, secure transit, no free tier for real confidential docs |
| fake supplier/payee, fraudulent invoice | financial loss | no auto bank transfer, trusted vendor master, PO/GRN match, human approval |
| CSV formula injection | code/data execution on Excel | neutralize leading `=`, `+`, `-`, `@` safely, CSV export tests |
| duplicate retries | duplicate export/webhook/write | DB idempotency + outbox + uniqueness + external idempotency/verification |
| credentials/DB leak | broad data exposure | secret manager, scoped IAM, short-lived tokens, rotation, encryption, logging redaction |
| backup loss/ransomware | data loss | encrypted backups, restore drills, least privilege, retention + access logging |

**Retentions:** define organization-specific retention policies before real customers; do not claim default number of years is a legal requirement unless validated. Right to delete must reconcile with legal retention; maintain immutable audit with access controls, avoid raw data in metrics. Use privacy-safe synthetic examples in GitHub/docs/demo.

## 6. Monitoring, alerting, incident response

### Metrics & dimensions

- API rate and response latency; upload `4xx/5xx` ratio; active tenants without leaking IDs.
- Queue depth, oldest queued age, processing success/failure, retries and dead-letter counts.
- Parser throughput, per-page time, worker memory/CPU, timeout counts by document format.
- LLM `429/timeout/schema_invalid`, tokens and cost per successful/failed document, provider compatibility failures.
- Review backlog age, false-safe-approval incidents, duplicate issues, mismatched PO/GRN counts, export failures.
- Security: 403/IDOR probing, XML unsafe rejects, parsing sandbox alerts, secret scanning CI.

### Tracing

`trace_id` links HTTP upload → `document_id` → outbox → `job_id` → parser attempt → provider call → validation/reconciliation → approval → export. Raw document text **không** vào spans, error bodies, APM logs. Use RED (rate-errors-duration) and stage metrics; sampling có policy, no PII.

### Alert / response

- P0: data leak, unauthorized approval/export, corrupted/duplicate business effect → disable writes/exports, preserve audit, notify operator, reconcile affected records.
- P1: queue oldest age above threshold, repeatedly failing workers, provider quota denial → pause inference, allow deterministic XML path, replay after dependencies fixed.
- P2: latency/cost budget exceeded → capacity/routing tuning after measurement; don't compromise correctness silently.

## 7. Backup, restore, migration, rollback

- Daily scheduled PostgreSQL backups (frequency determined by RPO/RTO), encrypted storage separate from live host, retention and restore test; objectstore versioning/backup and cross-check DB refs.
- Restore drill: new isolated environment → restore DB + files → check SHA, schema migration compatibility, document counts, approved revision consistency → E2E synthetic canary.
- Deploy immutable image digest; lock dependencies; staging migration smoke; use expand/contract migrations, background backfill when needed.
- On incident: stop new writes, drain workers or pause jobs, rollback app image **only if compatible with DB schema**; if migration destructive, use tested restore not guess.
- Do not erase migrations or existing production tables to unblock tests. No destructive SQL without approved backup plan.

## 8. Privacy, license, law awareness

- VN electronic-invoice rule references current as of 08/11/2026 include **Nghị định 254/2026/NĐ-CP** and **Thông tư 91/2026/TT-BTC** effective 01/07/2026 (official sources in `REFERENCES.md`). Implementation must consult actual XSD, authoritative schema/verification APIs, special invoice categories and expert compliance review; **không đưa nội dung văn bản vào Python if-else bằng hardcode**.
- Các endpoint “verify tax authority” hay “verify digital signature” chỉ bật nếu integration thực tế, trust store/CA và evidence có thể kiểm; parse XML thành công chưa xác nhận hóa đơn được nhà nước chấp nhận.
- Không gửi hóa đơn thật lên LLM provider nếu chưa đánh giá data processing terms, retention, nơi lưu trữ, bảo mật và quyền của doanh nghiệp.
- Ứng dụng portfolio mang tính trình diễn, **không phải dịch vụ tư vấn pháp lý/thuế**.

## 9. Release checklist (go/no-go)

- [ ] Security: RBAC/tenancy/auth, XXE, upload, malicious PDF sandbox, no secrets/PII leaks.
- [ ] Correctness: Decimal, duplicates, XML/PDF mismatches, line-item structure, PO/GRN exceptions, stale review.
- [ ] Reliability: job status durable, outbox, bounded retries, DLQ/alert, idempotent export, restart recovery.
- [ ] Product: 8 user journeys pass on synthetic fixtures, UI errors display meaningful feedback, links and exports permission-scoped.
- [ ] Quality: frozen benchmark + per-case evidence, separate synthetic international/VN and parser vs invoice/business metrics.
- [ ] Deployment: pinned images, migration & backup/restore verified, health/readiness, tracing and alerting.
- [ ] Docs: `AGENTS.md` enforced, updated in place, attribution/license and truthful README/CV claims.

**Nếu một mục an toàn nghiêm trọng chưa đạt → NO-GO.** Không dùng từ “production-ready” chỉ nhờ Compose chạy và hình demo đẹp.
