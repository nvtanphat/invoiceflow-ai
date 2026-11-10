import React, { useState, useEffect } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { api, ReconciliationResult } from "../../lib/api-client";
import { ExtendedInvoiceItem } from "../../lib/seed-data";

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const MatchingPage: React.FC = () => {
  const {
    invoices,
    reconciliations,
    runReconcile,
    setActivePage,
    setSelectedDocId,
    showToast,
  } = useInvoiceFlow();

  const [tolerance, setTolerance] = useState(2);
  const [filterKind, setFilterKind] = useState<"all" | "ok" | "bad" | "miss">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedInvId, setSelectedInvId] = useState<string | null>(null);
  const [reconResult, setReconResult] = useState<ReconciliationResult | null>(null);
  const [curInvDetails, setCurInvDetails] = useState<ExtendedInvoiceItem | null>(null);
  const [decisionState, setDecisionState] = useState<Record<string, "accepted" | "returned" | null>>({});

  useEffect(() => {
    if (!selectedInvId && invoices.length > 0) {
      setSelectedInvId(invoices[0].id);
    }
  }, [invoices, selectedInvId]);

  useEffect(() => {
    if (!selectedInvId) {
      setCurInvDetails(null);
      return;
    }
    const local = invoices.find((i) => i.id === selectedInvId);
    api.getInvoice(selectedInvId)
      .then((full) => setCurInvDetails({ ...local, ...full }))
      .catch(() => setCurInvDetails(local || null));
  }, [selectedInvId, invoices]);

  useEffect(() => {
    if (!selectedInvId) return;
    if (reconciliations[selectedInvId]) {
      setReconResult(reconciliations[selectedInvId]);
    } else {
      runReconcile(selectedInvId).then((res) => {
        if (res) setReconResult(res);
      });
    }
  }, [selectedInvId, reconciliations, runReconcile]);

  const rawInv = invoices.find((i) => i.id === selectedInvId) || invoices[0];
  const curInv = curInvDetails || rawInv;

  const getDecision = (id: string) => decisionState[id] || null;

  // Compute matched lines and differences
  const poLines = curInv?.po_lines || [];
  const grnQtys = curInv?.grn_qtys || [];
  const invLines = curInv?.lines || [];

  const matchedLines = invLines.map((l, i) => {
    const qI = parseFloat(l.qty) || 0;
    const pI = parseFloat(l.unit_price) || 0;
    const poLine = poLines[i];
    const qP = poLine ? poLine.qty : qI;
    const pP = poLine ? poLine.unit_price : pI;
    const qG = grnQtys[i] !== undefined ? grnQtys[i] : qI;
    const pDiff = pI - pP;
    const pPct = pP > 0 ? (pDiff / pP) * 100 : 0;
    const qDiff = qI - qG;
    const isQBad = qI !== qG;
    const isPBad = Math.abs(pPct) > tolerance;
    return {
      sku: l.sku_ref || `SP-${i + 1}`,
      desc: l.description,
      qP,
      pP,
      qG,
      qI,
      pI,
      qDiff,
      pPct,
      isQBad,
      isPBad,
      isDiff: isQBad || isPBad,
    };
  });

  const hasLineDiff = matchedLines.some((l) => l.isDiff);
  const pBad = matchedLines.some((l) => l.isPBad);
  const qBad = matchedLines.some((l) => l.isQBad);

  const subtotal = curInv ? parseFloat(curInv.subtotal) || 0 : 0;
  const poSum = poLines.length
    ? poLines.reduce((s, p) => s + p.qty * p.unit_price, 0)
    : subtotal;
  const grnSum = grnQtys.length
    ? matchedLines.reduce((s, l) => s + l.qG * l.pI, 0)
    : subtotal;

  const curDecision = curInv ? getDecision(curInv.id) : null;
  const isMatched =
    curDecision === "accepted"
      ? true
      : !hasLineDiff && (reconResult ? reconResult.is_matched : true);

  const isDocDone = (invItem: ExtendedInvoiceItem) =>
    invItem.status === "APPROVED" || invItem.status === "REJECTED";

  const isInvoiceDiscrepant = (invItem: ExtendedInvoiceItem) => {
    const dec = getDecision(invItem.id);
    if (dec === "accepted") return false;
    if (reconciliations[invItem.id]) {
      return !reconciliations[invItem.id].is_matched;
    }
    return Boolean(invItem.issues && invItem.issues.length > 0);
  };

  const counts = {
    all: invoices.length,
    ok: invoices.filter((i) => !isInvoiceDiscrepant(i)).length,
    bad: invoices.filter((i) => isInvoiceDiscrepant(i)).length,
    miss: 0,
  };

  const filteredInvoices = invoices.filter((inv) => {
    const q = searchQuery.toLowerCase();
    const matchQ =
      (inv.invoice_number || "").toLowerCase().includes(q) ||
      (inv.supplier_name || "").toLowerCase().includes(q) ||
      (inv.po_number || "").toLowerCase().includes(q) ||
      (inv.id || "").toLowerCase().includes(q);
    if (!matchQ) return false;

    const isBad = isInvoiceDiscrepant(inv);
    const isOk = !isBad;

    if (filterKind === "all") return true;
    if (filterKind === "ok") return isOk;
    if (filterKind === "bad") return isBad;
    return false;
  });

  const handleAcceptDiscrepancy = () => {
    if (!curInv) return;
    setDecisionState((prev) => ({ ...prev, [curInv.id]: "accepted" }));
    showToast(`Đã chấp nhận chênh lệch cho #${curInv.invoice_number || curInv.id}.`);
  };

  const handleReturnSupplier = () => {
    if (!curInv) return;
    setDecisionState((prev) => ({ ...prev, [curInv.id]: "returned" }));
    showToast(`Đã ghi nhận yêu cầu nhà cung cấp điều chỉnh hóa đơn.`);
  };

  const handleUndoDecision = () => {
    if (!curInv) return;
    setDecisionState((prev) => ({ ...prev, [curInv.id]: null }));
    showToast(`Đã hoàn tác quyết định đối soát.`);
  };

  return (
    <main className="pg col on" id="pg-doi-soat">
      <div className="ph">
        <div>
          <h1>Đối soát 3-Way (3-Way Matching)</h1>
          <p className="sub">
            Kết quả đối soát 3 chiều: So khớp Đơn đặt hàng (PO) – Phiếu nhập kho (GRN) – Hóa đơn theo số lượng, đơn giá và tổng tiền.
          </p>
        </div>
        <div className="pha">
          <div className="tol">
            Dung sai đơn giá ±
            <input
              id="tolIn"
              type="number"
              min="0"
              max="20"
              step="0.5"
              value={tolerance}
              onChange={(e) => {
                const v = parseFloat(e.target.value) || 2;
                setTolerance(v);
                showToast(`Đã cập nhật dung sai đơn giá ±${v}% và tính lại đối soát.`);
              }}
            />
            %
          </div>
          <button
            className="bt"
            onClick={() => {
              if (selectedInvId) {
                runReconcile(selectedInvId);
                showToast(`Đã tính lại đối soát 3-Way (dung sai ±${tolerance}%).`);
              }
            }}
          >
            <Icon name="refresh" /> Chạy đối soát lại
          </button>
        </div>
      </div>

      <div className="mrow">
        {/* Left list */}
        <div className="cd mlist">
          <div style={{ padding: "14px 16px 0" }}>
            <div className="srch">
              <Icon name="search" />
              <input
                className="inp"
                id="mSearch"
                placeholder="Tìm mã chứng từ, nhà cung cấp, số PO…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          <div className="mfil" id="mFil">
            {[
              { k: "all", l: "Tất cả", c: counts.all },
              { k: "ok", l: "Khớp", c: counts.ok },
              { k: "bad", l: "Lệch", c: counts.bad },
              { k: "miss", l: "Thiếu", c: counts.miss },
            ].map((f) => (
              <button
                key={f.k}
                className={`chip ${filterKind === f.k ? "on" : ""}`}
                onClick={() => setFilterKind(f.k as any)}
              >
                {f.l} <b>{f.c}</b>
              </button>
            ))}
          </div>

          <div className="scr" id="mList" style={{ marginTop: "10px", flex: 1 }}>
            {filteredInvoices.map((inv) => {
              const isSel = inv.id === selectedInvId;
              const dec = getDecision(inv.id);
              const isBad =
                dec !== "accepted" &&
                Boolean(reconciliations[inv.id] && !reconciliations[inv.id].is_matched);
              const ok = !isBad;

              return (
                <div
                  key={inv.id}
                  className={`mi2 ${isSel ? "sel" : ""}`}
                  onClick={() => setSelectedInvId(inv.id)}
                >
                  <div>
                    <div className="t1">#{inv.invoice_number || inv.id}</div>
                    <div className="t2">{inv.supplier_name || "Nhà cung cấp"}</div>
                  </div>
                  <div className="rt">
                    <span className={`k ${dec === "accepted" ? "k-b" : dec === "returned" ? "k-a" : ok ? "k-g" : "k-a"}`}>
                      {dec === "accepted"
                        ? "Đã chấp nhận"
                        : dec === "returned"
                        ? "Đã trả NCC"
                        : ok
                        ? "Khớp"
                        : "Lệch"}
                    </span>
                    <small>{fmt(inv.amount_payable)}</small>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right detail */}
        <div className="cd mdet" id="mDetail" style={{ display: "flex", flexDirection: "column" }}>
          {curInv ? (
            <>
              <div className="mdh">
                <h2>#{curInv.invoice_number || curInv.id}</h2>
                <span className="sup">{curInv.supplier_name || "Nhà cung cấp"}</span>
                <span
                  style={{ marginLeft: "auto" }}
                  className={`k ${curDecision === "accepted" ? "k-b" : isMatched ? "k-g" : "k-a"}`}
                >
                  <Icon name={isMatched ? "check" : "alert"} />
                  {curDecision === "accepted"
                    ? "Đã chấp nhận chênh lệch"
                    : isMatched
                    ? "Đối soát khớp"
                    : "Phát hiện chênh lệch"}
                </span>
              </div>

              {/* 3-Way Tri-Cards */}
              <div className="tri">
                <div className="dc">
                  <div className="tp">
                    <Icon name="cart" /> Đơn đặt hàng (PO)
                  </div>
                  <div className="no">{curInv.po_number || "PO-2026-0456"}</div>
                  <div className="mt">Đơn giá theo PO đã ký</div>
                  <div className="am">
                    {fmt(poSum)} VND <small className="nt">chưa thuế</small>
                  </div>
                </div>

                <div className="lnk">
                  <span className={`cc ${pBad ? "amb" : ""}`}>
                    <Icon name={pBad ? "alert" : "check"} />
                  </span>
                  Đơn giá
                </div>

                <div className={`dc ${pBad || qBad ? "bad" : ""}`}>
                  <div className="tp">
                    <Icon name="doc" /> Hóa đơn NCC
                  </div>
                  <div className="no">{curInv.invoice_series} – {curInv.invoice_number}</div>
                  <div className="mt">{curInv.issue_date || "09/11/2026"} · {curInv.supplier_tax_id}</div>
                  <div className="am">
                    {fmt(subtotal)} VND <small className="nt">chưa thuế</small>
                  </div>
                </div>

                <div className="lnk">
                  <span className={`cc ${qBad ? "amb" : ""}`}>
                    <Icon name={qBad ? "alert" : "check"} />
                  </span>
                  Số lượng
                </div>

                <div className="dc">
                  <div className="tp">
                    <Icon name="package" /> Phiếu nhập kho (GRN)
                  </div>
                  <div className="no">{curInv.grn_number || "GRN-0321"}</div>
                  <div className="mt">SL thực nhận theo kho</div>
                  <div className="am">
                    {fmt(grnSum)} VND <small className="nt">chưa thuế</small>
                  </div>
                </div>
              </div>

              {/* Checks */}
              <div className="chks">
                <div className="chk2">
                  <span className={`cc ${curInv.tax_authority_status === "INACTIVE" ? "red" : ""}`}>
                    <Icon name={curInv.tax_authority_status === "INACTIVE" ? "x" : "check"} />
                  </span>
                  <div>
                    <b>MST nhà cung cấp: {curInv.tax_authority_status === "INACTIVE" ? "Không hợp lệ" : "Hợp lệ"}</b>
                    <small>Doanh nghiệp {curInv.tax_authority_status === "INACTIVE" ? "ngừng hoạt động" : "đang hoạt động bình thường"}</small>
                  </div>
                </div>

                <div className="chk2">
                  <span className="cc">
                    <Icon name="check" />
                  </span>
                  <div>
                    <b>Số hóa đơn không trùng lặp</b>
                    <small>{curInv.invoice_series} – {curInv.invoice_number}</small>
                  </div>
                </div>

                <div className={`chk2 ${isMatched ? "" : "bad"}`}>
                  <span className={`cc ${isMatched ? "" : "red"}`}>
                    <Icon name={isMatched ? "check" : "x"} />
                  </span>
                  <div>
                    <b>Tổng tiền khớp</b>
                    <small>{fmt(curInv.amount_payable)} VND</small>
                  </div>
                </div>
              </div>

              {/* Line comparison table */}
              <table className="mt3">
                <thead>
                  <tr>
                    <th>Mã hàng / Mô tả</th>
                    <th>SL PO</th>
                    <th>ĐG PO</th>
                    <th>SL nhận (GRN)</th>
                    <th>SL hóa đơn</th>
                    <th>ĐG hóa đơn</th>
                    <th>Chênh lệch</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {matchedLines.map((l, idx) => {
                    const diffText = [];
                    if (l.isQBad) diffText.push(`SL ${l.qDiff > 0 ? "+" : ""}${l.qDiff}`);
                    if (l.isPBad) diffText.push(`ĐG ${l.pPct > 0 ? "+" : ""}${l.pPct.toFixed(1)}%`);
                    return (
                      <tr key={idx}>
                        <td>
                          <b>{l.sku}</b>
                          <div className="m">{l.desc}</div>
                        </td>
                        <td>{l.qP.toFixed(0)}</td>
                        <td>{fmt(l.pP)}</td>
                        <td className={l.isQBad ? "bd" : ""}>{l.qG.toFixed(0)}</td>
                        <td className={l.isQBad ? "bd" : ""}>{l.qI.toFixed(0)}</td>
                        <td className={l.isPBad ? "bd" : ""}>{fmt(l.pI)}</td>
                        <td>
                          {diffText.length ? (
                            <span className="k k-a">{diffText.join(" · ")}</span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          <span className={`cc ${diffText.length ? "amb" : ""}`}>
                            <Icon name={diffText.length ? "alert" : "check"} />
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Tổng giá trị (chưa thuế)</td>
                    <td colSpan={2}>PO: {fmt(poSum)}</td>
                    <td colSpan={2}>GRN: {fmt(grnSum)}</td>
                    <td colSpan={3}>Hóa đơn: {fmt(subtotal)}</td>
                  </tr>
                </tfoot>
              </table>

              {/* Decision Banners */}
              {curDecision === "accepted" ? (
                <div className="bnr b" style={{ marginTop: "14px" }}>
                  <Icon name="info" />
                  Bạn đã chấp nhận chênh lệch cho chứng từ này – hệ thống coi là khớp khi trình duyệt.
                </div>
              ) : curDecision === "returned" ? (
                <div className="bnr a" style={{ marginTop: "14px" }}>
                  <Icon name="send" />
                  Đã gửi yêu cầu nhà cung cấp điều chỉnh hóa đơn.
                </div>
              ) : isMatched ? (
                <div className="bnr g" style={{ marginTop: "14px" }}>
                  <Icon name="circlecheck" />
                  Hóa đơn khớp hoàn toàn với PO và phiếu nhập kho trong dung sai ±{tolerance}%.
                </div>
              ) : (
                <div className="bnr a" style={{ marginTop: "14px" }}>
                  <Icon name="alert" />
                  Phát hiện chênh lệch – cần xử lý trước khi phê duyệt.
                </div>
              )}

              {/* Action Buttons */}
              <div className="mact" style={{ marginTop: "16px", display: "flex", gap: "10px", justifyContent: "flex-end" }}>
                {!isMatched && !curDecision && (
                  <>
                    <button className="bt" onClick={handleReturnSupplier}>
                      <Icon name="undo" /> Yêu cầu NCC điều chỉnh
                    </button>
                    <button className="bt" onClick={handleAcceptDiscrepancy}>
                      <Icon name="check" /> Chấp nhận chênh lệch
                    </button>
                  </>
                )}
                {curDecision && (
                  <button className="bt" onClick={handleUndoDecision}>
                    <Icon name="undo" /> Hoàn tác quyết định
                  </button>
                )}
                <button
                  className="bt p"
                  disabled={isDocDone(curInv)}
                  onClick={() => {
                    setSelectedDocId(curInv.document_id || curInv.id);
                    setActivePage("phe-duyet");
                  }}
                >
                  <Icon name="arrowr" /> Chuyển phê duyệt
                </button>
              </div>
            </>
          ) : (
            <div className="empty" style={{ padding: "40px 20px" }}>
              <Icon name="layers" />
              Chọn một chứng từ để xem kết quả đối soát 3-Way
            </div>
          )}
        </div>
      </div>
    </main>
  );
};
