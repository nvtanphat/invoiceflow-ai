import React, { useState } from "react";
import { FieldDecision, ReviewItem } from "../../lib/api-client";

interface FieldReviewSectionProps {
  items: ReviewItem[];
  readOnly: boolean;
  onResolve: (fieldPath: string, decision: FieldDecision, value?: string) => Promise<boolean>;
  onHighlight: (fieldPath: string | null) => void;
}

// Lists only the fields the backend still blocks on; each is settled on its own against
// the source document. Nothing changes locally until the API confirms the decision.
export const FieldReviewSection: React.FC<FieldReviewSectionProps> = ({
  items,
  readOnly,
  onResolve,
  onHighlight,
}) => {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busyField, setBusyField] = useState<string | null>(null);

  if (items.length === 0) return null;

  const resolve = async (fieldPath: string, decision: FieldDecision, value?: string) => {
    setBusyField(fieldPath);
    try {
      await onResolve(fieldPath, decision, value);
    } finally {
      setBusyField(null);
    }
  };

  return (
    <div data-testid="field-review" style={{ marginBottom: "14px" }}>
      <div style={{ fontWeight: 600, fontSize: "13px", color: "var(--navy)", marginBottom: "8px" }}>
        Trường cần xác nhận ({items.length})
      </div>
      {items.map((item) => {
        const busy = busyField === item.field_path;
        const draft = drafts[item.field_path] ?? "";
        const disabled = readOnly || busy;
        return (
          <div
            key={item.field_path}
            data-testid={`review-item-${item.field_path}`}
            className="ev"
            onMouseEnter={() => onHighlight(item.field_path)}
            onMouseLeave={() => onHighlight(null)}
            style={{ padding: "10px 12px", border: "1px solid #fcd34d", borderRadius: "8px", marginBottom: "8px", background: "#fffbeb" }}
          >
            <div style={{ fontWeight: 600, fontSize: "13px" }}>{item.field_path}</div>
            <div style={{ fontSize: "12px", margin: "4px 0" }}>
              Giá trị hiện tại: <b>{item.current_value ?? "—"}</b>
              {item.source_kind ? ` · ${item.source_kind}` : ""}
            </div>
            {item.candidate_value !== null && (
              <div style={{ fontSize: "12px", margin: "4px 0", color: "#b91c1c" }}>
                Đề xuất Vision: <b>{item.candidate_value}</b>
              </div>
            )}
            <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "6px" }}>{item.reasons.join(" · ")}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {item.current_value !== null && (
                <button type="button" className="bt s" disabled={disabled} onClick={() => resolve(item.field_path, "accept_extracted")}>
                  Đúng với chứng từ
                </button>
              )}
              {item.candidate_value !== null && (
                <button type="button" className="bt s" disabled={disabled} onClick={() => resolve(item.field_path, "accept_candidate")}>
                  Dùng đề xuất Vision
                </button>
              )}
              <input
                aria-label={`Giá trị đúng cho ${item.field_path}`}
                value={draft}
                disabled={disabled}
                onChange={(e) => setDrafts((prev) => ({ ...prev, [item.field_path]: e.target.value }))}
                style={{ flex: "1 1 120px", fontSize: "12px", padding: "4px 6px" }}
              />
              <button
                type="button"
                className="bt p s"
                disabled={disabled || !draft.trim()}
                onClick={() => resolve(item.field_path, "correct", draft.trim())}
              >
                Sửa
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};
