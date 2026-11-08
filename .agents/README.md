# Antigravity Workspace Skills — InvoiceFlow AI

Thư mục này chứa toàn bộ các **Workspace Skills** được tích hợp cho dự án **InvoiceFlow AI**, tuân thủ đặc tả chuẩn mở của [Agent Skills](https://github.com/agentskills/agentskills) và hệ thống tùy biến của **Google Antigravity (`agy`)**.

## 1. Cơ chế hoạt động (Progressive Disclosure)

Mỗi skill được đóng gói trong một thư mục riêng biệt với file chỉ dẫn `SKILL.md` có YAML frontmatter:
```text
.agents/skills/<skill_name>/
├── SKILL.md          # Bắt buộc: metadata (name, description) + hướng dẫn
├── references/       # Tài liệu chi tiết kèm theo (đọc khi cần)
└── scripts/          # Script thực thi hỗ trợ
```

Khi Antigravity khởi động trong workspace, chỉ `name` và `description` của các skills được nạp vào context window index. Nội dung chi tiết chỉ được nạp theo cơ chế **Progressive Disclosure** khi agent hoặc người dùng kích hoạt skill đó, giúp tiết kiệm tối đa token context mà vẫn đảm bảo năng lực thực thi chuyên sâu.

---

## 2. Danh mục 44 Skills đã cài đặt

### A. Quy trình Kỹ nghệ Phần mềm Chuẩn mực (Software Engineering Workflow)
*Nguồn: [obra/superpowers](https://github.com/obra/superpowers) — Giấy phép: MIT (Copyright (c) 2025 Jesse Vincent)*

| Skill | Vai trò & Thời điểm kích hoạt | Phù hợp AGENTS.md |
|---|---|---|
| [`brainstorming`](skills/brainstorming/SKILL.md) | Làm rõ yêu cầu, ranh giới và thiết kế trước khi bắt tay vào code | Mục 1 (Inspect & Plan) |
| [`writing-plans`](skills/writing-plans/SKILL.md) | Lập kế hoạch chi tiết từng bước, có acceptance criteria | Mục 1 (Plan) & Mục 9 (DoD) |
| [`executing-plans`](skills/executing-plans/SKILL.md) | Điều phối thực thi kế hoạch theo từng giai đoạn chặt chẽ | Mục 1 (Implement) |
| [`test-driven-development`](skills/test-driven-development/SKILL.md) | Viết test thất bại trước, cài đặt tối thiểu, refactor an toàn | Mục 6 (Kiểm thử) |
| [`systematic-debugging`](skills/systematic-debugging/SKILL.md) | Truy vết nguyên nhân gốc 4 bước, không đoán mò hay sửa bừa | Mục 5 (Sửa lỗi) |
| [`verification-before-completion`](skills/verification-before-completion/SKILL.md) | Kiểm chứng bằng chứng thực tế trước khi tuyên bố hoàn thành | Mục 9 (Definition of Done) |
| [`requesting-code-review`](skills/requesting-code-review/SKILL.md) | Yêu cầu rà soát code độc lập, kiểm tra regression | Mục 8 & 9 (Review) |
| [`receiving-code-review`](skills/receiving-code-review/SKILL.md) | Tiếp nhận phản hồi review và giải quyết có hệ thống | Mục 5 & 8 |
| [`using-git-worktrees`](skills/using-git-worktrees/SKILL.md) | Cách ly không gian làm việc an toàn với Git worktree | Mục 4 & 8 (Git hygiene) |
| [`finishing-a-development-branch`](skills/finishing-a-development-branch/SKILL.md) | Hoàn tất nhánh làm việc, kiểm tra clean tree trước khi merge | Mục 8 (Git hygiene) |
| [`subagent-driven-development`](skills/subagent-driven-development/SKILL.md) | Điều phối subagents độc lập giải quyết từng task | Mục 3 (Module boundaries) |
| [`dispatching-parallel-agents`](skills/dispatching-parallel-agents/SKILL.md) | Chạy nhiều subagents song song để giải quyết tác vụ độc lập | Tối ưu tiến độ |
| [`using-superpowers`](skills/using-superpowers/SKILL.md) | Thiết lập nguyên tắc tìm và áp dụng skill trong phiên làm việc | Toàn bộ quy trình |
| [`diagnosing-superpowers`](skills/diagnosing-superpowers/SKILL.md) | Chẩn đoán và phân tích phiên làm việc của agent | Audit & cải tiến |
| [`writing-skills`](skills/writing-skills/SKILL.md) | Hướng dẫn tạo skill mới chuẩn format | Mở rộng skill nội bộ |

---

### B. Xử lý Tài liệu, Hóa đơn & Báo cáo (Document & AP Pipeline)
*Nguồn: [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0) & [Composio](https://github.com/ComposioHQ/awesome-claude-skills) (Apache-2.0)*

| Skill | Mục đích sử dụng | Ứng dụng trong InvoiceFlow AI |
|---|---|---|
| [`pdf`](skills/pdf/SKILL.md) | Trích xuất text, bảng, tọa độ trang, xoay, tách trang, OCR | Tiền xử lý và ingest hóa đơn PDF đầu vào |
| [`xlsx`](skills/xlsx/SKILL.md) | Đọc, tính toán, kiểm tra và xuất bảng tính Excel | Xuất dữ liệu đối soát PO/GRN, báo cáo kế toán AP |
| [`docx`](skills/docx/SKILL.md) | Đọc, tạo và thao tác tài liệu Word | Biên soạn báo cáo đối soát và hồ sơ chứng từ |
| [`invoice-organizer`](skills/invoice-organizer/SKILL.md) | Tổ chức, phân loại hóa đơn đầu vào theo nhà cung cấp/kỳ thuế | Tổ chức dữ liệu hóa đơn AP có cấu trúc |

---

### C. Phát triển Giao diện & Frontend (React/TypeScript & UI Testing)
*Nguồn: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) (MIT) & [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0)*

| Skill | Mục đích sử dụng | Ứng dụng trong InvoiceFlow AI |
|---|---|---|
| [`react-best-practices`](skills/react-best-practices/SKILL.md) | 70 quy tắc tối ưu hiệu năng React/Vite/TypeScript | Xây dựng UI review và reconciliation panel mượt mà |
| [`composition-patterns`](skills/composition-patterns/SKILL.md) | Mẫu thiết kế component React có khả năng mở rộng | Thiết kế component hiển thị PDF + review bounding box |
| [`web-design-guidelines`](skills/web-design-guidelines/SKILL.md) | Kiểm tra UI theo tiêu chuẩn Web Interface & Accessibility | Đảm bảo tính khả dụng và UX chuyên nghiệp cho kế toán |
| [`frontend-design`](skills/frontend-design/SKILL.md) | Hướng dẫn phong cách giao diện chất lượng cao | Tránh giao diện nghiệp dư, đồng bộ visual design |
| [`webapp-testing`](skills/webapp-testing/SKILL.md) | Kiểm thử tự động giao diện web với Playwright | Chạy smoke test và E2E test cho luồng upload & review |
| [`web-artifacts-builder`](skills/web-artifacts-builder/SKILL.md) | Tạo nguyên mẫu giao diện và components tương tác | Thử nghiệm nhanh các thành phần UX phức tạp |

---

### D. Tiện ích Mở rộng & Tích hợp (Extensibility & Documentation)
*Nguồn: [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0) & [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) (MIT)*

| Skill | Mục đích sử dụng |
|---|---|
| [`mcp-builder`](skills/mcp-builder/SKILL.md) | Xây dựng Model Context Protocol (MCP) servers |
| [`skill-creator`](skills/skill-creator/SKILL.md) | Khởi tạo và kiểm tra skill mới |
| [`doc-coauthoring`](skills/doc-coauthoring/SKILL.md) | Đồng biên soạn tài liệu kỹ thuật có cấu trúc |
| [`writing-guidelines`](skills/writing-guidelines/SKILL.md) | Tiêu chuẩn văn phong kỹ thuật rõ ràng, chính xác |
| [`claude-api`](skills/claude-api/SKILL.md) | Mẫu tích hợp API |
| [`deploy-to-vercel`](skills/deploy-to-vercel/SKILL.md) | Hướng dẫn triển khai demo frontend |
| [`brand-guidelines`](skills/brand-guidelines/SKILL.md), [`theme-factory`](skills/theme-factory/SKILL.md) | Thiết kế thương hiệu và hệ thống theme |
| [`internal-comms`](skills/internal-comms/SKILL.md), [`discernment-nudge`](skills/discernment-nudge/SKILL.md) | Truyền thông kỹ thuật và quy trình ra quyết định |

---

## 3. Cách Sử Dụng Trong Antigravity

1. **Tự động kích hoạt (Context-Aware):**
   Khi người dùng đưa ra yêu cầu (ví dụ: *"hãy viết test cho module parse PDF"* hoặc *"debug lỗi trích xuất ngày hóa đơn"*), Antigravity sẽ tự động đối chiếu mô tả trong frontmatter của từng skill và tải chỉ dẫn phù hợp (`test-driven-development`, `systematic-debugging`, `pdf`).
2. **Kích hoạt chủ động:**
   Người dùng có thể yêu cầu agent áp dụng skill cụ thể:
   - *"Hãy dùng skill `brainstorming` để phân tích kiến trúc bảng reconciliation."*
   - *"Dùng skill `test-driven-development` để viết unit test cho parser XML."*
   - *"Dùng skill `react-best-practices` để review component hiển thị hóa đơn."*
3. **Cơ chế ghi nhận task:**
   Theo quy ước Antigravity, việc theo dõi task trong các skill lập kế hoạch (`writing-plans`, `executing-plans`) sử dụng artifact markdown checklist (`IsArtifact: true`, `ArtifactType: "task"`), đảm bảo trạng thái luôn được cập nhật xuyên suốt phiên làm việc.
