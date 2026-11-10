import React, { useState } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { api } from "../../lib/api-client";

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

type ServerFormat = "xlsx" | "csv" | "json";

// Only formats the server renders: the file must be exactly what is recorded as exported.
const FMTS: { k: ServerFormat; ic: string; l: string; sub: string }[] = [
  { k: "xlsx", ic: "xls", l: "Excel", sub: ".xlsx" },
  { k: "csv", ic: "table", l: "CSV", sub: ".csv UTF-8" },
  { k: "json", ic: "braces", l: "JSON", sub: ".json" },
];

interface ExportRecord {
  name: string;
  rows: number;
  size: number;
  time: string;
  sha256: string;
  blob: Blob;
}

const saveBlob = (blob: Blob, name: string) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

export const ExportPage: React.FC = () => {
  const { invoices, showToast, logEvent, refreshData } = useInvoiceFlow();
  const [format, setFormat] = useState<ServerFormat>("xlsx");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<ExportRecord[]>([]);

  // Mirrors the server rule: only approved invoices are exported, each exactly once.
  const exportable = invoices.filter((inv) => inv.status === "APPROVED");

  const handleExport = async () => {
    setBusy(true);
    try {
      const { blob, sha256 } = await api.postExport(format);
      const now = new Date();
      const stamp = now.toISOString().slice(0, 19).replace(/[-:T]/g, "");
      const name = `invoiceflow_export_${stamp}.${format}`;
      saveBlob(blob, name);
      setHistory((prev) => [
        {
          name,
          rows: exportable.length,
          size: blob.size,
          time: now.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
          sha256,
          blob,
        },
        ...prev,
      ]);
      showToast(`Đã chốt xuất ${exportable.length} hóa đơn – ${name}`);
      logEvent(`Chốt xuất kế toán ${exportable.length} hóa đơn (${format.toUpperCase()})`, {
        icon: "export",
        page: "xuat-du-lieu",
      });
      await refreshData();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Xuất dữ liệu thất bại", "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="pg col on" id="pg-xuat-du-lieu">
      <div className="ph">
        <div>
          <h1>Xuất dữ liệu</h1>
          <p className="sub">
            Chốt lô xuất hóa đơn đã phê duyệt sang phần mềm kế toán. Hóa đơn đã xuất chuyển sang trạng thái
            Đã xuất và không thể nằm trong lô sau.
          </p>
        </div>
      </div>

      <div className="erow">
        <div className="cd ecfg">
          <div className="cb scr" style={{ padding: "18px 22px 20px" }}>
            <div className="eh">Định dạng</div>
            <div className="fmts" id="eFmts">
              {FMTS.map((f) => (
                <div key={f.k} className={`fmt ${format === f.k ? "on" : ""}`} onClick={() => setFormat(f.k)}>
                  <Icon name={f.ic} />
                  <div>
                    <b>{f.l}</b>
                    <small>{f.sub}</small>
                  </div>
                </div>
              ))}
            </div>
            <div className="enote" id="eNote">
              Lô xuất gồm toàn bộ hóa đơn đang ở trạng thái Đã phê duyệt, sắp xếp theo ngày lập và số hóa đơn. Mỗi
              tệp có mã SHA-256 được ghi vào nhật ký kiểm toán.
            </div>
            <button
              className="bt p"
              id="eBtn"
              style={{ width: "100%", height: "46px", marginTop: "18px" }}
              disabled={exportable.length === 0 || busy}
              onClick={handleExport}
            >
              <Icon name="dl" /> {busy ? "Đang chốt xuất..." : `Chốt xuất kế toán (${exportable.length} hóa đơn)`}
            </button>
          </div>
        </div>

        <div className="ecol">
          <div className="cd" style={{ flex: 1.25 }}>
            <div className="ch">
              <div>
                <div className="ct">Hóa đơn sẽ xuất</div>
                <div className="cs" id="ePrevT">
                  Xem trước · {Math.min(7, exportable.length)}/{exportable.length} hóa đơn
                </div>
              </div>
            </div>
            <div className="cb scr" id="ePrev" style={{ padding: "10px 0 0", overflow: "auto" }}>
              {exportable.length === 0 ? (
                <div className="empty">
                  <Icon name="inbox" />
                  Không có hóa đơn đã phê duyệt chờ xuất
                </div>
              ) : (
                <table className="dt" style={{ fontSize: "12.5px" }}>
                  <thead>
                    <tr>
                      <th>Số HĐ</th>
                      <th>Ngày</th>
                      <th>Nhà cung cấp</th>
                      <th>MST</th>
                      <th className="r">Tổng thanh toán</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exportable.slice(0, 7).map((inv) => (
                      <tr key={inv.id}>
                        <td>#{inv.invoice_number || inv.id}</td>
                        <td>{inv.issue_date || "—"}</td>
                        <td>{inv.supplier_name || "—"}</td>
                        <td>{inv.supplier_tax_id || "—"}</td>
                        <td className="r">
                          <b>{fmt(inv.amount_payable)}</b>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="cd" style={{ flex: 1 }}>
            <div className="ch">
              <div className="ct">Lô đã chốt trong phiên</div>
            </div>
            <div className="cb scr" id="eHist" style={{ paddingTop: "6px" }}>
              {history.length === 0 ? (
                <div className="empty" style={{ padding: "20px" }}>
                  <Icon name="inbox" />
                  Chưa chốt lô xuất nào trong phiên này
                </div>
              ) : (
                history.map((h) => (
                  <div key={h.name} className="hrow">
                    <Icon name="xls" />
                    <div>
                      <b>{h.name}</b>
                      <small>
                        {h.rows} hóa đơn · {(h.size / 1024).toFixed(1)} KB · {h.time} · SHA-256 {h.sha256.slice(0, 12)}…
                      </small>
                    </div>
                    <button className="bt s" onClick={() => saveBlob(h.blob, h.name)}>
                      <Icon name="dl" /> Tải lại
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
};
