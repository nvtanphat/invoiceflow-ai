import React, { useState, useEffect } from "react";
import { CheckCircle2, XCircle, Save, ArrowLeft, GitCompare, AlertTriangle, ShieldCheck } from "lucide-react";
import { api, InvoiceItem } from "../../lib/api-client";
import { BBoxViewer } from "./BBoxViewer";

interface InvoiceReviewProps {
  invoiceId: string;
  onBack: () => void;
  onOpenReconcile: (invoiceId: string) => void;
}

export const InvoiceReview: React.FC<InvoiceReviewProps> = ({
  invoiceId,
  onBack,
  onOpenReconcile,
}) => {
  const [invoice, setInvoice] = useState<InvoiceItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [selectedField, setSelectedField] = useState<string | null>(null);

  const renderSignatureBadge = (status?: string) => {
    switch (status?.toLowerCase()) {
      case "verified":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            Chữ ký số: Hợp lệ (Verified)
          </span>
        );
      case "unverified":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-amber-50 text-amber-700 border border-amber-200" title="Chữ ký số mật mã đúng nhưng chưa cấu hình CA Trust Anchor">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
            Chữ ký số: Chưa xác thực CA
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-3.5 h-3.5 text-rose-600" />
            Chữ ký số: Không hợp lệ
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-slate-100 text-slate-600 border border-slate-200">
            Chữ ký số: Chưa kiểm
          </span>
        );
    }
  };

  const renderTaxBadge = (status?: string) => {
    switch (status?.toLowerCase()) {
      case "verified":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            Tổng cục Thuế: Đã kiểm chứng
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-3.5 h-3.5 text-rose-600" />
            Tổng cục Thuế: Báo sai
          </span>
        );
      case "unknown":
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-amber-50 text-amber-700 border border-amber-200" title="Cổng Tổng cục Thuế cần credentials hoặc đang bảo trì">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
            Tổng cục Thuế: Chờ đối soát
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-medium bg-slate-100 text-slate-600 border border-slate-200">
            Tổng cục Thuế: Chưa tra cứu
          </span>
        );
    }
  };

  // Form edit state
  const [formData, setFormData] = useState<Partial<InvoiceItem>>({});

  const loadInvoice = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const data = await api.getInvoice(invoiceId);
      setInvoice(data);
      setFormData({
        supplier_tax_id: data.supplier_tax_id,
        supplier_name: data.supplier_name,
        invoice_number: data.invoice_number,
        invoice_series: data.invoice_series,
        issue_date: data.issue_date,
        currency: data.currency,
        subtotal: data.subtotal,
        tax_total: data.tax_total,
        amount_payable: data.amount_payable,
      });
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Không thể tải hóa đơn");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadInvoice();
  }, [invoiceId]);

  const handleAction = async (action: "approve" | "reject" | "correct") => {
    if (!invoice) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const updated = await api.reviewInvoice(
        invoice.id,
        action,
        invoice.revision,
        action === "correct" ? formData : {}
      );
      setInvoice(updated);
      setSuccessMsg(
        action === "approve"
          ? "Hóa đơn đã được phê duyệt thành công!"
          : action === "reject"
          ? "Hóa đơn đã bị từ chối."
          : "Thông tin đính chính đã được lưu và cập nhật phiên bản."
      );
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Thao tác thất bại");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-500 text-sm">
        Đang tải chi tiết hóa đơn và bằng chứng đối soát...
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="p-8 text-center">
        <p className="text-rose-600 mb-4">{errorMsg || "Không tìm thấy hóa đơn"}</p>
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          <ArrowLeft className="w-4 h-4" /> Quay lại danh sách
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top Header */}
      <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
            title="Quay lại danh sách"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">
                Hóa đơn #{invoice.invoice_number || "Chưa có số"} ({invoice.invoice_series || "Series"})
              </h2>
              <span className="text-xs px-2 py-0.5 rounded font-mono bg-slate-100 text-slate-700">
                Rev v{invoice.revision}
              </span>
              {renderSignatureBadge(invoice.signature_status)}
              {renderTaxBadge(invoice.tax_authority_status)}
            </div>
            <p className="text-xs text-slate-500">
              Nhà cung cấp: <span className="font-semibold text-slate-700">{invoice.supplier_name || "N/A"}</span> ({invoice.supplier_tax_id || "N/A"})
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onOpenReconcile(invoice.id)}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
          >
            <GitCompare className="w-4 h-4 text-sky-600" /> Xem 3-Way Matching
          </button>
          <button
            onClick={() => handleAction("reject")}
            disabled={isSubmitting}
            className="inline-flex items-center gap-1 px-3 py-2 text-xs font-medium text-rose-700 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors border border-rose-200"
          >
            <XCircle className="w-4 h-4" /> Từ chối
          </button>
          <button
            onClick={() => handleAction("approve")}
            disabled={isSubmitting}
            className="inline-flex items-center gap-1 px-4 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm transition-all"
          >
            <CheckCircle2 className="w-4 h-4" /> Phê duyệt (Approve)
          </button>
        </div>
      </div>

      {/* Notifications */}
      {errorMsg && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
          <button
            onClick={loadInvoice}
            className="font-medium underline hover:text-rose-900 ml-4"
          >
            Tải lại dữ liệu mới nhất
          </button>
        </div>
      )}

      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-lg flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Dual Pane Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[680px]">
        {/* Left Pane: Ground Truth & BBox Viewer */}
        <div className="lg:col-span-5 h-full">
          <BBoxViewer
            documentId={invoice.document_id}
            documentName={invoice.invoice_number ? `Hóa đơn số ${invoice.invoice_number}` : `Tài liệu ${invoice.document_id.slice(0, 8)}`}
            evidenceList={invoice.evidence || []}
            selectedField={selectedField}
            onSelectField={(f) => setSelectedField(f)}
            isVerifiedSignature={false}
          />
        </div>

        {/* Right Pane: Structured Extraction Form */}
        <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 p-6 shadow-sm flex flex-col justify-between">
          <div className="space-y-6">
            <div className="border-b border-slate-100 pb-3 flex justify-between items-center">
              <h3 className="text-sm font-semibold text-slate-800 uppercase tracking-wider">
                Dữ liệu trường thông tin hóa đơn
              </h3>
              <span className="text-xs text-slate-400">
                Cập nhật có xác thực khóa lạc quan (If-Match)
              </span>
            </div>

            {/* General Fields */}
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <label className="block font-medium text-slate-600 mb-1">Mã số thuế bên bán</label>
                <input
                  type="text"
                  value={formData.supplier_tax_id || ""}
                  onChange={(e) => setFormData({ ...formData, supplier_tax_id: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono text-slate-800"
                />
              </div>
              <div>
                <label className="block font-medium text-slate-600 mb-1">Tên nhà cung cấp</label>
                <input
                  type="text"
                  value={formData.supplier_name || ""}
                  onChange={(e) => setFormData({ ...formData, supplier_name: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 text-slate-800"
                />
              </div>

              <div>
                <label className="block font-medium text-slate-600 mb-1">Số hóa đơn</label>
                <input
                  type="text"
                  value={formData.invoice_number || ""}
                  onChange={(e) => setFormData({ ...formData, invoice_number: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono text-slate-800"
                />
              </div>
              <div>
                <label className="block font-medium text-slate-600 mb-1">Ký hiệu (Series)</label>
                <input
                  type="text"
                  value={formData.invoice_series || ""}
                  onChange={(e) => setFormData({ ...formData, invoice_series: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono text-slate-800"
                />
              </div>

              <div>
                <label className="block font-medium text-slate-600 mb-1">Ngày lập hóa đơn</label>
                <input
                  type="date"
                  value={formData.issue_date || ""}
                  onChange={(e) => setFormData({ ...formData, issue_date: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono text-slate-800"
                />
              </div>
              <div>
                <label className="block font-medium text-slate-600 mb-1">Loại tiền tệ</label>
                <input
                  type="text"
                  value={formData.currency || "VND"}
                  onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500 font-mono text-slate-800 uppercase"
                />
              </div>
            </div>

            {/* Line items table */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs font-semibold text-slate-700">Chi tiết từng dòng sản phẩm / dịch vụ</span>
                <span className="text-[11px] text-slate-400">({invoice.lines.length} dòng hàng)</span>
              </div>
              <div className="overflow-x-auto border border-slate-200 rounded-lg">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-50 font-medium text-slate-600 border-b border-slate-200">
                    <tr>
                      <th className="p-2.5">#</th>
                      <th className="p-2.5">Mô tả</th>
                      <th className="p-2.5 text-right">Số lượng</th>
                      <th className="p-2.5 text-right">Đơn giá</th>
                      <th className="p-2.5 text-right">Thuế (%)</th>
                      <th className="p-2.5 text-right">Thành tiền</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-mono">
                    {invoice.lines.map((ln) => (
                      <tr key={ln.id || ln.line_no} className="hover:bg-slate-50/50">
                        <td className="p-2.5 text-slate-400">{ln.line_no}</td>
                        <td className="p-2.5 font-sans font-medium text-slate-800 max-w-xs truncate">
                          {ln.description}
                        </td>
                        <td className="p-2.5 text-right text-slate-700">{ln.qty}</td>
                        <td className="p-2.5 text-right text-slate-700">{Number(ln.unit_price).toLocaleString("vi-VN")}</td>
                        <td className="p-2.5 text-right text-slate-500">{ln.tax_rate ?? "0"}%</td>
                        <td className="p-2.5 text-right font-semibold text-slate-900">
                          {Number(ln.line_amount).toLocaleString("vi-VN")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Totals Summary */}
            <div className="bg-slate-50 p-4 rounded-lg border border-slate-100 space-y-2 text-xs">
              <div className="flex justify-between text-slate-600">
                <span>Cộng tiền hàng (Subtotal):</span>
                <span className="font-mono font-medium">{Number(formData.subtotal || invoice.subtotal).toLocaleString("vi-VN")} {invoice.currency}</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Tiền thuế GTGT (Tax):</span>
                <span className="font-mono font-medium">{Number(formData.tax_total || invoice.tax_total).toLocaleString("vi-VN")} {invoice.currency}</span>
              </div>
              <div className="flex justify-between text-sm font-bold text-slate-900 pt-2 border-t border-slate-200">
                <span>Tổng tiền thanh toán (Payable):</span>
                <span className="font-mono text-sky-700">{Number(formData.amount_payable || invoice.amount_payable).toLocaleString("vi-VN")} {invoice.currency}</span>
              </div>
            </div>
          </div>

          {/* Bottom save correction button */}
          <div className="pt-4 border-t border-slate-100 flex justify-end">
            <button
              onClick={() => handleAction("correct")}
              disabled={isSubmitting}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-lg shadow-sm transition-all"
            >
              <Save className="w-4 h-4 text-slate-500" /> Lưu bản đính chính (Tăng Revision)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
