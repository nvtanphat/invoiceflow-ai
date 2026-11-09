import React from "react";
import { Icon } from "../../components/SvgIcons";
import { InvoiceLineItem } from "../../lib/api-client";

interface LineItemsSectionProps {
  linesCount: number;
  isOpen: boolean;
  onToggle: () => void;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: () => void;
  editLines: InvoiceLineItem[];
  setEditLines: React.Dispatch<React.SetStateAction<InvoiceLineItem[]>>;
  hasArithmeticMismatch: boolean;
  onHoverLine?: (line: number | null) => void;
}

const fmt = (n: number | string) => {
  const num = typeof n === "string" ? parseFloat(n) || 0 : n;
  return Math.round(num).toLocaleString("en-US");
};

export const LineItemsSection: React.FC<LineItemsSectionProps> = ({
  linesCount,
  isOpen,
  onToggle,
  isEditing,
  onStartEdit,
  onCancelEdit,
  onSave,
  editLines,
  setEditLines,
  hasArithmeticMismatch,
  onHoverLine,
}) => {
  return (
    <div className={`sec s2 ${isOpen ? "" : "cl"}`}>
      <div className="sh" onClick={onToggle}>
        <Icon name={isOpen ? "chu" : "chd"} className="chv" />
        <h3>Danh sách dòng hàng ({linesCount})</h3>
        {isEditing || hasArithmeticMismatch ? (
          <div className="editbar" onClick={(e) => e.stopPropagation()}>
            {isEditing && (
              <div className="edit" onClick={onCancelEdit}>
                Hủy
              </div>
            )}
            <button
              type="button"
              className="edit on"
              style={{ border: "none" }}
              onClick={onSave}
            >
              <Icon name="check" /> Lưu bản đính chính
            </button>
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
        Chi tiết từng dòng sản phẩm / dịch vụ và kiểm tra khớp số học
      </div>

      {isOpen && (
        <div className="lt">
          <div className="lr hd">
            <div>#</div>
            <div>Mã hàng</div>
            <div>Mô tả</div>
            <div>Số lượng</div>
            <div>Đơn giá</div>
            <div></div>
            <div>Thành tiền</div>
            <div></div>
          </div>
          {editLines.map((l, i) => {
            const isMismatch =
              Math.abs(
                (parseFloat(l.qty) || 0) * (parseFloat(l.unit_price) || 0) -
                  (parseFloat(l.line_amount) || 0)
              ) > 1.0;
            const canEdit = isEditing || hasArithmeticMismatch;
            return (
              <div
                key={l.id || i}
                className="lr rw"
                onMouseEnter={() => onHoverLine?.(i)}
                onMouseLeave={() => onHoverLine?.(null)}
                style={{ cursor: "pointer" }}
              >
                <div>{i + 1}</div>
                <div>{l.sku_ref || `SP-${i + 1}`}</div>
                <div>{l.description}</div>
                <div>
                  {canEdit ? (
                    <input
                      className="inp sm"
                      value={l.qty}
                      onChange={(e) => {
                        const val = e.target.value;
                        setEditLines((prev) => {
                          const copy = [...prev];
                          copy[i].qty = val;
                          return copy;
                        });
                      }}
                    />
                  ) : (
                    parseFloat(l.qty || "0").toFixed(4)
                  )}
                </div>
                <div>
                  {canEdit ? (
                    <input
                      className="inp sm"
                      value={l.unit_price}
                      onChange={(e) => {
                        const val = e.target.value;
                        setEditLines((prev) => {
                          const copy = [...prev];
                          copy[i].unit_price = val;
                          return copy;
                        });
                      }}
                    />
                  ) : (
                    fmt(l.unit_price)
                  )}
                </div>
                <div></div>
                <div>
                  {canEdit ? (
                    <input
                      className="inp sm"
                      data-testid={`input-line-amount-${i + 1}`}
                      value={l.line_amount}
                      onChange={(e) => {
                        const val = e.target.value;
                        setEditLines((prev) => {
                          const copy = [...prev];
                          copy[i].line_amount = val;
                          return copy;
                        });
                      }}
                    />
                  ) : (
                    fmt(l.line_amount)
                  )}
                </div>
                <div className={`cc ${isMismatch ? "amb" : ""}`}>
                  <Icon name={isMismatch ? "alert" : "check"} />
                </div>
              </div>
            );
          })}

          {(isEditing || hasArithmeticMismatch) && (
            <div style={{ padding: "12px 14px", textAlign: "right" }}>
              <button type="button" className="bt p s" onClick={onSave}>
                <Icon name="check" /> Lưu bản đính chính
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
