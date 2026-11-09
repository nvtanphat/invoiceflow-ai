import React, { useState, useRef, useEffect, useCallback } from "react";
import { Icon } from "../../components/SvgIcons";
import { useInvoiceFlow } from "../../context/InvoiceFlowContext";
import { api } from "../../lib/api-client";

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const DocumentViewer: React.FC = () => {
  const {
    documents,
    selectedDocId,
    selectedInvoice,
    highlightedField,
    setHighlightedField,
    setActivePage,
    showToast,
  } = useInvoiceFlow();

  const [zoom, setZoom] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [scale, setScale] = useState(1);
  const [leftOffset, setLeftOffset] = useState(0);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [pageImageUrl, setPageImageUrl] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const curDoc = documents.find((d) => d.id === selectedDocId);
  const inv = selectedInvoice;

  // Zoom steps
  const Z = [0.5, 0.75, 1, 1.25, 1.5, 2];
  const zoomIn = () => {
    const idx = Z.indexOf(zoom);
    if (idx < Z.length - 1) setZoom(Z[idx + 1]);
  };
  const zoomOut = () => {
    const idx = Z.indexOf(zoom);
    if (idx > 0) setZoom(Z[idx - 1]);
  };

  // Auto-fit document inside pagewrap
  const fitPage = useCallback(() => {
    const wrap = wrapRef.current;
    if (!wrap || !wrap.clientWidth) return;
    const k = Math.max(0.5, Math.min(wrap.clientWidth / 566, wrap.clientHeight / 678)) * zoom;
    setScale(k);
    setLeftOffset(Math.max(0, (wrap.clientWidth - 562 * k) / 2));
  }, [zoom]);

  useEffect(() => {
    fitPage();
    window.addEventListener("resize", fitPage);
    const ro = window.ResizeObserver ? new ResizeObserver(fitPage) : null;
    if (ro && wrapRef.current) ro.observe(wrapRef.current);
    return () => {
      window.removeEventListener("resize", fitPage);
      ro?.disconnect();
    };
  }, [fitPage]);

  // Attempt real page rendering for uploaded documents
  useEffect(() => {
    let active = true;
    if (!curDoc) {
      setPageImageUrl(null);
      return;
    }
    api.renderDocumentPage(curDoc.id, 0)
      .then((res) => {
        if (active) setPageImageUrl(res.blobUrl);
      })
      .catch(() => {
        if (active) setPageImageUrl(null);
      });
    return () => {
      active = false;
    };
  }, [curDoc?.id]);

  // Close popup menu on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as HTMLElement)) {
        setIsMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const handleDownloadJson = () => {
    if (!inv) {
      showToast("Chưa có dữ liệu trích xuất để tải.", "warn");
      return;
    }
    const blob = new Blob([JSON.stringify(inv, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${curDoc?.filename || "invoice"}.json`;
    a.click();
    showToast(`Đã tải xuống ${curDoc?.filename || "invoice"}.json`);
  };

  const handleCopyDocId = () => {
    if (curDoc) {
      navigator.clipboard.writeText(curDoc.id);
      showToast(`Đã sao chép mã chứng từ: ${curDoc.id}`);
      setIsMenuOpen(false);
    }
  };

  const subtotal = inv ? parseFloat(inv.subtotal) || 0 : 0;
  const taxTotal = inv ? parseFloat(inv.tax_total) || 0 : 0;
  const amountPayable = inv ? parseFloat(inv.amount_payable) || 0 : 0;

  const isProcessing =
    curDoc?.status === "PROCESSING" ||
    (curDoc && curDoc.status === "PENDING" && !inv);

  return (
    <section className={`mid ${isFullscreen ? "fs" : ""}`} id="mid">
      <div className="mh">
        <span className="fn" id="docName">
          {curDoc?.filename || "Chưa chọn chứng từ"}
        </span>
        <span className="badge" id="docType">
          Hóa đơn GTGT
        </span>
        <span className="pg" id="docPg">
          1 / 1 trang
        </span>

        <div className="tools" style={{ position: "relative" }}>
          <div className="tb zoom">
            <span className="zi" onClick={zoomOut} title="Thu nhỏ">
              <Icon name="minus" />
            </span>
            <span id="zval">{Math.round(zoom * 100)}%</span>
            <span className="zi" onClick={zoomIn} title="Phóng to">
              <Icon name="plus" />
            </span>
          </div>

          <div
            className="tb"
            title="Toàn màn hình"
            onClick={() => setIsFullscreen(!isFullscreen)}
          >
            <Icon name="max" />
          </div>

          <span className="gap"></span>

          <div className="tb" title="Tải dữ liệu JSON" onClick={handleDownloadJson}>
            <Icon name="dl" />
          </div>

          <div
            ref={menuRef}
            className="tb"
            title="Thao tác chứng từ"
            onClick={() => setIsMenuOpen(!isMenuOpen)}
          >
            <Icon name="dots" />
            {isMenuOpen && (
              <div
                className="menu"
                style={{
                  top: "36px",
                  right: "0px",
                  zIndex: 100,
                  width: "190px",
                  textAlign: "left",
                }}
              >
                <div className="mi" onClick={handleCopyDocId}>
                  <Icon name="copy" />
                  <span>Sao chép mã HĐ</span>
                </div>
                <div
                  className="mi"
                  onClick={() => {
                    setActivePage("doi-soat");
                    setIsMenuOpen(false);
                  }}
                >
                  <Icon name="layers" />
                  <span>Mở đối soát 3-Way</span>
                </div>
                <div
                  className="mi"
                  onClick={() => {
                    setActivePage("phe-duyet");
                    setIsMenuOpen(false);
                  }}
                >
                  <Icon name="approve" />
                  <span>Trình phê duyệt</span>
                </div>
                <div className="msep"></div>
                <div className="mi" onClick={handleDownloadJson}>
                  <Icon name="dl" />
                  <span>Tải tệp JSON</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="view">
        {/* Thumbnails Sidebar */}
        <div className="thumbs">
          <div className="th">
            <svg viewBox="0 0 78 104" aria-hidden="true">
              <rect width="78" height="104" fill="#fff" />
              <rect x="6" y="8" width="14" height="10" rx="2" fill="#2457c5" />
              <rect x="26" y="10" width="40" height="3" rx="1.5" fill="#9aa3b2" />
              <rect x="26" y="16" width="30" height="2" rx="1" fill="#c3c9d4" />
              <rect x="6" y="26" width="30" height="2.5" rx="1.2" fill="#6b7280" />
              <rect x="6" y="31" width="38" height="2" rx="1" fill="#c3c9d4" />
              <rect x="6" y="35" width="22" height="2" rx="1" fill="#c3c9d4" />
              <rect x="50" y="26" width="22" height="2" rx="1" fill="#c3c9d4" />
              <rect x="50" y="31" width="22" height="2" rx="1" fill="#c3c9d4" />
              <rect x="50" y="36" width="22" height="2" rx="1" fill="#c3c9d4" />
              <rect x="6" y="46" width="66" height="1.5" fill="#e1e5ec" />
              <rect x="6" y="52" width="40" height="2" rx="1" fill="#c3c9d4" />
              <rect x="6" y="57" width="46" height="2" rx="1" fill="#c3c9d4" />
              <g fill="none" stroke="#c9ceda" strokeWidth="1">
                <rect x="5.5" y="66.5" width="67" height="22" />
                <path d="M5.5 72.5h67M5.5 80.5h67M18.5 66.5v22M34.5 66.5v22M48.5 66.5v22M60.5 66.5v22" />
              </g>
              <rect x="44" y="93" width="28" height="2" rx="1" fill="#c3c9d4" />
            </svg>
          </div>
          <div className="thn">1</div>
        </div>

        {/* Page Render Canvas with Responsive Fit */}
        <div className="pagewrap" id="pagewrap" ref={wrapRef}>
          <div
            className="page"
            id="docPage"
            style={{
              transform: `scale(${scale})`,
              transformOrigin: "0 0",
              left: `${leftOffset}px`,
              position: "relative",
            }}
          >
            {isProcessing ? (
              /* Processing Animation State */
              <div style={{ padding: "40px 24px", textAlign: "center", color: "#6b7588" }}>
                <div className="sk" style={{ height: "48px", marginBottom: "18px" }}></div>
                <div className="sk" style={{ height: "190px", marginBottom: "18px" }}></div>
                <div className="sk" style={{ height: "140px" }}></div>
                <div className="qmsg" style={{ top: "310px" }}>
                  <Icon name="spark" style={{ width: "32px", height: "32px", color: "var(--blue)", margin: "0 auto 8px" }} />
                  <div style={{ fontWeight: 600, color: "var(--navy)", fontSize: "15px" }}>
                    Đang xử lý Document AI...
                  </div>
                  <div style={{ fontSize: "13px", marginTop: "4px" }}>
                    Hệ thống đang chạy OCR đa tầng, phân tích bảng Docling và đối soát 3-Way.
                  </div>
                </div>
              </div>
            ) : pageImageUrl ? (
              /* Real Document PNG Page Render */
              <div style={{ position: "relative", width: "100%", height: "100%" }}>
                <img
                  src={pageImageUrl}
                  alt="Trang hóa đơn"
                  style={{ width: "100%", height: "auto", display: "block", borderRadius: "4px" }}
                />
                {/* Overlay Evidence BBoxes if available */}
                {inv?.evidence?.map((ev, idx) => {
                  try {
                    const bb = JSON.parse(ev.bbox_json);
                    const isHi = highlightedField === ev.field_name;
                    return (
                      <div
                        key={idx}
                        title={`${ev.field_name}: ${(ev.confidence * 100).toFixed(1)}%`}
                        onClick={() => setHighlightedField(ev.field_name)}
                        style={{
                          position: "absolute",
                          left: `${bb.x}px`,
                          top: `${bb.y}px`,
                          width: `${bb.w}px`,
                          height: `${bb.h}px`,
                          border: isHi ? "2px solid #ff4d4f" : "1.5px dashed rgba(26,102,242,.7)",
                          background: isHi ? "rgba(255,77,79,.15)" : "rgba(26,102,242,.08)",
                          cursor: "pointer",
                          transition: "all .2s ease",
                        }}
                      />
                    );
                  } catch {
                    return null;
                  }
                })}
              </div>
            ) : inv ? (
              /* High-Fidelity SVG Interactive Invoice Document */
              <>
                {/* Logo badge */}
                <svg
                  className="a"
                  style={{ left: "35px", top: "44px" }}
                  width="72"
                  height="64"
                  viewBox="0 0 72 64"
                  aria-hidden="true"
                >
                  <rect x="2" y="2" width="60" height="60" rx="15" fill="#1a66f2" />
                  <circle cx="50" cy="14" r="12" fill="#5fa4f9" opacity=".92" />
                  <text
                    x="32"
                    y="42"
                    textAnchor="middle"
                    fontFamily="Inter,sans-serif"
                    fontWeight="800"
                    fontSize="24"
                    fill="#fff"
                  >
                    HĐ
                  </text>
                </svg>

                {/* Header Title */}
                <div
                  className="a b"
                  data-f="type"
                  style={{
                    left: "214px",
                    top: "58px",
                    fontSize: "21px",
                    letterSpacing: "-.2px",
                    lineHeight: "26px",
                  }}
                >
                  HÓA ĐƠN GIÁ TRỊ GIA TĂNG
                </div>

                {/* Seller info */}
                <div
                  className={`a b ${highlightedField === "supplier" ? "flash" : ""}`}
                  onClick={() => setHighlightedField("supplier")}
                  style={{
                    left: "23px",
                    top: "134px",
                    fontSize: "15px",
                    lineHeight: "22px",
                    maxWidth: "368px",
                    cursor: "pointer",
                  }}
                >
                  {inv.supplier_name || "CÔNG TY CỔ PHẦN CUNG CẤP DỊCH VỤ"}
                </div>
                <div
                  className="a"
                  style={{
                    left: "23px",
                    top: "163px",
                    maxWidth: "368px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  Địa chỉ: Số 123 Đường Lê Lợi, Quận 1, TP. Hồ Chí Minh
                </div>
                <div
                  className="a"
                  style={{ left: "23px", top: "187px", fontSize: "13.7px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("mst")}
                >
                  MST:{" "}
                  <span
                    className={`ul b ${highlightedField === "mst" ? "flash" : ""}`}
                    data-f="mst"
                    style={{
                      fontWeight: 600,
                      fontSize: "14.3px",
                      padding: "1px 4px",
                      borderRadius: "3px",
                    }}
                  >
                    {inv.supplier_tax_id || "0312345678"}
                  </span>
                </div>

                {/* Invoice Meta */}
                <div className="a" style={{ left: "397px", top: "130px" }}>
                  Mẫu số: 01GTKT0/001
                </div>
                <div
                  className={`a ${highlightedField === "serial" ? "flash" : ""}`}
                  style={{ left: "397px", top: "154px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("serial")}
                  data-f="serial"
                >
                  Ký hiệu: <b>{inv.invoice_series || "AA/26E"}</b>
                </div>
                <div
                  className="a"
                  style={{ left: "397px", top: "178px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("no")}
                >
                  Số:{" "}
                  <span
                    className={`hl ${highlightedField === "no" ? "flash" : ""}`}
                    data-f="no"
                    style={{ fontWeight: 600, marginLeft: "1px", padding: "1px 4px", borderRadius: "3px" }}
                  >
                    {inv.invoice_number || "0001234"}
                  </span>
                </div>
                <div
                  className={`a ${highlightedField === "date" ? "flash" : ""}`}
                  style={{ left: "397px", top: "203px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("date")}
                  data-f="date"
                >
                  Ngày lập: <b>{inv.issue_date || "09/11/2026"}</b>
                </div>

                <div
                  className="a"
                  style={{
                    left: "23px",
                    top: "227px",
                    width: "516px",
                    height: "1px",
                    background: "#d8dce4",
                  }}
                ></div>

                {/* Buyer info */}
                <div
                  className={`a ${highlightedField === "buyer" ? "flash" : ""}`}
                  style={{ left: "23px", top: "240px", fontSize: "13.7px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("buyer")}
                  data-f="buyer"
                >
                  Tên người mua hàng: <b>{inv.buyer_name || "Công ty Cổ phần Thương mại Alpha VN"}</b>
                </div>
                <div className="a" style={{ left: "23px", top: "265px" }}>
                  Địa chỉ: 456 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh
                </div>
                <div
                  className={`a ${highlightedField === "bmst" ? "flash" : ""}`}
                  style={{ left: "23px", top: "289px", fontSize: "13.7px", cursor: "pointer" }}
                  onClick={() => setHighlightedField("bmst")}
                  data-f="bmst"
                >
                  MST:{" "}
                  <b style={{ fontSize: "14.3px" }}>
                    {inv.buyer_tax_id || "0309876543"}
                  </b>
                </div>

                {/* Line Items Table */}
                <div className="lower">
                  <table>
                    <colgroup>
                      <col style={{ width: "32px" }} />
                      <col style={{ width: "88px" }} />
                      <col style={{ width: "133px" }} />
                      <col style={{ width: "48px" }} />
                      <col style={{ width: "71px" }} />
                      <col style={{ width: "76px" }} />
                      <col style={{ width: "84px" }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>STT</th>
                        <th>Mã hàng</th>
                        <th>Tên hàng hóa, dịch vụ</th>
                        <th>ĐVT</th>
                        <th>Số lượng</th>
                        <th>Đơn giá</th>
                        <th>Thành tiền</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(inv.lines || []).map((l, i) => {
                        const isLineHi = highlightedField === `line-${i}` || highlightedField === "lines";
                        return (
                          <tr
                            key={l.id || i}
                            className={isLineHi ? "flash" : ""}
                            onClick={() => setHighlightedField(`line-${i}`)}
                            style={{ cursor: "pointer" }}
                          >
                            <td className="c">{i + 1}</td>
                            <td>{l.sku_ref || `SP-${i + 1}`}</td>
                            <td>{l.description}</td>
                            <td className="c">{l.unit || "Chiếc"}</td>
                            <td className="r">{parseFloat(l.qty || "0").toFixed(4)}</td>
                            <td className="r">{fmt(l.unit_price || 0)}</td>
                            <td className="r">{fmt(l.line_amount || 0)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  {/* Summary Totals */}
                  <div className="tt">
                    <div
                      className={`tot ${highlightedField === "sub" ? "flash" : ""}`}
                      onClick={() => setHighlightedField("sub")}
                      style={{ cursor: "pointer" }}
                    >
                      <span>Cộng tiền hàng:</span>
                      <b data-f="sub">{fmt(subtotal)}</b>
                    </div>
                    <div
                      className={`tot ${highlightedField === "vat" ? "flash" : ""}`}
                      onClick={() => setHighlightedField("vat")}
                      style={{ cursor: "pointer" }}
                    >
                      <span data-f="vat">Thuế GTGT:</span>
                      <b data-f="vatamt">{fmt(taxTotal)}</b>
                    </div>
                    <div
                      className={`grand ${highlightedField === "total" ? "flash" : ""}`}
                      onClick={() => setHighlightedField("total")}
                      data-f="total"
                      style={{ cursor: "pointer" }}
                    >
                      <span>Tổng thanh toán:</span>
                      <span>{fmt(amountPayable)}</span>
                    </div>
                  </div>

                  {/* Digital Signature Footer */}
                  <div
                    style={{
                      marginTop: "16px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      border: "1px dashed #c8d3e6",
                      borderRadius: "6px",
                      background: "#fafbfd",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <Icon name="shield" style={{ width: "16px", height: "16px", color: "var(--green)" }} />
                      <span style={{ fontSize: "11.5px", color: "var(--navy)", fontWeight: 600 }}>
                        Ký điện tử bởi: {inv.supplier_name}
                      </span>
                    </div>
                    <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                      Ngày ký: {inv.issue_date || "09/11/2026"} · Hợp lệ CQT
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <div style={{ padding: "40px", textAlign: "center", color: "#6b7588" }}>
                <Icon name="inbox" style={{ width: "36px", height: "36px", margin: "0 auto 12px" }} />
                <div>Vui lòng chọn chứng từ để xem nội dung</div>
              </div>
            )}
          </div>
          <div className="track" id="track" style={{ display: zoom === 1 ? "block" : "none" }}></div>
        </div>
      </div>
    </section>
  );
};
