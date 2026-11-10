import React, { useState } from "react";
import { Download, X, FileSpreadsheet, FileText, Code2, ShieldCheck } from "lucide-react";
import { api } from "../../lib/api-client";

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ExportModal: React.FC<ExportModalProps> = ({ isOpen, onClose }) => {
  const [format, setFormat] = useState<"csv" | "xlsx" | "json">("xlsx");
  const [isExporting, setIsExporting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleDownload = async () => {
    setIsExporting(true);
    setErrorMsg(null);
    try {
      const blob = await api.downloadExport(format);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `invoiceflow_export_${new Date().toISOString().slice(0, 10)}.${format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      onClose();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Xuất tệp thất bại");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Download className="w-5 h-5 text-sky-600" />
            <h3 className="text-base font-bold text-slate-800">Xuất dữ liệu hóa đơn AP</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-100"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-xs text-slate-500">
            Bản xem trước các hóa đơn đã phê duyệt. Tệp này <b>chưa chốt xuất</b>: để hạch toán vào ERP,
            dùng trang "Xuất dữ liệu" để chốt lô (hóa đơn chuyển sang trạng thái Đã xuất, không xuất trùng).
          </p>

          <div className="space-y-2">
            <label
              onClick={() => setFormat("xlsx")}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                format === "xlsx"
                  ? "border-sky-500 bg-sky-50/50 text-sky-900"
                  : "border-slate-200 hover:bg-slate-50 text-slate-700"
              }`}
            >
              <FileSpreadsheet className="w-5 h-5 text-emerald-600 flex-shrink-0" />
              <div>
                <div className="text-xs font-semibold">Microsoft Excel (.xlsx)</div>
                <div className="text-[11px] text-slate-500">Đầy đủ định dạng tiền tệ và các sheet chi tiết</div>
              </div>
            </label>

            <label
              onClick={() => setFormat("csv")}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                format === "csv"
                  ? "border-sky-500 bg-sky-50/50 text-sky-900"
                  : "border-slate-200 hover:bg-slate-50 text-slate-700"
              }`}
            >
              <FileText className="w-5 h-5 text-sky-600 flex-shrink-0" />
              <div>
                <div className="text-xs font-semibold">Chuẩn CSV an toàn (.csv)</div>
                <div className="text-[11px] text-slate-500">
                  Đã làm sạch ký tự độc hại chống CSV Formula Injection (OWASP)
                </div>
              </div>
            </label>

            <label
              onClick={() => setFormat("json")}
              className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                format === "json"
                  ? "border-sky-500 bg-sky-50/50 text-sky-900"
                  : "border-slate-200 hover:bg-slate-50 text-slate-700"
              }`}
            >
              <Code2 className="w-5 h-5 text-purple-600 flex-shrink-0" />
              <div>
                <div className="text-xs font-semibold">Structured JSON (.json)</div>
                <div className="text-[11px] text-slate-500">Dữ liệu dạng API RESTful cho integration pipeline</div>
              </div>
            </label>
          </div>

          <div className="flex items-center gap-1.5 text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-lg border border-slate-100">
            <ShieldCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>Đảm bảo tuân thủ bảo mật dữ liệu doanh nghiệp và số tiền Decimal chuẩn mực.</span>
          </div>

          {errorMsg && (
            <div className="text-xs text-rose-600 bg-rose-50 p-2.5 rounded-lg">
              {errorMsg}
            </div>
          )}
        </div>

        <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800"
          >
            Hủy
          </button>
          <button
            onClick={handleDownload}
            disabled={isExporting}
            className="px-4 py-1.5 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-lg shadow-sm transition-all"
          >
            {isExporting ? "Đang tạo tệp..." : "Tải xuống"}
          </button>
        </div>
      </div>
    </div>
  );
};
