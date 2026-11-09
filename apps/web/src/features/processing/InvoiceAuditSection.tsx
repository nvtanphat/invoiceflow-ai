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
  const isBadMst =
    inv.tax_authority_status === "INACTIVE" ||
    inv.tax_authority_status === "inactive" ||
    inv.tax_authority_status === "invalid";
  const isSignatureInvalid =
    inv.signature_status === "INVALID" ||
    inv.signature_status === "invalid";
  const hasIssues = Boolean(
    (inv.issues && inv.issues.length > 0) ||
    inv.status === "REVIEW_REQUIRED" ||
    inv.status === "REQUIRES_REVIEW" ||
    inv.status === "DISCREPANCY_DETECTED"
  );
  const isOk = !isBadMst && !hasIssues && !isSignatureInvalid;

  const getTaxStatusLabel = () => {
    if (isBadMst) return "MST không tồn tại / Ngừng HĐ";
    if (inv.tax_authority_status === "not_checked") return "Chưa tra cứu";
    return "Đang hoạt động bình thường (Tổng cục Thuế)";
  };

  const getSignatureLabel = () => {
    if (isSignatureInvalid) return "Không hợp lệ";
    if (inv.signature_status === "unverified") return "Chờ kiểm tra";
    return "Hợp lệ (Chữ ký số hợp chuẩn)";
  };

  const matchingSummary =
    inv.issues && inv.issues.length > 0
      ? inv.issues.map((i) => i.message).join("; ")
      : "Khớp số lượng, đơn giá và thành tiền theo PO/GRN";

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
            <span className={`cc ${isSignatureInvalid ? "red" : ""}`}>
              <Icon name={isSignatureInvalid ? "x" : "check"} />
            </span>
            <div>
              Chữ ký số: {getSignatureLabel()}
              <small>Xác thực mã băm chữ ký điện tử VNPT-CA / Viettel-CA</small>
            </div>
          </div>

          <div className="ck">
            <span className={`cc ${isBadMst ? "red" : ""}`}>
              <Icon name={isBadMst ? "x" : "check"} />
            </span>
            <div>
              Tổng cục Thuế: {getTaxStatusLabel()}
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
            <span className={`cc ${hasIssues ? "red" : ""}`}>
              <Icon name={hasIssues ? "alert" : "check"} />
            </span>
            <div>
              Đối soát 3-Way (PO – GRN – HĐ): {hasIssues ? "Phát hiện chênh lệch" : "Khớp 100%"}
              <small>{matchingSummary}</small>
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
