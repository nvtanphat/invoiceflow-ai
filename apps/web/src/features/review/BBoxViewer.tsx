import React, { useState, useEffect } from "react";
import { FieldEvidenceItem, api } from "../../lib/api-client";
import {
  Eye,
  ShieldCheck,
  ShieldAlert,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Layers,
  Table as TableIcon,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  RefreshCw,
  Loader2,
} from "lucide-react";

interface BBoxViewerProps {
  documentId?: string;
  documentName: string;
  evidenceList: FieldEvidenceItem[];
  selectedField: string | null;
  onSelectField: (fieldName: string) => void;
  isVerifiedSignature?: boolean;
}

interface ParsedBBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_index?: number;
}

export const BBoxViewer: React.FC<BBoxViewerProps> = ({
  documentId,
  documentName,
  evidenceList,
  selectedField,
  onSelectField,
  isVerifiedSignature,
}) => {
  const [zoom, setZoom] = useState<number>(1.0);
  const [activeTab, setActiveTab] = useState<"visual" | "table">("visual");
  const [pageIndex, setPageIndex] = useState<number>(0);
  const [pageCount, setPageCount] = useState<number>(1);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({
    width: 595,
    height: 842,
  });
  const [renderedImageUrl, setRenderedImageUrl] = useState<string | null>(null);
  const [isLoadingImage, setIsLoadingImage] = useState<boolean>(false);
  const [imageError, setImageError] = useState<string | null>(null);

  // Fetch rendered document page using authenticated blob API
  const fetchPageImage = async () => {
    if (!documentId) return;
    setIsLoadingImage(true);
    setImageError(null);

    try {
      const res = await api.renderDocumentPage(documentId, pageIndex);
      setRenderedImageUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return res.blobUrl;
      });
      if (res.width > 0 && res.height > 0) {
        setDimensions({ width: res.width, height: res.height });
      }
      if (res.pageCount > 0) {
        setPageCount(res.pageCount);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Không thể kết xuất trang tài liệu";
      setImageError(msg);
    } finally {
      setIsLoadingImage(false);
    }
  };

  useEffect(() => {
    fetchPageImage();
    return () => {
      if (renderedImageUrl) {
        URL.revokeObjectURL(renderedImageUrl);
      }
    };
  }, [documentId, pageIndex]);

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
      // Ignored non-json format
    }
    return null;
  };

  const handleZoomIn = () => setZoom((prev) => Math.min(prev + 0.15, 2.5));
  const handleZoomOut = () => setZoom((prev) => Math.max(prev - 0.15, 0.5));
  const handleResetZoom = () => setZoom(1.0);

  // Filter evidence fields for current page
  const pageEvidence = evidenceList.filter((ev) => {
    const bbox = parseBBox(ev.bbox_json);
    const itemPage = bbox?.page_index ?? ev.page ?? 0;
    return itemPage === pageIndex;
  });

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

      {/* Sub-header Bar: Zoom, Doc info & Page Navigation */}
      <div className="px-4 py-2 bg-slate-950/40 border-b border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span className="font-mono text-slate-300 truncate max-w-[200px]" title={documentName}>
            {documentName}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300 border border-slate-700">
            {evidenceList.length} trường trích xuất
          </span>
        </div>

        {/* Page Switcher */}
        {pageCount > 1 && (
          <div className="flex items-center gap-1 bg-slate-900 px-2 py-0.5 rounded border border-slate-800 text-[11px]">
            <button
              onClick={() => setPageIndex((p) => Math.max(p - 1, 0))}
              disabled={pageIndex === 0}
              className="p-0.5 rounded hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Trang trước"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="font-mono px-1">
              {pageIndex + 1} / {pageCount}
            </span>
            <button
              onClick={() => setPageIndex((p) => Math.min(p + 1, pageCount - 1))}
              disabled={pageIndex >= pageCount - 1}
              className="p-0.5 rounded hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Trang sau"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Zoom Controls */}
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
          {isLoadingImage ? (
            <div className="flex flex-col items-center justify-center gap-3 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin text-sky-500" />
              <span className="text-xs">Đang tải trang tài liệu số {pageIndex + 1}...</span>
            </div>
          ) : imageError ? (
            <div className="flex flex-col items-center justify-center gap-3 text-rose-400 max-w-sm text-center p-6 bg-slate-900/60 rounded-xl border border-rose-900/40">
              <AlertCircle className="w-8 h-8 text-rose-500" />
              <div className="text-xs">{imageError}</div>
              <button
                onClick={fetchPageImage}
                className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Thử lại
              </button>
            </div>
          ) : (
            <div
              style={{
                width: `${dimensions.width * zoom}px`,
                height: `${dimensions.height * zoom}px`,
                transformOrigin: "center center",
              }}
              className="relative bg-white text-slate-900 shadow-2xl rounded-sm border border-slate-200 transition-all duration-150 overflow-hidden"
            >
              {/* Header Document Verification Indicator */}
              <div className="p-4 border-b border-slate-200 flex justify-between items-start bg-slate-50/50">
                <div>
                  <div className="text-xs font-bold text-sky-900 tracking-wider">
                    BẢN THỂ HIỆN HÓA ĐƠN ĐIỆN TỬ
                  </div>
                  <div className="text-[10px] text-slate-500">
                    Kích thước: {Math.round(dimensions.width)} x {Math.round(dimensions.height)} pt (Trang {pageIndex + 1}/{pageCount})
                  </div>
                </div>

                {/* Digital Signature Status (Accurate check, no fake claims) */}
                {isVerifiedSignature ? (
                  <div className="flex items-center gap-1 text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                    <ShieldCheck className="w-3.5 h-3.5" /> Chữ ký số đã xác thực
                  </div>
                ) : (
                  <div className="flex items-center gap-1 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
                    <ShieldAlert className="w-3 h-3 text-amber-500" /> Chưa kiểm tra chữ ký số
                  </div>
                )}
              </div>

              {/* Real Authenticated Rendered Document Page Background */}
              {renderedImageUrl && (
                <img
                  src={renderedImageUrl}
                  alt={`Tài liệu trang ${pageIndex + 1}`}
                  className="absolute inset-0 w-full h-full object-contain pointer-events-none z-0"
                />
              )}

              {/* Watermark */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-5">
                <span className="text-6xl font-black uppercase text-slate-900 tracking-widest rotate-[-30deg]">
                  InvoiceFlow AI
                </span>
              </div>

              {/* Bounding Box Overlays */}
              {pageEvidence.map((ev, idx) => {
                const bbox = parseBBox(ev.bbox_json);
                const isSelected = selectedField === ev.field_name;
                const confPct = Math.round(ev.confidence * 100);

                if (bbox) {
                  // Coordinate scaling based on actual page dimensions
                  const left = (bbox.x0 / dimensions.width) * 100;
                  const top = (bbox.y0 / dimensions.height) * 100;
                  const width = Math.max(((bbox.x1 - bbox.x0) / dimensions.width) * 100, 2);
                  const height = Math.max(((bbox.y1 - bbox.y0) / dimensions.height) * 100, 1.5);

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
                      className={`absolute cursor-pointer rounded-xs transition-all z-10 ${
                        isSelected
                          ? "bg-sky-500/30 border-2 border-sky-500 ring-2 ring-sky-400/50"
                          : "bg-indigo-500/15 border border-indigo-500/70 hover:bg-indigo-500/30"
                      }`}
                      title={`${ev.field_name}: ${ev.raw_value} (Độ tin cậy: ${confPct}%)`}
                    >
                      {/* BBox Field Badge */}
                      <div
                        className={`absolute -top-4.5 left-0 text-[9px] font-mono px-1 py-0.2 rounded shadow-xs whitespace-nowrap pointer-events-none ${
                          isSelected
                            ? "bg-sky-600 text-white font-semibold"
                            : "bg-slate-900/80 text-sky-200"
                        }`}
                      >
                        {ev.field_name}
                      </div>
                    </div>
                  );
                }
                return null;
              })}
            </div>
          )}
        </div>
      ) : (
        /* Table View */
        <div className="flex-1 p-6 overflow-auto bg-slate-950/40">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-800 text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Tên trường</th>
                <th className="px-4 py-3">Giá trị gốc</th>
                <th className="px-4 py-3">Trang</th>
                <th className="px-4 py-3">Tọa độ [x0, y0, x1, y1]</th>
                <th className="px-4 py-3">Độ tin cậy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {evidenceList.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                    Không có tọa độ trích xuất cho tài liệu này.
                  </td>
                </tr>
              ) : (
                evidenceList.map((ev, idx) => {
                  const bbox = parseBBox(ev.bbox_json);
                  const isSelected = selectedField === ev.field_name;
                  const itemPage = (bbox?.page_index ?? ev.page ?? 0) + 1;

                  return (
                    <tr
                      key={`row-${ev.field_name}-${idx}`}
                      onClick={() => onSelectField(ev.field_name)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-sky-950/60 text-sky-200 border-l-2 border-sky-500"
                          : "hover:bg-slate-800/50"
                      }`}
                    >
                      <td className="px-4 py-2.5 font-sans font-medium text-white">
                        {ev.field_name}
                      </td>
                      <td className="px-4 py-2.5 text-slate-200 truncate max-w-xs">{ev.raw_value}</td>
                      <td className="px-4 py-2.5">{itemPage}</td>
                      <td className="px-4 py-2.5 text-slate-400">
                        {bbox
                          ? `[${Math.round(bbox.x0)}, ${Math.round(bbox.y0)}, ${Math.round(bbox.x1)}, ${Math.round(bbox.y1)}]`
                          : "null"}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-sans ${
                            ev.confidence >= 0.8
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : "bg-amber-950 text-amber-400 border border-amber-800"
                          }`}
                        >
                          {Math.round(ev.confidence * 100)}%
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
