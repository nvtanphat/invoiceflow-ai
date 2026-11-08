# References & reuse policy — Nguồn đã đối chiếu

> Kiểm tra vào 08/11/2026. Nguồn dùng để **thiết kế và benchmark**, không phải minh chứng các tính năng đã triển khai. Không sao chép toàn repo rồi gọi là tự xây; nếu reuse code phải kiểm tra license tại commit/tag cụ thể, giữ attribution và nêu đóng góp riêng.

## 1. Open-source source implementations

| Repository | Vai trò tham khảo | Điều nên học / không bê nguyên |
|---|---|---|
| [Docling](https://github.com/docling-project/docling) + [DoclingDocument](https://github.com/docling-project/docling/blob/main/docs/concepts/docling_document.md) | parser primary; structured elements, tables, hierarchy, reading order, bbox | chuyển `DoclingDocument` sang canonical schema, benchmark trên invoice, không lấy Markdown-only output |
| [Docling Serve](https://github.com/docling-project/docling-serve) | reference triển khai document parser API | ranh giới process parser; không bắt buộc tách thành service P0 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | alternative OCR/layout/table | chạy **ablation** khi scan khó, không enable mọi backend đồng thời |
| [MinerU](https://github.com/opendatalab/MinerU) | layout/table PDF alternate | chỉ prototype comparator; kiểm tra requirements & license riêng ở tag dùng |
| [Marker](https://github.com/datalab-to/marker) | alternative PDF-to-Markdown/JSON | đọc hạn chế output/trade-offs, không dùng làm thước đo invoice field accuracy |
| [olmOCR](https://github.com/allenai/olmocr) | VLM document OCR research | hardware/pipeline phù hợp benchmark khi có GPU; không là P0 CPU-only |
| [Google LangExtract](https://github.com/google/langextract) | evidence-grounded structured extraction | học extraction/citation contract; không thay business rules |
| [Invoice OCR & Extraction System](https://github.com/GabrielHuertasdl/invoice-ocr-system) | full-stack FastAPI/React, OCR, validation | tham khảo UX/API, baseline deterministic, không giữ SQLite/regex như kiến trúc production cuối |
| [Document Processing Platform](https://github.com/SyedAliZafar/document-processing-platform) | review panel + structured extraction | nghiên cứu review and validation; **chưa xác nhận license** trong audit này, không reuse code khi chưa có phép |

**Ghi nhận license đã kiểm tra ở GitHub:** Docling MIT, Docling Serve MIT, PaddleOCR Apache-2.0; tham khảo các repo khác phải kiểm tra riêng file `LICENSE`, model weight licenses, data licenses và phụ thuộc tại revision cụ thể. License mã nguồn **không tự cấp quyền** tái sử dụng dataset hoặc pretrained weights.

## 2. Benchmark/dataset nguồn

| Nguồn | Benchmark chính xác | License/cảnh báo |
|---|---|---|
| [Invoice Extraction Benchmark — 181 synthetic documents](https://github.com/DrewKraken/invoice-extraction-benchmark) | invoice header/lines/exceptions theo scorer kèm repo | tạo bởi InvoiceParser Pro (vendor), không độc lập; code MIT, corpus/examples CC BY 4.0 |
| [DocILE](https://github.com/rossumai/docile) | official KILE (localization/extraction) và LIR (line-item grouping) | dùng official evaluation, phải tuân thủ điều khoản tải dữ liệu; code repo MIT |
| [OmniDocBench](https://github.com/opendatalab/OmniDocBench) | document parsing benchmark | chỉ dùng khi nghiên cứu parser, không lẫn thành AP benchmark |
| Synthetic VN AP Casebook | business XML/PDF/PO/GRN do nhóm tự tạo có GT | minh bạch: không có ý nghĩa thống kê về tất cả hóa đơn Việt Nam |

**Không được:** công bố điểm trên DocILE từ extractor chỉ có string và không có bbox; so sánh một model trên 181 tài liệu với model khác trên 20 tài liệu; sửa scorer để pass; gộp các điểm khác định nghĩa.

## 3. API / framework / chính sách an toàn

- [Gemini — Document Understanding](https://ai.google.dev/gemini-api/docs/document-processing): PDF, structured information, native vision. Kiểm request and model capability trước khi implement.
- [Gemini — Pricing](https://ai.google.dev/gemini-api/docs/pricing): giá thay đổi; xác thực tier và điều khoản dữ liệu khi chạy, không hardcode giá cũ vào sản phẩm.
- [Gemini — Interactions API migration](https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026): interface trả dữ liệu có cấu trúc thay đổi ở API; pin SDK và conformance tests, đừng trộn API shapes không tương thích.
- [Docling — Pipeline Options](https://docling-project.github.io/docling/reference/pipeline_options/): config OCR, tables và parsing; pin versions theo benchmark.
- [PyMuPDF docs](https://pymupdf.readthedocs.io/en/latest/): PDF inspection, text blocks, page coordinates.
- [Dramatiq Guide](https://dramatiq.io/guide.html): retry/backoff; default retries không thay thế idempotency/app state.
- [SQLAlchemy 2](https://docs.sqlalchemy.org/en/20/): DB session/transaction boundaries.
- [Pydantic v2](https://docs.pydantic.dev/latest/): validation/schemas; `extra='forbid'` cho contracts quan trọng.
- [OWASP File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html): allowlist, MIME detection, limits, storage isolation.
- [OWASP XXE Prevention](https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html): DTD, external entities, XInclude, schema/network controls.
- [Microsoft Dynamics — Accounts payable invoice matching](https://learn.microsoft.com/en-us/dynamics365/finance/accounts-payable/accounts-payable-invoice-matching): two-way/three-way + configurable tolerances, partial receipts; đây là **quy trình tham khảo**, không áp mặc định quy định của Dynamics cho mọi doanh nghiệp.

## 4. Nguồn pháp lý chính thức Việt Nam (cần đối chiếu khi code)

- [Nghị định 254/2026/NĐ-CP](https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-254-2026-nd-cp-469957/66826.htm), ban hành 30/06/2026, hiệu lực 01/07/2026.
- [Thông tư 91/2026/TT-BTC](https://congbao.chinhphu.vn/van-ban/thong-tu-so-91-2026-tt-btc-470171/67424.htm), ban hành 30/06/2026, hiệu lực 01/07/2026.
- [Toàn văn Nghị định và nội dung hóa đơn](https://xaydungchinhsach.chinhphu.vn/toan-van-nghi-dinh-so-254-2026-nd-cp-ve-hoa-don-dien-tu-chung-tu-dien-tu-119260713164251972.htm).

**Giới hạn:** văn bản quy định không tương đương API xác thực hóa đơn hoặc bộ XSD ký số. XML parser cần schema implementation chính thức theo dạng hóa đơn cần hỗ trợ; hoàn thành parser không đồng nghĩa đáp ứng đầy đủ luật. Mọi nhận định thuế, thuế suất, ngoại lệ hóa đơn phải được chuyên gia nghiệp vụ kiểm tra trước khi cho doanh nghiệp dùng.

## 5. Quản lý nguồn và giấy phép khi rebuild repo

1. Chọn repo, pin Git SHA/tag, đọc README/architecture/tests/CI, LICENSE và dependency/data/model licenses; ghi phần dùng để học và phần code reuse.
2. Viết `NOTICE`/attribution ở repo ứng dụng khi license yêu cầu. Không copy code chưa được cấp phép hoặc clone private repo không có quyền.
3. Dùng thiết kế boundary từ `ARCHITECTURE.md`, không chồng framework từ nhiều repo mà không có benchmark.
4. Benchmark trên cùng frozen data, ghi own commits và contribution; chỉ CV những chức năng và metric thực tế do mình tạo/đo.
5. Khi lựa chọn kỹ thuật mới tốt hơn, ghi trade-off trong `ARCHITECTURE.md`, giữ experiment artifacts và dọn implementation obsolete ở active code.

## 6. Agent Skills & Tooling (Quy chuẩn và kỹ năng coding agent)

| Nguồn / Repository | Giấy phép | Danh mục kỹ năng | Vai trò trong dự án |
|---|---|---|---|
| [obra/superpowers](https://github.com/obra/superpowers) | MIT | `brainstorming`, `writing-plans`, `executing-plans`, `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `requesting-code-review`, `using-git-worktrees`, `subagent-driven-development`, `receiving-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `writing-skills`, `using-superpowers`, `diagnosing-superpowers` | Quy trình kỹ thuật công nghệ phần mềm: TDD, lập kế hoạch, debug nguyên nhân gốc, rà soát code và an toàn commit |
| [anthropics/skills](https://github.com/anthropics/skills) | Apache-2.0 | `pdf`, `xlsx`, `docx`, `webapp-testing`, `frontend-design`, `web-artifacts-builder`, `doc-coauthoring`, `mcp-builder`, `skill-creator`, `claude-api`, `canvas-design`, v.v. | Thao tác tài liệu PDF (trích xuất, OCR), xuất file Excel/Word, kiểm thử E2E giao diện với Playwright |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | MIT | `react-best-practices`, `composition-patterns`, `web-design-guidelines`, `writing-guidelines`, `deploy-to-vercel`, v.v. | Chuẩn mực lập trình React/Vite/TypeScript, mẫu composition, tiêu chuẩn UX/Web interface |
| [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | Apache-2.0 | `invoice-organizer`, v.v. | Tham khảo quy trình tổ chức, phân loại hóa đơn đầu vào AP |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | Apache-2.0 | Đặc tả chuẩn mở Agent Skills (`SKILL.md`, YAML frontmatter, Progressive Disclosure) | Chuẩn đặc tả kỹ thuật đảm bảo tính tương thích giữa Antigravity, Claude, Codex và các agent khác |
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | MIT | Danh mục sinh thái Agent Skills | Nguồn tra cứu các kỹ năng mở rộng |

