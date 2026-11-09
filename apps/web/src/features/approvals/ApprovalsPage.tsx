import React, { useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { ReviewNoteModal } from "../processing/ReviewNoteModal";

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const ApprovalsPage: React.FC = () => {
  const {
    invoices,
    approveInvoice,
    rejectInvoice,
    setSelectedDocId,
    setActivePage,
    showToast,
    logEvent,
  } = useInvoiceFlow();

  const [aprTab, setAprTab] = useState<"pending" | "approved" | "rejected">("pending");
  const [searchQuery, setSearchQuery] = useState("");
  const [amtFilter, setAmtFilter] = useState<"all" | "lt20" | "mid" | "gt100">("all");
  const [selectedInvId, setSelectedInvId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [approvalNote, setApprovalNote] = useState("");
  const [isRejectModalOpen, setIsRejectModalOpen] = useState(false);
  const [isRequestNoteOpen, setIsRequestNoteOpen] = useState(false);

  const pendingList = invoices.filter((i) => i.status !== "APPROVED" && i.status !== "REJECTED");
  const approvedList = invoices.filter((i) => i.status === "APPROVED");
  const rejectedList = invoices.filter((i) => i.status === "REJECTED");

  const currentList = aprTab === "pending" ? pendingList : aprTab === "approved" ? approvedList : rejectedList;

  const filteredList = currentList.filter((inv) => {
    const q = searchQuery.toLowerCase();
    const matchQ =
      (inv.invoice_number || "").toLowerCase().includes(q) ||
      (inv.supplier_name || "").toLowerCase().includes(q) ||
      (inv.id || "").toLowerCase().includes(q);
    if (!matchQ) return false;

    const amt = parseFloat(inv.amount_payable) || 0;
    if (amtFilter === "lt20" && amt >= 20e6) return false;
    if (amtFilter === "mid" && (amt < 20e6 || amt > 100e6)) return false;
    if (amtFilter === "gt100" && amt <= 100e6) return false;
    return true;
  });

  const curInv = invoices.find((i) => i.id === selectedInvId) || filteredList[0];

  const handleBulkApprove = async () => {
    const ids = Array.from(checkedIds);
    if (!ids.length) return;
    let count = 0;
    for (const id of ids) {
      const ok = await approveInvoice(id);
      if (ok) count++;
    }
    setCheckedIds(new Set());
    showToast(`Đã duyệt hàng loạt ${count} chứng từ.`);
  };

  const handleSimulateUpperApproval = async () => {
    if (!curInv) return;
    const ok = await approveInvoice(curInv.id, "Giám đốc tài chính (CFO) đã phê duyệt.");
    if (ok) {
      showToast(`Đã giả lập cấp trên phê duyệt #${curInv.invoice_number || curInv.id}.`);
    }
  };

  const handleRemindUpper = () => {
    if (!curInv) return;
    logEvent(`Nhắc duyệt chứng từ #${curInv.invoice_number || curInv.id} gửi Giám đốc`, {
      icon: "send",
      page: "phe-duyet",
      docId: curInv.id,
    });
    showToast(`Đã gửi email nhắc duyệt tới Giám đốc tài chính.`);
  };

  const getWorkflowSteps = (inv: typeof curInv) => {
    if (!inv) return [];
    const amt = parseFloat(inv.amount_payable) || 0;
    const isAppr = inv.status === "APPROVED";
    const isRej = inv.status === "REJECTED";
    const steps = [
      { r: "AI", n: "Hệ thống Document AI", sub: "Trích xuất & kiểm tra", done: true },
      { r: "KTV", n: "Kế toán viên", sub: "Nguyễn Văn An · Đã soát", done: true },
      {
        r: "KTT",
        n: "Kế toán trưởng (Bạn)",
        sub: isAppr ? "Phát (NP) · Đã duyệt" : isRej ? "Phát (NP) · Từ chối" : "Phát (NP) · Đang chờ",
        done: isAppr,
      },
    ];
    if (amt > 50e6) {
      steps.push({
        r: "GDTC",
        n: "Giám đốc tài chính",
        sub: isAppr ? "Lê Minh Quân · Đã duyệt" : "Lê Minh Quân · Chờ duyệt",
        done: isAppr,
      });
    }
    if (amt > 200e6) {
      steps.push({
        r: "TGD",
        n: "Tổng giám đốc",
        sub: isAppr ? "Trần Hoàng Nam · Đã duyệt" : "Trần Hoàng Nam · Chờ duyệt",
        done: isAppr,
      });
    }
    return steps;
  };

  const curTotal = curInv ? parseFloat(curInv.amount_payable) || 0 : 0;
  const isAppr = curInv?.status === "APPROVED";
  const isRej = curInv?.status === "REJECTED";
  const isOver50M = curTotal > 50e6;

  return (
    <main className="pg col on" id="pg-phe-duyet">
      <div className="ph">
        <div>
          <h1>Phê duyệt</h1>
          <p className="sub">
            Hàng đợi phê duyệt chứng từ theo hạn mức: dưới 50 triệu – Kế toán trưởng; trên 50 triệu – thêm Giám đốc tài chính; trên 200 triệu – thêm Tổng giám đốc.
          </p>
        </div>
        <div className="pha">
          <button
            className="bt p"
            id="aBulk"
            disabled={checkedIds.size === 0}
            onClick={handleBulkApprove}
          >
            <Icon name="check" /> Duyệt hàng loạt ({checkedIds.size})
          </button>
        </div>
      </div>

      <div className="arow">
        {/* Table column */}
        <div className="cd" style={{ flex: 1, minWidth: 0 }}>
          <div className="atb">
            {/* Tabs */}
            <div className="sg" id="aTabs">
              {[
                { k: "pending", l: "Chờ duyệt", c: pendingList.length },
                { k: "approved", l: "Đã duyệt", c: approvedList.length },
                { k: "rejected", l: "Từ chối", c: rejectedList.length },
              ].map((t) => (
                <button
                  key={t.k}
                  className={aprTab === t.k ? "on" : ""}
                  onClick={() => {
                    setAprTab(t.k as any);
                    setCheckedIds(new Set());
                  }}
                >
                  {t.l} (<span>{t.c}</span>)
                </button>
              ))}
            </div>

            {/* Search */}
            <div className="srch">
              <Icon name="search" />
              <input
                className="inp"
                id="aSearch"
                placeholder="Tìm chứng từ, nhà cung cấp…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Amount filter */}
            <select
              className="inp"
              style={{ width: "160px", height: "36px" }}
              value={amtFilter}
              onChange={(e) => setAmtFilter(e.target.value as any)}
            >
              <option value="all">Tất cả số tiền</option>
              <option value="lt20">&lt; 20 triệu</option>
              <option value="mid">20 – 100 triệu</option>
              <option value="gt100">&gt; 100 triệu</option>
            </select>
          </div>

          <div className="scr" id="aTableWrap" style={{ overflow: "auto" }}>
            {filteredList.length === 0 ? (
              <div className="empty" style={{ padding: "40px" }}>
                <Icon name="inbox" />
                Không có chứng từ trong mục này
              </div>
            ) : (
              <table className="at" id="aTable">
                <thead>
                  <tr>
                    <th style={{ width: "44px" }}>
                      <input
                        type="checkbox"
                        className="chk"
                        checked={
                          filteredList.length > 0 &&
                          filteredList.every((i) => checkedIds.has(i.id))
                        }
                        onChange={(e) => {
                          if (e.target.checked) {
                            setCheckedIds(new Set(filteredList.map((i) => i.id)));
                          } else {
                            setCheckedIds(new Set());
                          }
                        }}
                      />
                    </th>
                    <th>Chứng từ</th>
                    <th className="r">Tổng tiền</th>
                    <th>Đối soát</th>
                    <th>Độ tin cậy</th>
                    <th>Trạng thái</th>
                    <th>Chờ duyệt</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredList.map((inv) => {
                    const isSel = curInv && inv.id === curInv.id;
                    const isChecked = checkedIds.has(inv.id);
                    const invAppr = inv.status === "APPROVED";
                    const invRej = inv.status === "REJECTED";
                    return (
                      <tr
                        key={inv.id}
                        className={`rw ${isSel ? "sel" : ""}`}
                        onClick={() => setSelectedInvId(inv.id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td style={{ width: "44px" }} onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            className="chk"
                            checked={isChecked}
                            disabled={invAppr || invRej}
                            onChange={(e) => {
                              const s = new Set(checkedIds);
                              if (e.target.checked) s.add(inv.id);
                              else s.delete(inv.id);
                              setCheckedIds(s);
                            }}
                          />
                        </td>
                        <td>
                          <div className="nm2">#{inv.invoice_number || inv.id}</div>
                          <div className="m">{inv.supplier_name || "Nhà cung cấp"}</div>
                        </td>
                        <td className="r">
                          <b>{fmt(inv.amount_payable)}</b>
                        </td>
                        <td>
                          {(() => {
                            const isMismatch =
                              inv.status === "REVIEW_REQUIRED" ||
                              Boolean(inv.issues && inv.issues.some((i) => i.severity === "ERROR" || i.severity === "critical"));
                            return (
                              <span className={`k ${isMismatch ? "k-a" : "k-g"}`}>
                                <Icon name={isMismatch ? "alert" : "check"} />
                                {isMismatch ? "Lệch" : "Khớp"}
                              </span>
                            );
                          })()}
                        </td>
                        <td>
                          {inv.evidence && inv.evidence.length > 0
                            ? `${(
                                (inv.evidence.reduce((s, e) => s + (e.confidence ?? 1.0), 0) /
                                  inv.evidence.length) *
                                100
                              ).toFixed(1)}%`
                            : "—"}
                        </td>
                        <td>
                          <span className={`k ${invAppr ? "k-g" : invRej ? "k-r" : "k-b"}`}>
                            {invAppr ? "Đã phê duyệt" : invRej ? "Đã từ chối" : "Chờ bạn duyệt"}
                          </span>
                        </td>
                        <td style={{ color: "var(--muted)" }}>
                          {invAppr || invRej ? "—" : "< 1 giờ"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right drawer detail */}
        <div className="cd adr" id="aDrawer" style={{ width: "420px", flex: "none" }}>
          {curInv ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px" }}>
                <div>
                  <h2>#{curInv.invoice_number || curInv.id}</h2>
                  <div className="sup">{curInv.supplier_name || "Nhà cung cấp"}</div>
                </div>
                <span className={`k ${isAppr ? "k-g" : isRej ? "k-r" : "k-b"}`}>
                  {isAppr ? "Đã phê duyệt" : isRej ? "Đã từ chối" : "Chờ bạn duyệt"}
                </span>
              </div>

              <div className="amt">
                {fmt(curTotal)} <small>VND</small>
              </div>

              <div className="kv">
                <div>
                  <small>Số hóa đơn</small>
                  <b>{curInv.invoice_series} – {curInv.invoice_number}</b>
                </div>
                <div>
                  <small>Ngày lập</small>
                  <b>{curInv.issue_date || "09/11/2026"}</b>
                </div>
                <div>
                  <small>MST nhà cung cấp</small>
                  <b>{curInv.supplier_tax_id || "0312345678"}</b>
                </div>
                <div>
                  <small>Độ tin cậy trích xuất</small>
                  <b>
                    {curInv.evidence && curInv.evidence.length > 0
                      ? `${(
                          (curInv.evidence.reduce((s, e) => s + (e.confidence ?? 1.0), 0) /
                            curInv.evidence.length) *
                          100
                        ).toFixed(1)}%`
                      : "100% (XML)"}
                  </b>
                </div>
                <div>
                  <small>PO / GRN</small>
                  <b>{curInv.po_number || "—"} / {curInv.grn_number || "—"}</b>
                </div>
                <div>
                  <small>Đối soát 3-Way</small>
                  <b>
                    {curInv.issues && curInv.issues.length > 0 || curInv.status === "REVIEW_REQUIRED"
                      ? "Có chênh lệch"
                      : "Khớp"}
                  </b>
                </div>
              </div>

              <h4>Quy trình phê duyệt ({curTotal > 50e6 ? "Cần 3 cấp duyệt" : "Cần 2 cấp duyệt"})</h4>
              <div className="fl">
                {getWorkflowSteps(curInv).map((s, idx) => (
                  <div key={idx} className={`fs2 ${s.done ? "dn" : ""}`}>
                    <span className={`cc ${s.done ? "" : isRej ? "red" : "cur"}`}>
                      <Icon name={s.done ? "check" : isRej ? "x" : "clock"} />
                    </span>
                    <div>
                      <b>{s.n}</b>
                      <small>{s.sub}</small>
                    </div>
                  </div>
                ))}
              </div>

              {isAppr || isRej ? (
                <div className="adf">
                  <div className="acts">
                    <button
                      className="bt"
                      onClick={() => {
                        setSelectedDocId(curInv.document_id || curInv.id);
                        setActivePage("xu-ly");
                      }}
                    >
                      <Icon name="eye" /> Mở trong Xử lý chứng từ
                    </button>
                  </div>
                </div>
              ) : (
                <div className="adf">
                  {isOver50M && (
                    <div className="bnr b" style={{ margin: "10px 0" }}>
                      <Icon name="info" />
                      Chứng từ trên 50 triệu – cần thêm phê duyệt của Giám đốc tài chính.
                    </div>
                  )}

                  <h4>Ghi chú phê duyệt</h4>
                  <textarea
                    className="inp"
                    id="aNote"
                    rows={2}
                    placeholder="Ghi chú cho người xử lý tiếp theo (tuỳ chọn)"
                    value={approvalNote}
                    onChange={(e) => setApprovalNote(e.target.value)}
                  />
                  <div className="acts">
                    <button
                      className="bt d"
                      onClick={() => setIsRejectModalOpen(true)}
                    >
                      <Icon name="x" /> Từ chối
                    </button>
                    <button
                      className="bt"
                      onClick={() => setIsRequestNoteOpen(true)}
                    >
                      <Icon name="undo" /> Yêu cầu bổ sung
                    </button>
                    <button
                      className="bt p"
                      onClick={() => approveInvoice(curInv.id, approvalNote)}
                    >
                      <Icon name="check" /> Phê duyệt
                    </button>
                  </div>

                  {isOver50M && (
                    <div style={{ marginTop: "12px", display: "flex", gap: "8px" }}>
                      <button className="bt s" style={{ flex: 1 }} onClick={handleRemindUpper}>
                        <Icon name="send" /> Nhắc cấp trên duyệt
                      </button>
                      <button className="bt s" style={{ flex: 1 }} onClick={handleSimulateUpperApproval}>
                        <Icon name="play" /> Giả lập duyệt
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="empty">
              <Icon name="approve" />
              Chọn một chứng từ để xem chi tiết
            </div>
          )}
        </div>
      </div>

      {/* Rejection Modal */}
      <ReviewNoteModal
        isOpen={isRejectModalOpen}
        onClose={() => setIsRejectModalOpen(false)}
        onSubmit={async (reason) => {
          setIsRejectModalOpen(false);
          if (curInv) {
            await rejectInvoice(curInv.id, reason);
          }
        }}
      />

      {/* Request Supplement Modal */}
      <ReviewNoteModal
        isOpen={isRequestNoteOpen}
        onClose={() => setIsRequestNoteOpen(false)}
        onSubmit={async (notes) => {
          setIsRequestNoteOpen(false);
          if (curInv) {
            await rejectInvoice(curInv.id, `Yêu cầu bổ sung chứng từ: ${notes}`);
          }
        }}
      />
    </main>
  );
};
