import React, { useState, useEffect, useRef } from "react";
import { UploadCloud, FileText, CheckCircle2, AlertCircle, Clock, RefreshCw, Eye } from "lucide-react";
import { api, DocumentItem } from "../../lib/api-client";

interface DocumentInboxProps {
  onSelectInvoice: (docId: string) => void;
}

export const DocumentInbox: React.FC<DocumentInboxProps> = ({ onSelectInvoice }) => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = async () => {
    setIsLoading(true);
    try {
      const data = await api.getDocuments();
      setDocuments(data);
    } catch (err: unknown) {
      console.error("Failed to load documents", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    const interval = setInterval(loadDocuments, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 25 * 1024 * 1024) {
      setUploadError("Tệp quá lớn (> 25MB). Giới hạn tối đa là 25MB.");
      return;
    }

    setUploadError(null);
    setIsUploading(true);
    try {
      await api.uploadDocument(file);
      await loadDocuments();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Tải lên thất bại";
      setUploadError(msg);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "PROCESSED":
      case "MATCHED":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">
            <CheckCircle2 className="w-3 h-3" /> Đã hoàn thành
          </span>
        );
      case "READY_FOR_REVIEW":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-sky-100 text-sky-800">
            <Eye className="w-3 h-3" /> Chờ xem xét
          </span>
        );
      case "FAILED":
      case "ERROR":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800">
            <AlertCircle className="w-3 h-3" /> Lỗi xử lý
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 animate-pulse">
            <Clock className="w-3 h-3" /> Đang xử lý...
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload Banner */}
      <div className="border-2 border-dashed border-slate-300 hover:border-sky-500 transition-colors rounded-xl p-8 bg-white text-center shadow-sm">
        <UploadCloud className="w-12 h-12 text-sky-600 mx-auto mb-3" />
        <h3 className="text-base font-semibold text-slate-800">Tải lên hóa đơn điện tử</h3>
        <p className="text-sm text-slate-500 mt-1 max-w-md mx-auto">
          Hỗ trợ định dạng XML Thông tư 78/NĐ 123 và PDF (bản scan hoặc digital). Dung lượng tối đa 25MB.
        </p>

        {uploadError && (
          <div className="mt-3 inline-flex items-center gap-2 text-sm text-rose-600 bg-rose-50 px-3 py-1.5 rounded-md">
            <AlertCircle className="w-4 h-4" /> {uploadError}
          </div>
        )}

        <div className="mt-4">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".xml,.pdf,application/xml,application/pdf"
            className="hidden"
            id="file-upload"
          />
          <label
            htmlFor="file-upload"
            className={`inline-flex items-center px-4 py-2 text-sm font-medium rounded-lg text-white bg-sky-600 hover:bg-sky-700 cursor-pointer shadow-sm transition-all ${
              isUploading ? "opacity-75 cursor-not-allowed" : ""
            }`}
          >
            {isUploading ? "Đang tải lên và quét an toàn..." : "Chọn tệp từ máy tính"}
          </label>
        </div>
      </div>

      {/* Document Queue Table */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50/50">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Hộp thư Hóa đơn & Chứng từ</h2>
            <p className="text-xs text-slate-500 mt-0.5">Danh sách các hóa đơn đầu vào chờ xử lý hoặc đã trích xuất</p>
          </div>
          <button
            onClick={loadDocuments}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded-md border border-slate-200 bg-white hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} /> Làm mới
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600">
            <thead className="bg-slate-50 text-xs uppercase font-semibold text-slate-500 border-b border-slate-200">
              <tr>
                <th className="px-6 py-3.5">Tên tệp</th>
                <th className="px-6 py-3.5">Định dạng</th>
                <th className="px-6 py-3.5">Kích thước</th>
                <th className="px-6 py-3.5">Trạng thái</th>
                <th className="px-6 py-3.5">Thời gian</th>
                <th className="px-6 py-3.5 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {documents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-400">
                    Chưa có tài liệu nào trong hộp thư. Hãy tải lên một hóa đơn XML hoặc PDF để bắt đầu.
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-6 py-4 font-medium text-slate-900 flex items-center gap-3">
                      <FileText className="w-5 h-5 text-sky-600 flex-shrink-0" />
                      <span className="truncate max-w-xs" title={doc.filename}>{doc.filename}</span>
                    </td>
                    <td className="px-6 py-4 font-mono text-xs text-slate-500">
                      {doc.mime_type.includes("xml") ? "XML (TT78)" : "PDF"}
                    </td>
                    <td className="px-6 py-4 text-xs font-mono">{formatFileSize(doc.file_size_bytes)}</td>
                    <td className="px-6 py-4">{getStatusBadge(doc.status)}</td>
                    <td className="px-6 py-4 text-xs text-slate-500">
                      {new Date(doc.created_at).toLocaleString("vi-VN")}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => onSelectInvoice(doc.id)}
                        className="text-xs font-medium text-sky-600 hover:text-sky-800 bg-sky-50 hover:bg-sky-100 px-3 py-1.5 rounded-md transition-colors"
                      >
                        Xem chi tiết
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
