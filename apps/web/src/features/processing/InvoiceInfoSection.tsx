import React from "react";
import { Icon } from "../../components/SvgIcons";
import { ExtendedInvoiceItem } from "../../lib/seed-data";

interface InvoiceInfoSectionProps {
  inv: ExtendedInvoiceItem;
  isOpen: boolean;
  onToggle: () => void;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: () => void;
  editMst: string;
  setEditMst: (v: string) => void;
  editNo: string;
  setEditNo: (v: string) => void;
  editDate: string;
  setEditDate: (v: string) => void;
  onHoverField?: (field: string | null) => void;
}

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const InvoiceInfoSection: React.FC<InvoiceInfoSectionProps> = ({
  inv,
  isOpen,
  onToggle,
  isEditing,
  onStartEdit,
  onCancelEdit,
  onSave,
  editMst,
  setEditMst,
  editNo,
  setEditNo,
  editDate,
  setEditDate,
  onHoverField,
}) => {
  const isBadMst =
    inv.tax_authority_status === "INACTIVE" ||
    inv.tax_authority_status === "inactive" ||
    inv.tax_authority_status === "invalid";

  const getFieldEvidence = (name: string) => {
    return (inv.evidence || []).find(
      (e) => e.field_name === name || e.field_name.toLowerCase().includes(name.toLowerCase())
    );
  };

  const mstEv = getFieldEvidence("supplier_tax_id") || getFieldEvidence("tax_id");
  const noEv = getFieldEvidence("invoice_number");
  const dateEv = getFieldEvidence("issue_date") || getFieldEvidence("date");

  return (
    <div className={`sec s1 ${isOpen ? "" : "cl"}`}>
      <div className="sh" onClick={onToggle}>
        <Icon name={isOpen ? "chu" : "chd"} className="chv" />
        <h3>Thông tin hóa đơn</h3>
        <span style={{ fontSize: "12px", color: "var(--muted)", marginLeft: "8px" }}>
          Hóa đơn #{inv.invoice_number || inv.id} (Rev v{inv.revision})
        </span>
        {isEditing ? (
          <div className="editbar" onClick={(e) => e.stopPropagation()}>
            <div className="edit" onClick={onCancelEdit}>
              Hủy
            </div>
            <div className="edit on" onClick={onSave}>
              <Icon name="check" /> Lưu
            </div>
          </div>
        ) : (
          <div
            className="edit"
            onClick={(e) => {
              e.stopPropagation();
              onStartEdit();
            }}
          >
            <Icon name="edit" /> Chỉnh sửa
          </div>
        )}
      </div>

      <div style={{ fontSize: "11.5px", color: "var(--muted)", padding: "0 14px 6px" }}>
        Dữ liệu trường thông tin hóa đơn trích xuất từ tài liệu gốc
      </div>

      {isOpen && (
        <div className="irows">
          <div
            className="row"
            onMouseEnter={() => onHoverField?.("mst")}
            onMouseLeave={() => onHoverField?.(null)}
            style={{ cursor: "pointer" }}
          >
            <Icon name="building" />
            <span className="l">MST nhà cung cấp</span>
            {isEditing ? (
              <input
                className="inp sm"
                value={editMst}
                onChange={(e) => setEditMst(e.target.value)}
              />
            ) : (
              <span className="v">{inv.supplier_tax_id || "—"}</span>
            )}
            {isBadMst ? (
              <span className="pill a">
                <Icon name="alert" /> MST lỗi
              </span>
            ) : (
              <span className="pill g">
                <Icon name="check" /> {mstEv ? `${Math.round((mstEv.confidence ?? 1.0) * 100)}%` : "100%"}
              </span>
            )}
          </div>

          <div
            className="row"
            onMouseEnter={() => onHoverField?.("no")}
            onMouseLeave={() => onHoverField?.(null)}
            style={{ cursor: "pointer" }}
          >
            <Icon name="shield" />
            <span className="l">Số hóa đơn</span>
            {isEditing ? (
              <input
                className="inp sm"
                value={editNo}
                onChange={(e) => setEditNo(e.target.value)}
              />
            ) : (
              <span className="v">{inv.invoice_number || "—"}</span>
            )}
            <span className="pill g">
              <Icon name="check" /> {noEv ? `${Math.round((noEv.confidence ?? 1.0) * 100)}%` : "100%"}
            </span>
          </div>

          <div
            className="row"
            onMouseEnter={() => onHoverField?.("date")}
            onMouseLeave={() => onHoverField?.(null)}
            style={{ cursor: "pointer" }}
          >
            <Icon name="cal" />
            <span className="l">Ngày lập</span>
            {isEditing ? (
              <input
                className="inp sm"
                value={editDate}
                onChange={(e) => setEditDate(e.target.value)}
              />
            ) : (
              <span className="v">{inv.issue_date || "—"}</span>
            )}
            <span className="pill g">
              <Icon name="check" /> {dateEv ? `${Math.round((dateEv.confidence ?? 1.0) * 100)}%` : "100%"}
            </span>
          </div>

          <div
            className="row"
            onMouseEnter={() => onHoverField?.("total")}
            onMouseLeave={() => onHoverField?.(null)}
            style={{ cursor: "pointer" }}
          >
            <Icon name="layers" />
            <span className="l">Tổng thanh toán</span>
            <span className="v">{fmt(inv.amount_payable)} VND</span>
            <span className="pill p">
              <Icon name="check" /> Đối soát
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
