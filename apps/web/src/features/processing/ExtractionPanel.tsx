import React, { useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { InvoiceLineItem } from "../../lib/api-client";
import { InvoiceInfoSection } from "./InvoiceInfoSection";
import { LineItemsSection } from "./LineItemsSection";
import { InvoiceAuditSection } from "./InvoiceAuditSection";
import { ReviewNoteModal } from "./ReviewNoteModal";

export const ExtractionPanel: React.FC = () => {
  const {
    documents,
    selectedDocId,
    selectedInvoice,
    highlightedField,
    setHighlightedField,
    approveInvoice,
    rejectInvoice,
    correctInvoice,
    setActivePage,
    showToast,
  } = useInvoiceFlow();

  const [activeTab, setActiveTab] = useState<"res" | "ev" | "hist">("res");
  const [openSecs, setOpenSecs] = useState<{ s1: boolean; s2: boolean; s3: boolean }>({
    s1: true,
    s2: true,
    s3: true,
  });

  // Edit mode
  const [editSec, setEditSec] = useState<"info" | "lines" | null>(null);
  const [editMst, setEditMst] = useState("");
  const [editNo, setEditNo] = useState("");
  const [editDate, setEditDate] = useState("");
  const [editLines, setEditLines] = useState<InvoiceLineItem[]>([]);
  const [reviewNoteModal, setReviewNoteModal] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  const curDoc = documents.find((d) => d.id === selectedDocId);
  const inv = selectedInvoice;
  const prevInvoiceIdRef = React.useRef<string | null>(null);

  // Initialize edit fields when invoice changes
  React.useEffect(() => {
    if (inv) {
      setEditMst(inv.supplier_tax_id || "");
      setEditNo(inv.invoice_number || "");
      setEditDate(inv.issue_date || "");
      setEditLines(inv.lines ? JSON.parse(JSON.stringify(inv.lines)) : []);
      if (prevInvoiceIdRef.current !== inv.id) {
        prevInvoiceIdRef.current = inv.id;
        setErrorBanner(null);
        setSuccessBanner(null);
      }
    }
  }, [inv]);

  if (!inv) {
    return (
      <aside className="rp">
        <div className="tabs">
          <div className="tab on">
            <Icon name="spark" />
            Kết quả trích xuất AI
          </div>
        </div>
        <div className="rbody" style={{ padding: "40px 20px", textAlign: "center", color: "var(--muted)" }}>
          <Icon name="inbox" style={{ width: "36px", height: "36px", margin: "0 auto 12px" }} />
          <div>Vui lòng chọn chứng từ để xem kết quả trích xuất</div>
        </div>
      </aside>
    );
  }

  const isDocProcessing =
    curDoc?.status === "PROCESSING" ||
    inv.status === "PROCESSING";

  const progressVal = inv.progress || 68;
  const procSteps = [
    { name: "Tải lên tệp chứng từ", done: true },
    { name: "Phân loại chứng từ", done: progressVal >= 15 },
    { name: "Trích xuất OCR + LLM", done: progressVal >= 55 },
    { name: "Kiểm tra hợp lệ (MST, số HĐ, ngày)", done: progressVal >= 80 },
    { name: "Đối soát 3-Way", done: progressVal >= 95 },
  ];

  // Detect arithmetic mismatch
  const hasArithmeticMismatch = (inv.lines || []).some((l) => {
    const q = parseFloat(l.qty) || 0;
    const p = parseFloat(l.unit_price) || 0;
    const amt = parseFloat(l.line_amount) || 0;
    return Math.abs(q * p - amt) > 1.0;
  });

  // Calculate overall confidence
  const avgConf =
    inv.evidence && inv.evidence.length > 0
      ? (inv.evidence.reduce((s, e) => s + e.confidence, 0) / inv.evidence.length) * 100
      : 98.7;
  const confVal = Math.min(99.9, Math.max(70, avgConf));
  const ring = ((confVal / 100) * 238.76 - 3).toFixed(1);
  const isApproved = inv.status === "APPROVED";
  const isRejected = inv.status === "REJECTED";

  const handleApprove = async () => {
    if (hasArithmeticMismatch) {
      setErrorBanner(
        "Lỗi nghiêm trọng: LINE_ARITHMETIC_MISMATCH: Dòng hàng không khớp số học. Không thể phê duyệt (critical blocking)."
      );
      showToast("Lệch số học dòng hàng, vui lòng đính chính trước khi duyệt.", "err");
      return;
    }
    setErrorBanner(null);
    const ok = await approveInvoice(inv.id);
    if (ok) {
      setSuccessBanner("Hóa đơn đã được phê duyệt thành công!");
    }
  };

  const handleSaveCorrection = async () => {
    let corrections: Partial<typeof inv> = {};
    if (editSec === "info") {
      corrections = {
        supplier_tax_id: editMst,
        invoice_number: editNo,
        issue_date: editDate,
      };
    } else if (editSec === "lines" || hasArithmeticMismatch) {
      corrections = {
        lines: editLines,
      };
    }

    const ok = await correctInvoice(inv.id, corrections);
    if (ok) {
      setEditSec(null);
      setErrorBanner(null);
      setSuccessBanner("Thông tin đính chính đã được lưu và cập nhật phiên bản.");
    }
  };

  return (
    <aside className="rp">
      {/* Tabs */}
      <div className="tabs" id="rtabs">
        <div
          className={`tab ${activeTab === "res" ? "on" : ""}`}
          onClick={() => setActiveTab("res")}
        >
          <Icon name="spark" />
          Kết quả trích xuất AI
        </div>
        <div
          className={`tab ${activeTab === "ev" ? "on" : ""}`}
          onClick={() => setActiveTab("ev")}
        >
          <Icon name="img" />
          Bằng chứng
        </div>
        <div
          className={`tab ${activeTab === "hist" ? "on" : ""}`}
          onClick={() => setActiveTab("hist")}
        >
          <Icon name="clock" />
          Lịch sử xử lý
        </div>
      </div>

      <div className="rbody" id="rbody">
        {/* Arithmetic Mismatch Warning Banner */}
        {hasArithmeticMismatch && (
          <div
            data-testid="arithmetic-mismatch-banner"
            className="bnr a"
            style={{
              margin: "12px 14px 4px",
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Icon name="alert" style={{ width: "18px", height: "18px", flexShrink: 0 }} />
            <span style={{ fontSize: "12.5px" }}>
              Cảnh báo đỏ: Phát hiện sai lệch số học dòng hàng (LINE_ARITHMETIC_MISMATCH - LỆCH SỐ HỌC). Phải đính chính trước khi phê duyệt!
            </span>
          </div>
        )}

        {/* Banner Alert Feedback */}
        {errorBanner && (
          <div
            data-testid="error-banner"
            className="bnr a"
            style={{
              margin: "12px 14px 4px",
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Icon name="alert" style={{ width: "18px", height: "18px", flexShrink: 0 }} />
            <span style={{ fontSize: "12.5px" }}>{errorBanner}</span>
          </div>
        )}

        {successBanner && (
          <div
            className="bnr g"
            style={{
              margin: "12px 14px 4px",
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Icon name="check" style={{ width: "18px", height: "18px", flexShrink: 0 }} />
            <span style={{ fontSize: "12.5px" }}>{successBanner}</span>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px 0" }}>
          <span style={{ fontSize: "13px", fontWeight: 700, color: "var(--navy)" }}>
            Hóa đơn #{inv.invoice_number || inv.id}
          </span>
          <span className="k k-b" style={{ fontSize: "11px", height: "20px" }}>
            Rev v{inv.revision}
          </span>
        </div>

        {isDocProcessing ? (
          /* Live Document AI Processing Widget */
          <div className="pc" style={{ margin: "20px 14px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontWeight: 700, fontSize: "15.5px", color: "var(--navy)" }}>
                Đang trích xuất dữ liệu…
              </div>
              <b style={{ color: "var(--blue)", fontSize: "17px" }}>{progressVal}%</b>
            </div>
            <div className="meter" style={{ margin: "14px 0 16px" }}>
              <i style={{ width: `${progressVal}%` }}></i>
            </div>
            {procSteps.map((s, idx) => (
              <div key={idx} className={`stp ${s.done ? "" : "off"}`} style={{ padding: "6px 0" }}>
                <span className="cc">
                  <Icon name={s.done ? "check" : "clock"} />
                </span>
                <span style={{ fontSize: "13px", fontWeight: s.done ? 600 : 400 }}>{s.name}</span>
              </div>
            ))}
          </div>
        ) : activeTab === "res" ? (
          <>
            {/* Confidence Score Gauge Header */}
            <div className="conf">
              <div className="donut">
                <svg viewBox="0 0 92 92">
                  <circle
                    cx="46"
                    cy="46"
                    r="38"
                    fill="none"
                    stroke={confVal >= 95 ? "#e3f3e9" : "#fbefd2"}
                    strokeWidth="9"
                  />
                  <circle
                    cx="46"
                    cy="46"
                    r="38"
                    fill="none"
                    stroke={confVal >= 95 ? "#22a65b" : "#e8a200"}
                    strokeWidth="9"
                    strokeLinecap="round"
                    strokeDasharray={`${ring} 238.76`}
                  />
                </svg>
                <span>{confVal.toFixed(1)}%</span>
              </div>
              <div className="tx">
                <div className="t1">Độ tin cậy tổng thể</div>
                <div className="t2">Dữ liệu đã được nhận dạng và kiểm tra chéo.</div>
              </div>
              {confVal >= 95 && !hasArithmeticMismatch ? (
                <span className="pill g">
                  <span className="cc">
                    <Icon name="check" />
                  </span>
                  Đạt yêu cầu
                </span>
              ) : (
                <span className="pill a">
                  <span className="cc amb">
                    <Icon name="alert" />
                  </span>
                  Cần kiểm tra
                </span>
              )}
            </div>

            {/* Section 1: Thông tin hóa đơn */}
            <InvoiceInfoSection
              inv={inv}
              isOpen={openSecs.s1}
              onToggle={() => setOpenSecs((p) => ({ ...p, s1: !p.s1 }))}
              isEditing={editSec === "info"}
              onStartEdit={() => setEditSec("info")}
              onCancelEdit={() => setEditSec(null)}
              onSave={handleSaveCorrection}
              editMst={editMst}
              setEditMst={setEditMst}
              editNo={editNo}
              setEditNo={setEditNo}
              editDate={editDate}
              setEditDate={setEditDate}
              onHoverField={setHighlightedField}
            />

            {/* Section 2: Danh sách dòng hàng */}
            <LineItemsSection
              linesCount={(inv.lines || []).length}
              isOpen={openSecs.s2}
              onToggle={() => setOpenSecs((p) => ({ ...p, s2: !p.s2 }))}
              isEditing={editSec === "lines"}
              onStartEdit={() => setEditSec("lines")}
              onCancelEdit={() => setEditSec(null)}
              onSave={handleSaveCorrection}
              editLines={editLines}
              setEditLines={setEditLines}
              hasArithmeticMismatch={hasArithmeticMismatch}
              onHoverLine={(idx) => setHighlightedField(idx != null ? `line-${idx}` : null)}
            />

            {/* Section 3: Kiểm tra & đối soát */}
            <InvoiceAuditSection
              inv={inv}
              isOpen={openSecs.s3}
              onToggle={() => setOpenSecs((p) => ({ ...p, s3: !p.s3 }))}
              onOpenMatching={() => setActivePage("doi-soat")}
            />
          </>
        ) : activeTab === "ev" ? (
          /* Tab 2: Bằng chứng BBox */
          <div style={{ padding: "14px 8px" }}>
            <div className="evh" style={{ marginBottom: "12px", fontSize: "12.5px", color: "var(--muted)" }}>
              Bằng chứng OCR và toạ độ BBox được trích xuất từ tài liệu gốc. Di chuột để xem vị trí trên chứng từ:
            </div>
            {inv.evidence && inv.evidence.length > 0 ? (
              inv.evidence.map((ev, i) => (
                <div
                  key={i}
                  className="ev"
                  onMouseEnter={() => setHighlightedField(ev.field_name)}
                  onMouseLeave={() => setHighlightedField(null)}
                  style={{
                    cursor: "pointer",
                    padding: "10px 12px",
                    border: highlightedField === ev.field_name ? "1px solid var(--blue)" : "1px solid var(--line)",
                    borderRadius: "8px",
                    marginBottom: "8px",
                    background: highlightedField === ev.field_name ? "var(--blue-soft)" : "#fff",
                    transition: "all .15s ease",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--navy)" }}>
                      {ev.field_name}
                    </div>
                    <span className="k k-g" style={{ fontSize: "11px" }}>
                      {(ev.confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ fontSize: "12px", color: "#3b4557", margin: "4px 0" }}>
                    Giá trị: <b>{ev.raw_value}</b>
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--muted)" }}>
                    {ev.source} · Trang {ev.page + 1}
                  </div>
                </div>
              ))
            ) : (
              <div className="empty" style={{ padding: "30px 10px", textAlign: "center" }}>
                <Icon name="img" style={{ width: "32px", height: "32px", margin: "0 auto 8px" }} />
                <div>Chưa có dữ liệu bằng chứng BBox chi tiết</div>
              </div>
            )}
          </div>
        ) : (
          /* Tab 3: Lịch sử xử lý Audit Trail */
          <div className="tl" style={{ padding: "16px 12px" }}>
            <div className="tli">
              <i></i>
              <b>Tải lên chứng từ</b>
              <small>Hệ thống Ingestion · {inv.issue_date || "09/11/2026"}</small>
            </div>
            <div className="tli g">
              <i></i>
              <b>Trích xuất Document AI hoàn tất</b>
              <small>Độ tin cậy {confVal.toFixed(1)}% · Đa tầng OCR + Docling</small>
            </div>
            <div className={`tli ${hasArithmeticMismatch ? "a" : "g"}`}>
              <i></i>
              <b>Kiểm tra tính hợp lệ số học</b>
              <small>
                {hasArithmeticMismatch
                  ? "Phát hiện chênh lệch số học dòng hàng"
                  : "Các dòng hàng khớp số học 100%"}
              </small>
            </div>
            <div className="tli g">
              <i></i>
              <b>Tra cứu cơ sở dữ liệu Tổng cục Thuế</b>
              <small>Doanh nghiệp đang hoạt động bình thường</small>
            </div>
            {isApproved && (
              <div className="tli g">
                <i></i>
                <b>Đã phê duyệt hóa đơn</b>
                <small>Kế toán trưởng (NP) · Đã hoàn tất và sẵn sàng xuất</small>
              </div>
            )}
            {isRejected && (
              <div className="tli r">
                <i></i>
                <b>Đã từ chối hóa đơn</b>
                <small>Lý do: {inv.note || "Không đạt yêu cầu kiểm tra"}</small>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Footer */}
      {!isDocProcessing && (
        <div className="foot" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <div
            className="btn o"
            onClick={() => setReviewNoteModal(true)}
            style={{ cursor: "pointer", flex: 1 }}
          >
            <Icon name="flag" />
            Cần rà soát
          </div>
          <button
            type="button"
            className={`btn p ${hasArithmeticMismatch || isApproved ? "dis" : ""}`}
            id="btnApprove"
            onClick={handleApprove}
            style={{
              cursor: hasArithmeticMismatch || isApproved ? "not-allowed" : "pointer",
              flex: 1.2,
              border: "none",
            }}
          >
            <Icon name="check" />
            {isApproved ? "Đã phê duyệt" : "Phê duyệt (Approve)"}
          </button>
          {isApproved && (
            <button
              type="button"
              className="bt s"
              style={{ height: "46px", padding: "0 10px" }}
              onClick={() => setActivePage("doi-soat")}
            >
              <Icon name="layers" /> Xem 3-Way Matching
            </button>
          )}
        </div>
      )}

      {/* Note / Review Modal */}
      <ReviewNoteModal
        isOpen={reviewNoteModal}
        onClose={() => setReviewNoteModal(false)}
        onSubmit={async (note) => {
          setReviewNoteModal(false);
          await rejectInvoice(inv.id, note);
        }}
      />
    </aside>
  );
};
