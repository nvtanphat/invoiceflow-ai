import React from "react";
import { FieldEvidenceItem } from "../../lib/api-client";
import { Eye, ShieldCheck } from "lucide-react";

interface BBoxViewerProps {
  evidenceList: FieldEvidenceItem[];
  selectedField: string | null;
  onSelectField: (fieldName: string) => void;
  documentName: string;
}

export const BBoxViewer: React.FC<BBoxViewerProps> = ({
  evidenceList,
  selectedField,
  onSelectField,
  documentName,
}) => {
  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl overflow-hidden shadow-sm border border-slate-800 text-white">
      {/* Top bar */}
      <div className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-sky-400" />
          <span className="text-xs font-semibold tracking-wide uppercase text-slate-300">
            Xem trước & Tọa độ Bounding Box (Ground Truth)
          </span>
        </div>
        <span className="text-xs text-slate-400 font-mono truncate max-w-[200px]" title={documentName}>
          {documentName}
        </span>
      </div>

      {/* Simulated Document Canvas with Evidence Overlay */}
      <div className="relative flex-1 p-6 overflow-auto flex items-center justify-center bg-slate-950/60">
        <div className="relative w-[500px] min-h-[640px] bg-white text-slate-900 rounded-lg shadow-2xl p-8 border border-slate-200 select-none">
          {/* Mock Document Watermark / Header */}
          <div className="border-b border-slate-200 pb-4 mb-6 flex justify-between items-start">
            <div>
              <div className="text-xs font-bold text-sky-700 uppercase tracking-wider">Hóa đơn điện tử</div>
              <div className="text-[10px] text-slate-500">Bản thể hiện dữ liệu trích xuất</div>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">
              <ShieldCheck className="w-3.5 h-3.5" /> Có chữ ký số
            </div>
          </div>

          {/* Interactive Bounding Box list as visual cards on the canvas */}
          <div className="space-y-4">
            <div className="text-xs font-medium text-slate-500 mb-2">
              Các vùng thông tin đã trích xuất (Bấm để xem tương ứng):
            </div>

            {evidenceList.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-xs italic">
                (Dữ liệu trực tiếp từ XML gốc - không cần OCR bounding box)
              </div>
            ) : (
              evidenceList.map((ev, idx) => {
                const isSelected = selectedField === ev.field_name;
                const confPct = Math.round(ev.confidence * 100);

                return (
                  <div
                    key={`${ev.field_name}-${idx}`}
                    onClick={() => onSelectField(ev.field_name)}
                    className={`cursor-pointer transition-all rounded-md p-2.5 border text-xs ${
                      isSelected
                        ? "bg-sky-50 border-sky-500 ring-2 ring-sky-300 shadow-sm"
                        : "bg-slate-50/80 border-slate-200 hover:border-slate-300 hover:bg-slate-100/80"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold text-slate-800">{ev.field_name}</span>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-medium ${
                          confPct >= 95
                            ? "bg-emerald-100 text-emerald-800"
                            : confPct >= 80
                            ? "bg-amber-100 text-amber-800"
                            : "bg-rose-100 text-rose-800"
                        }`}
                      >
                        Độ tin cậy: {confPct}%
                      </span>
                    </div>
                    <div className="font-mono text-slate-600 bg-white px-2 py-1 rounded border border-slate-100 truncate">
                      {ev.raw_value || "(trống)"}
                    </div>
                    <div className="mt-1 flex items-center justify-between text-[10px] text-slate-400 font-mono">
                      <span>Nguồn: {ev.source}</span>
                      <span>Trang: {ev.page}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
