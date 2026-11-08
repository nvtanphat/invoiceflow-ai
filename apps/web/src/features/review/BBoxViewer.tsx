import React, { useState } from "react";
import { FieldEvidenceItem } from "../../lib/api-client";
import {
  Eye,
  ShieldCheck,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Layers,
  Table as TableIcon,
} from "lucide-react";

interface BBoxViewerProps {
  evidenceList: FieldEvidenceItem[];
  selectedField: string | null;
  onSelectField: (fieldName: string) => void;
  documentName: string;
}

interface ParsedBBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_index?: number;
}

const PAGE_WIDTH = 595;
const PAGE_HEIGHT = 842;

export const BBoxViewer: React.FC<BBoxViewerProps> = ({
  evidenceList,
  selectedField,
  onSelectField,
  documentName,
}) => {
  const [zoom, setZoom] = useState<number>(1.0);
  const [activeTab, setActiveTab] = useState<"visual" | "table">("visual");

  const parseBBox = (bboxJson?: string): ParsedBBox | null => {
    if (!bboxJson) return null;
    try {
      const parsed = typeof bboxJson === "string" ? JSON.parse(bboxJson) : bboxJson;
      if (
        parsed &&
        typeof parsed.x0 === "number" &&
        typeof parsed.y0 === "number" &&
        typeof parsed.x1 === "number" &&
        typeof parsed.y1 === "number"
      ) {
        return parsed as ParsedBBox;
      }
    } catch {
      // Fallback if not valid JSON
    }
    return null;
  };

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.15, 2.0));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.15, 0.6));
  const handleResetZoom = () => setZoom(1.0);

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-xl overflow-hidden shadow-sm border border-slate-800 text-white select-none">
      {/* Top Header Bar */}
      <div className="px-4 py-2.5 bg-slate-800/90 border-b border-slate-700/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-sky-400" />
          <span className="text-xs font-semibold tracking-wide uppercase text-slate-200">
            Trình trực quan Bounding Box (Ground Truth)
          </span>
        </div>

        {/* View Mode Toggle */}
        <div className="flex items-center gap-1 bg-slate-950/70 p-1 rounded-lg border border-slate-700/50">
          <button
            onClick={() => setActiveTab("visual")}
            className={`px-2 py-1 text-xs rounded font-medium flex items-center gap-1.5 transition-colors ${
              activeTab === "visual"
                ? "bg-sky-600 text-white"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Layers className="w-3.5 h-3.5" /> Bản vẽ Overlay
          </button>
          <button
            onClick={() => setActiveTab("table")}
            className={`px-2 py-1 text-xs rounded font-medium flex items-center gap-1.5 transition-colors ${
              activeTab === "table"
                ? "bg-sky-600 text-white"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <TableIcon className="w-3.5 h-3.5" /> Bảng Tọa độ
          </button>
        </div>
      </div>

      {/* Sub-header Bar: Zoom & Doc info */}
      <div className="px-4 py-2 bg-slate-950/40 border-b border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span className="font-mono text-slate-300 truncate max-w-[220px]" title={documentName}>
            {documentName}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300 border border-slate-700">
            {evidenceList.length} trường trích xuất
          </span>
        </div>

        {activeTab === "visual" && (
          <div className="flex items-center gap-1">
            <button
              onClick={handleZoomOut}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
              title="Thu nhỏ"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="font-mono text-[11px] px-1">{Math.round(zoom * 100)}%</span>
            <button
              onClick={handleZoomIn}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
              title="Phóng to"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleResetZoom}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white ml-1"
              title="Khôi phục 100%"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Content Body */}
      {activeTab === "visual" ? (
        <div className="relative flex-1 p-6 overflow-auto flex items-center justify-center bg-slate-950/80">
          <div
            style={{
              width: `${PAGE_WIDTH * zoom}px`,
              height: `${PAGE_HEIGHT * zoom}px`,
              transformOrigin: "center center",
            }}
            className="relative bg-white text-slate-900 shadow-2xl rounded-sm border border-slate-200 transition-all duration-150 overflow-hidden"
          >
            {/* Header Document Decorative Elements */}
            <div className="p-6 border-b border-slate-200 flex justify-between items-start bg-slate-50/50">
              <div>
                <div className="text-sm font-bold text-sky-900 tracking-wider">
                  HÓA ĐƠN GIÁ TRỊ GIA TĂNG (ELECTRONIC INVOICE)
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  Bản thể hiện dữ liệu trích xuất kèm tọa độ Bounding Box
                </div>
              </div>
              <div className="flex items-center gap-1 text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                <ShieldCheck className="w-3.5 h-3.5" /> Chữ ký điện tử
              </div>
            </div>

            {/* Simulated Watermark */}
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-5">
              <span className="text-6xl font-black uppercase text-slate-900 tracking-widest rotate-[-30deg]">
                InvoiceFlow AI
              </span>
            </div>

            {/* Bounding Box Overlays */}
            {evidenceList.map((ev, idx) => {
              const bbox = parseBBox(ev.bbox_json);
              const isSelected = selectedField === ev.field_name;
              const confPct = Math.round(ev.confidence * 100);

              if (bbox) {
                // Point-based positioning scaled to container
                const left = (bbox.x0 / PAGE_WIDTH) * 100;
                const top = (bbox.y0 / PAGE_HEIGHT) * 100;
                const width = Math.max(((bbox.x1 - bbox.x0) / PAGE_WIDTH) * 100, 4);
                const height = Math.max(((bbox.y1 - bbox.y0) / PAGE_HEIGHT) * 100, 2);

                return (
                  <div
                    key={`bbox-${ev.field_name}-${idx}`}
                    onClick={() => onSelectField(ev.field_name)}
                    style={{
                      left: `${left}%`,
                      top: `${top}%`,
                      width: `${width}%`,
                      height: `${height}%`,
                    }}
                    className={`absolute cursor-pointer transition-all border-2 rounded ${
                      isSelected
                        ? "border-sky-500 bg-sky-400/25 ring-2 ring-sky-300 z-30 shadow-lg"
                        : "border-sky-400/70 bg-sky-100/20 hover:border-sky-500 hover:bg-sky-200/30 z-10"
                    }`}
                    title={`${ev.field_name}: ${ev.raw_value} (${confPct}%)`}
                  >
                    <span
                      className={`absolute -top-4 left-0 text-[9px] font-mono px-1 py-0.2 rounded font-bold whitespace-nowrap shadow-sm ${
                        isSelected
                          ? "bg-sky-600 text-white z-40"
                          : "bg-slate-800/80 text-sky-200"
                      }`}
                    >
                      {ev.field_name}
                    </span>
                  </div>
                );
              }

              return null;
            })}

            {/* Fallback layout if evidence items don't have visual bbox points */}
            <div className="p-6 space-y-3">
              {evidenceList.filter((ev) => !parseBBox(ev.bbox_json)).length > 0 && (
                <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="text-[11px] font-medium text-slate-500 mb-2">
                    Dữ liệu trích xuất trực tiếp (Deterministic XML / Direct Schema):
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {evidenceList
                      .filter((ev) => !parseBBox(ev.bbox_json))
                      .map((ev, idx) => {
                        const isSelected = selectedField === ev.field_name;
                        return (
                          <div
                            key={`xml-${ev.field_name}-${idx}`}
                            onClick={() => onSelectField(ev.field_name)}
                            className={`p-2 rounded text-xs border cursor-pointer transition-colors ${
                              isSelected
                                ? "border-sky-500 bg-sky-50 ring-1 ring-sky-400"
                                : "border-slate-200 bg-white hover:border-slate-300"
                            }`}
                          >
                            <div className="font-semibold text-slate-700 text-[11px]">
                              {ev.field_name}
                            </div>
                            <div className="font-mono text-slate-600 text-[10px] truncate">
                              {ev.raw_value || "(trống)"}
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* Table View of Evidence Coordinates */
        <div className="flex-1 overflow-auto p-4 bg-slate-950/60">
          <div className="border border-slate-800 rounded-lg overflow-hidden bg-slate-900">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-800/90 text-slate-300 border-b border-slate-700/80 font-semibold">
                  <th className="py-2.5 px-3">Trường (Field)</th>
                  <th className="py-2.5 px-3">Giá trị trích xuất</th>
                  <th className="py-2.5 px-3">Tọa độ [x0, y0, x1, y1]</th>
                  <th className="py-2.5 px-3">Trang</th>
                  <th className="py-2.5 px-3">Nguồn</th>
                  <th className="py-2.5 px-3 text-right">Độ tin cậy</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {evidenceList.map((ev, idx) => {
                  const bbox = parseBBox(ev.bbox_json);
                  const isSelected = selectedField === ev.field_name;
                  const confPct = Math.round(ev.confidence * 100);

                  return (
                    <tr
                      key={`row-${ev.field_name}-${idx}`}
                      onClick={() => onSelectField(ev.field_name)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-sky-950/80 text-sky-200 font-medium"
                          : "hover:bg-slate-800/50 text-slate-300"
                      }`}
                    >
                      <td className="py-2 px-3 font-semibold text-slate-200">
                        {ev.field_name}
                      </td>
                      <td className="py-2 px-3 font-mono text-slate-300 max-w-[180px] truncate">
                        {ev.raw_value || "-"}
                      </td>
                      <td className="py-2 px-3 font-mono text-[11px] text-slate-400">
                        {bbox
                          ? `[${Math.round(bbox.x0)}, ${Math.round(bbox.y0)}, ${Math.round(bbox.x1)}, ${Math.round(bbox.y1)}]`
                          : "N/A (XML direct)"}
                      </td>
                      <td className="py-2 px-3 font-mono text-slate-400">{ev.page}</td>
                      <td className="py-2 px-3 text-slate-400 text-[11px]">{ev.source}</td>
                      <td className="py-2 px-3 text-right">
                        <span
                          className={`px-1.5 py-0.5 rounded font-mono text-[10px] font-semibold ${
                            confPct >= 95
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : confPct >= 80
                              ? "bg-amber-950 text-amber-400 border border-amber-800"
                              : "bg-rose-950 text-rose-400 border border-rose-800"
                          }`}
                        >
                          {confPct}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
