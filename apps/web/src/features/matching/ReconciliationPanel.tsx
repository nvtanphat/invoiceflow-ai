import React, { useState, useEffect } from "react";
import { GitCompare, CheckCircle2, AlertTriangle, XCircle, ArrowLeft, RefreshCw, ShieldAlert } from "lucide-react";
import { api, ReconciliationResult, MatchingIssue } from "../../lib/api-client";

interface ReconciliationPanelProps {
  invoiceId: string;
  onBack: () => void;
}

export const ReconciliationPanel: React.FC<ReconciliationPanelProps> = ({
  invoiceId,
  onBack,
}) => {
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const runReconciliation = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const data = await api.reconcile(invoiceId);
      setResult(data);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Đối soát thất bại");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    runReconciliation();
  }, [invoiceId]);

  const getSeverityBadge = (severity: MatchingIssue["severity"]) => {
    switch (severity) {
      case "ERROR":
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded">
            <XCircle className="w-3 h-3" /> Nghiêm trọng
          </span>
        );
      case "WARNING":
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
            <AlertTriangle className="w-3 h-3" /> Cảnh báo
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
            Thông tin
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header bar */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
            title="Quay lại hóa đơn"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <GitCompare className="w-5 h-5 text-sky-600" />
              <h2 className="text-base font-bold text-slate-900">
                Kết quả đối soát 3 chiều (3-Way Matching: Hóa đơn ↔ PO ↔ GRN)
              </h2>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Tự động kiểm tra đơn giá, số lượng thực nhận tại kho và các chính sách dung sai mua hàng
            </p>
          </div>
        </div>

        <button
          onClick={runReconciliation}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 px-3 py-2 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} /> Chạy lại đối soát
        </button>
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-slate-500 text-sm bg-white rounded-xl border border-slate-200">
          Đang truy vấn đơn hàng (PO), phiếu nhập kho (GRN) và tính toán dung sai...
        </div>
      ) : errorMsg ? (
        <div className="p-6 bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-xl">
          {errorMsg}
        </div>
      ) : result ? (
        <div className="space-y-6">
          {/* Status summary card */}
          <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Trạng thái đối soát</span>
                <div className="mt-1 flex items-center gap-2">
                  {result.is_matched ? (
                    <div className="flex items-center gap-2 text-emerald-700 text-lg font-bold">
                      <CheckCircle2 className="w-6 h-6" /> Khớp hoàn toàn (Matched / Auto-Approved)
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-rose-600 text-lg font-bold">
                      <ShieldAlert className="w-6 h-6" /> Phát hiện sai lệch (Requires Manual Review)
                    </div>
                  )}
                </div>
              </div>

              <div className="text-right">
                <span className="text-xs text-slate-500">Quy tắc phân tách nhiệm vụ (SoD)</span>
                <div className="text-xs font-medium text-slate-800 mt-1">
                  Người duyệt không trùng người tạo chứng từ
                </div>
              </div>
            </div>
          </div>

          {/* Issues table */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50">
              <h3 className="text-sm font-semibold text-slate-900">
                Chi tiết sai lệch & Vi phạm chính sách dung sai ({result.issues.length} mục)
              </h3>
            </div>

            {result.issues.length === 0 ? (
              <div className="p-8 text-center text-emerald-700 text-sm flex items-center justify-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                Không có bất kỳ sai lệch nào. Hóa đơn hoàn toàn khớp với Đơn mua hàng và Phiếu nhập kho.
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {result.issues.map((issue, idx) => (
                  <div key={idx} className="p-4 hover:bg-slate-50 transition-colors flex items-start gap-4 text-xs">
                    <div className="pt-0.5">{getSeverityBadge(issue.severity)}</div>
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-slate-800">{issue.code}</span>
                        {issue.field && (
                          <span className="font-mono text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                            {issue.field}
                          </span>
                        )}
                      </div>
                      <p className="text-slate-700">{issue.message}</p>
                      {(issue.invoice_value || issue.reference_value) && (
                        <div className="flex gap-4 text-[11px] font-mono text-slate-500 pt-1">
                          {issue.invoice_value && <span>Giá trị hóa đơn: <strong className="text-slate-800">{issue.invoice_value}</strong></span>}
                          {issue.reference_value && <span>Giá trị PO/GRN gốc: <strong className="text-slate-800">{issue.reference_value}</strong></span>}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
};
