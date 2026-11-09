import React from "react";
import { Icon } from "../../components/SvgIcons";
import { ExtendedInvoiceItem } from "../../lib/seed-data";

interface InvoiceAuditSectionProps {
  inv: ExtendedInvoiceItem;
  isOpen: boolean;
  onToggle: () => void;
  onOpenMatching: () => void;
}

export const InvoiceAuditSection: React.FC<InvoiceAuditSectionProps> = ({
  inv,
  isOpen,
  onToggle,
  onOpenMatching,
}) => {
  const isBadMst = inv.id === "CASE-05" || inv.tax_authority_status === "INACTIVE";
  const isMismatch =
    inv.id === "CASE-07" ||
    inv.id === "CASE-09" ||
    inv.status === "REVIEW_REQUIRED";
  const isOk = !isBadMst && !isMismatch;

  return (
    <div className={`sec s3 ${isOpen ? "" : "cl"}`}>
      <div className="sh" onClick={onToggle}>
        <Icon name={isOpen ? "chu" : "chd"} className="chv" />
        <h3>Kiểm tra &amp; đối soát</h3>
        {isOk ? (
          <span className="pill g">
            <Icon name="check" /> Hợp lệ
          </span>
        ) : (
          <span className="pill a">
            <Icon name="alert" /> {isBadMst ? "MST lỗi" : "Cần rà soát"}
          </span>
        )}
      </div>

      {isOpen && (
        <div>
          <div className="ck">
            <span className={`cc ${inv.signature_status === "INVALID" ? "red" : ""}`}>
              <Icon name={inv.signature_status === "INVALID" ? "x" : "check"} />
            </span>
            <div>
              Chữ ký số: {inv.signature_status === "INVALID" ? "Không hợp lệ" : "Hợp lệ"}
              <small>Xác thực mã băm chữ ký điện tử VNPT-CA / Viettel-CA</small>
            </div>
          </div>

          <div className="ck">
            <span className={`cc ${isBadMst ? "red" : ""}`}>
              <Icon name={isBadMst ? "x" : "check"} />
            </span>
            <div>
              Tổng cục Thuế: {isBadMst ? "MST không tồn tại / Ngừng HĐ" : "Đang hoạt động"}
              <small>Tra cứu cơ sở dữ liệu Doanh nghiệp NNT của Tổng cục Thuế</small>
            </div>
          </div>

          <div className="ck">
            <span className="cc">
              <Icon name="check" />
            </span>
            <div>
              Kiểm tra trùng lặp: Đạt
              <small>
                Số hóa đơn duy nhất trong kỳ: {inv.invoice_series || "—"} – {inv.invoice_number || "—"}
              </small>
            </div>
          </div>

          <div className="ck">
            <span className={`cc ${isMismatch ? "red" : ""}`}>
              <Icon name={isMismatch ? "alert" : "check"} />
            </span>
            <div>
              Đối soát 3-Way (PO – GRN – HĐ): {isMismatch ? "Phát hiện chênh lệch" : "Khớp 100%"}
              <small>
                {inv.id === "CASE-07"
                  ? "Lệch số lượng: HĐ 120 ream vs GRN 100 ream"
                  : inv.id === "CASE-09"
                  ? "Lệch đơn giá: HĐ 4.2M vs PO 4.0M (+5.0%)"
                  : "Khớp số lượng và đơn giá trong dung sai ±2%"}
              </small>
            </div>
          </div>

          <div
            className="ck-link"
            style={{ cursor: "pointer", padding: "10px 14px", display: "flex", alignItems: "center", gap: "6px", color: "var(--blue)", fontWeight: 600, fontSize: "12.5px" }}
            onClick={onOpenMatching}
          >
            <span>Xem chi tiết đối soát 3-Way</span>
            <Icon name="arrowr" style={{ width: "14px", height: "14px" }} />
          </div>
        </div>
      )}
    </div>
  );
};
