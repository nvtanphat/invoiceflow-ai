from enum import Enum
import hashlib
import logging
import os
import threading
import time
from typing import Any, List, Optional
from uuid import UUID

from invoiceflow.infrastructure.document.page_orientation import normalize_page_rotation
from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    CoordinateSystem,
    DocumentCell,
    DocumentElement,
    DocumentTable,
)
from invoiceflow.infrastructure.document.layout_extractor import LayoutExtractor
from invoiceflow.infrastructure.document.text_normalization import normalize_extracted_text

logger = logging.getLogger(__name__)


class DoclingPatchStatus(str, Enum):
    UNINITIALIZED = "uninitialized"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    FALLBACK_ACTIVE = "fallback_active"


def spatial_group_cells(cells: list[Any]) -> list[list[Any]]:
    """Groups text cells into reading lines (top-to-bottom, left-to-right) based on
    vertical overlap and horizontal coordinates."""
    if not cells:
        return []
    cell_info = []
    for c in cells:
        bb = getattr(c, "rect", None)
        if bb is not None and hasattr(bb, "to_bounding_box"):
            box = bb.to_bounding_box()
            left, top, right, bottom = box.l, box.t, box.r, box.b
        elif (
            hasattr(c, "left")
            and hasattr(c, "top")
            and hasattr(c, "right")
            and hasattr(c, "bottom")
        ):
            left, top, right, bottom = c.left, c.top, c.right, c.bottom
        elif hasattr(c, "l") and hasattr(c, "t") and hasattr(c, "r") and hasattr(c, "b"):
            left, top, right, bottom = c.l, c.t, c.r, c.b
        elif hasattr(c, "bbox") and c.bbox is not None:
            box = c.bbox
            left, top, right, bottom = box.x0, box.y0, box.x1, box.y1
        elif isinstance(c, dict) and "left" in c:
            left, top, right, bottom = c["left"], c["top"], c["right"], c["bottom"]
        elif isinstance(c, dict) and "l" in c:
            left, top, right, bottom = c["l"], c["t"], c["r"], c["b"]
        else:
            continue

        cell_info.append(
            {
                "cell": c,
                "left": float(left),
                "top": float(top),
                "right": float(right),
                "bottom": float(bottom),
                "y_center": float((top + bottom) / 2.0),
                "height": max(float(bottom - top), 1.0),
            }
        )

    if not cell_info:
        return []

    cell_info.sort(key=lambda x: x["y_center"])
    lines: list[list[Any]] = []
    cur_line: list[dict] = []
    cur_y = None
    cur_h = None
    for item in cell_info:
        if not cur_line:
            cur_line.append(item)
            cur_y = item["y_center"]
            cur_h = item["height"]
        else:
            threshold = max(cur_h, item["height"]) * 0.6
            if abs(item["y_center"] - cur_y) < threshold:
                cur_line.append(item)
                cur_y = sum(x["y_center"] for x in cur_line) / len(cur_line)
                cur_h = max(x["height"] for x in cur_line)
            else:
                cur_line.sort(key=lambda x: x["left"])
                lines.append([x["cell"] for x in cur_line])
                cur_line = [item]
                cur_y = item["y_center"]
                cur_h = item["height"]
    if cur_line:
        cur_line.sort(key=lambda x: x["left"])
        lines.append([x["cell"] for x in cur_line])
    return lines


class DoclingAdapter:
    """Infrastructure adapter converting PDF documents to CanonicalDocument using Docling.

    Provides lazy-loading, environment isolation, and graceful fallback to PyMuPDF
    when running on resource-constrained hardware (e.g. CPU-only, 16GB RAM) or when
    Docling dependencies are unavailable.
    """

    _patch_lock = threading.Lock()
    _patch_status: DoclingPatchStatus = DoclingPatchStatus.ACTIVE

    @classmethod
    def get_patch_status(cls) -> DoclingPatchStatus:
        return cls._patch_status

    @classmethod
    def _patch_docling_reading_order(cls) -> DoclingPatchStatus:
        """Maintained for backward compatibility. Official Docling pipeline options
        and adapter-level spatial normalization are used directly without monkey-patching."""
        return cls._patch_status

    def __init__(
        self,
        fallback_extractor: Optional[LayoutExtractor] = None,
        ocr_engine: Optional[str] = None,
        ocr_languages: Optional[List[str]] = None,
        ocr_dpi: Optional[int] = None,
    ):
        self._fallback_extractor = fallback_extractor or LayoutExtractor()
        self._converters: dict[bool, Any] = {}

        if ocr_engine is None or ocr_languages is None or ocr_dpi is None:
            from invoiceflow.config import get_settings

            settings = get_settings()
            ocr_engine = ocr_engine if ocr_engine is not None else settings.OCR_ENGINE
            ocr_languages = (
                ocr_languages if ocr_languages is not None else list(settings.OCR_LANGUAGES)
            )
            ocr_dpi = ocr_dpi if ocr_dpi is not None else settings.OCR_DPI
        self._ocr_engine = ocr_engine
        self._ocr_dpi = ocr_dpi
        self._ocr_languages = ocr_languages

    def _get_converter(self, do_ocr: bool = False):
        if do_ocr in self._converters:
            return self._converters[do_ocr]

        # Environment isolation guards for Windows & CPU-only deployment
        os.environ["USE_TF"] = "0"
        os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        try:
            import huggingface_hub.file_download as fd

            if os.name == "nt":
                fd.are_symlinks_supported = lambda *args, **kwargs: False
        except Exception:
            pass

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            EasyOcrOptions,
            PdfPipelineOptions,
            RapidOcrOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = do_ocr
        pipeline_options.do_table_structure = True

        if do_ocr:
            if self._ocr_engine == "easyocr":
                # RapidOCR's bundled default model (ch_PP-OCRv4) is trained
                # for Chinese/English and silently strips Vietnamese
                # diacritics instead of erroring (verified: "Công ty" ->
                # "Cong ty"). EasyOCR has an explicit Vietnamese character
                # set and measurably recovers them (see
                # benchmarks/results/ocr_quality_report.json).
                pipeline_options.ocr_options = EasyOcrOptions(lang=self._ocr_languages)
            elif self._ocr_engine == "rapidocr":
                pipeline_options.ocr_options = RapidOcrOptions(lang=self._ocr_languages)

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        self._converters[do_ocr] = converter
        return converter

    def _normalize_page_rotation(
        self,
        pdf_bytes: bytes,
        page_classifications: Optional[dict[int, str]] = None,
    ) -> bytes:
        return normalize_page_rotation(pdf_bytes, self._ocr_dpi, page_classifications)

    def extract_canonical(
        self,
        tenant_id: UUID | str,
        document_id: UUID | str,
        pdf_bytes: bytes,
        do_ocr: bool = False,
        page_classifications: Optional[dict[int, str]] = None,
    ) -> CanonicalDocument:
        """Extracts structured elements, tables, and provenance from a PDF document into CanonicalDocument."""
        start_time = time.perf_counter()

        if do_ocr:
            pdf_bytes = self._normalize_page_rotation(
                pdf_bytes, page_classifications=page_classifications
            )

        try:
            import tempfile
            from pathlib import Path

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(pdf_bytes)
                tmp_path = Path(tmp_file.name)

            try:
                converter = self._get_converter(do_ocr=do_ocr)
                res = converter.convert(tmp_path)
                doc = res.document
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

            elements: List[DocumentElement] = []
            tables: List[DocumentTable] = []
            el_counter = 1
            table_counter = 1

            # Determine page heights for coordinate system conversion
            page_heights: dict[int, float] = {}
            for p_no, p_data in doc.pages.items():
                p_idx = int(p_no) - 1
                page_heights[p_idx] = float(p_data.size.height) if p_data.size else 842.0

            # 1. Extract structured tables
            for t_idx, tab in enumerate(doc.tables):
                page_no = 1
                if tab.prov and len(tab.prov) > 0:
                    page_no = tab.prov[0].page_no
                p_idx = max(int(page_no) - 1, 0)
                p_height = page_heights.get(p_idx, 842.0)

                cells: List[DocumentCell] = []
                row_cnt = tab.data.num_rows
                col_cnt = tab.data.num_cols
                table_id = f"docling-table-{p_idx}-{table_counter}"

                for cell in tab.data.table_cells:
                    cell_bbox = None
                    if cell.bbox:
                        try:
                            tl = cell.bbox.to_top_left_origin(p_height)
                            cell_bbox = BoundingBox(
                                page_index=p_idx,
                                x0=float(min(tl.l, tl.r)),
                                y0=float(min(tl.t, tl.b)),
                                x1=float(max(tl.l, tl.r)),
                                y1=float(max(tl.t, tl.b)),
                                coordinate_system=CoordinateSystem.PDF_POINTS,
                            )
                        except Exception:
                            pass

                    row_idx = cell.start_row_offset_idx
                    col_idx = cell.start_col_offset_idx
                    cells.append(
                        DocumentCell(
                            id=f"{table_id}-r{row_idx}-c{col_idx}",
                            table_id=table_id,
                            row_index=row_idx,
                            col_index=col_idx,
                            text=normalize_extracted_text(str(cell.text or "").strip()),
                            rowspan=cell.end_row_offset_idx - row_idx,
                            colspan=cell.end_col_offset_idx - col_idx,
                            bbox=cell_bbox,
                        )
                    )

                tables.append(
                    DocumentTable(
                        id=table_id,
                        page_index=p_idx,
                        row_count=row_cnt,
                        column_count=col_cnt,
                        cells=cells,
                    )
                )

                # Add non-header table row cells as document elements for extraction & evidence mapping
                for cell in tab.data.table_cells:
                    txt = normalize_extracted_text(str(cell.text or "").strip())
                    if txt and not getattr(cell, "column_header", False):
                        cell_bbox = None
                        if cell.bbox:
                            try:
                                tl = cell.bbox.to_top_left_origin(p_height)
                                cell_bbox = BoundingBox(
                                    page_index=p_idx,
                                    x0=float(min(tl.l, tl.r)),
                                    y0=float(min(tl.t, tl.b)),
                                    x1=float(max(tl.l, tl.r)),
                                    y1=float(max(tl.t, tl.b)),
                                    coordinate_system=CoordinateSystem.PDF_POINTS,
                                )
                            except Exception:
                                pass
                        row_idx = cell.start_row_offset_idx
                        col_idx = cell.start_col_offset_idx
                        elements.append(
                            DocumentElement(
                                id=f"docling-cell-{p_idx}-{table_counter}-{row_idx}-{col_idx}",
                                page_index=p_idx,
                                kind="table_cell",
                                text=txt,
                                reading_order=el_counter,
                                bbox=cell_bbox,
                                parent_id=f"{table_id}-r{row_idx}-c{col_idx}",
                            )
                        )
                        el_counter += 1

                table_counter += 1

            # 2. Extract textual elements (paragraphs, headings, text)
            if do_ocr and getattr(res, "pages", None):
                for page in res.pages:
                    p_idx = max(int(page.page_no or 1) - 1, 0)
                    p_height = page_heights.get(p_idx, 842.0)
                    if not (
                        page.predictions
                        and page.predictions.layout
                        and page.predictions.layout.clusters
                    ):
                        continue

                    for cluster in page.predictions.layout.clusters:
                        label_str = str(getattr(cluster, "label", "")).lower()
                        if "table" in label_str or "figure" in label_str:
                            continue

                        cluster_cells = getattr(cluster, "cells", [])
                        if not cluster_cells:
                            continue

                        line_groups = spatial_group_cells(cluster_cells)
                        for grp in line_groups:
                            words = [
                                c.text.replace("\x02", "-").strip()
                                for c in grp
                                if getattr(c, "text", "").strip()
                            ]
                            if not words:
                                continue
                            clean_text = normalize_extracted_text(" ".join(words))
                            if not clean_text:
                                continue

                            min_l = float("inf")
                            min_t = float("inf")
                            max_r = float("-inf")
                            max_b = float("-inf")
                            has_bbox = False

                            for c in grp:
                                bb = getattr(c, "rect", None)
                                if bb is not None and hasattr(bb, "to_bounding_box"):
                                    b = bb.to_bounding_box()
                                    if hasattr(b, "to_top_left_origin"):
                                        b = b.to_top_left_origin(p_height)
                                    min_l = min(min_l, float(min(b.l, b.r)))
                                    min_t = min(min_t, float(min(b.t, b.b)))
                                    max_r = max(max_r, float(max(b.l, b.r)))
                                    max_b = max(max_b, float(max(b.t, b.b)))
                                    has_bbox = True
                                elif hasattr(c, "bbox") and c.bbox is not None:
                                    min_l = min(min_l, float(c.bbox.x0))
                                    min_t = min(min_t, float(c.bbox.y0))
                                    max_r = max(max_r, float(c.bbox.x1))
                                    max_b = max(max_b, float(c.bbox.y1))
                                    has_bbox = True

                            bbox_obj = None
                            if has_bbox and min_l < max_r and min_t < max_b:
                                bbox_obj = BoundingBox(
                                    page_index=p_idx,
                                    x0=min_l,
                                    y0=min_t,
                                    x1=max_r,
                                    y1=max_b,
                                    coordinate_system=CoordinateSystem.PDF_POINTS,
                                )

                            elements.append(
                                DocumentElement(
                                    id=f"docling-elem-{p_idx}-{el_counter}",
                                    page_index=p_idx,
                                    kind=getattr(cluster, "label", "text"),
                                    text=clean_text,
                                    reading_order=el_counter,
                                    bbox=bbox_obj,
                                )
                            )
                            el_counter += 1
            else:
                for item in doc.texts:
                    clean_text = normalize_extracted_text(str(item.text or "").strip())
                    if not clean_text:
                        continue

                    page_no = 1
                    bbox_obj = None
                    if item.prov and len(item.prov) > 0:
                        page_no = item.prov[0].page_no
                        p_idx = max(int(page_no) - 1, 0)
                        p_height = page_heights.get(p_idx, 842.0)
                        raw_bbox = item.prov[0].bbox
                        if raw_bbox:
                            try:
                                tl = raw_bbox.to_top_left_origin(p_height)
                                bbox_obj = BoundingBox(
                                    page_index=p_idx,
                                    x0=float(min(tl.l, tl.r)),
                                    y0=float(min(tl.t, tl.b)),
                                    x1=float(max(tl.l, tl.r)),
                                    y1=float(max(tl.t, tl.b)),
                                    coordinate_system=CoordinateSystem.PDF_POINTS,
                                )
                            except Exception:
                                pass
                    else:
                        p_idx = 0

                    kind = getattr(item, "label", "text")
                    elements.append(
                        DocumentElement(
                            id=f"docling-elem-{p_idx}-{el_counter}",
                            page_index=p_idx,
                            kind=str(kind),
                            text=clean_text,
                            reading_order=el_counter,
                            bbox=bbox_obj,
                        )
                    )
                    el_counter += 1

            if not elements and not tables:
                logger.warning(
                    "Docling returned empty document without any elements or tables for document %s",
                    document_id,
                )
                fallback_canonical = self._fallback_extractor.extract_canonical(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    pdf_bytes=pdf_bytes,
                )
                fallback_canonical.metadata["fallback_from"] = "docling_empty"
                return fallback_canonical

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            config_hash = hashlib.sha256(f"docling-v2-ocr={do_ocr}".encode()).hexdigest()

            import importlib.metadata

            try:
                version = importlib.metadata.version("docling")
            except Exception:
                version = "2.87.0"

            return CanonicalDocument(
                document_id=document_id,
                tenant_id=tenant_id,
                source_format="pdf",
                parser_name="docling",
                parser_version=version,
                config_hash=config_hash,
                source_checksum=hashlib.sha256(pdf_bytes).hexdigest(),
                page_count=len(doc.pages) if doc.pages else 1,
                elements=elements,
                tables=tables,
                metadata={
                    "latency_ms": duration_ms,
                    "engine": "docling",
                    "do_ocr": do_ocr,
                    "tables_found": len(tables),
                    "elements_found": len(elements),
                },
            )

        except Exception as exc:
            logger.warning(
                "Docling extraction encountered an exception (%s); executing graceful fallback to PyMuPDF layout extractor.",
                exc,
            )
            try:
                canonical = self._fallback_extractor.extract_canonical(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    pdf_bytes=pdf_bytes,
                )
                canonical.metadata["fallback_from"] = "docling"
                canonical.metadata["fallback_reason"] = str(exc)
                return canonical
            except Exception as fallback_exc:
                return CanonicalDocument(
                    document_id=UUID(str(document_id)),
                    tenant_id=UUID(str(tenant_id)),
                    source_format="pdf",
                    parser_name="docling_fallback_failed",
                    parser_version="2.87.0",
                    config_hash=hashlib.sha256(b"corrupt-stream").hexdigest(),
                    page_count=0,
                    elements=[],
                    tables=[],
                    metadata={
                        "fallback_from": "docling",
                        "error": str(exc),
                        "fallback_error": str(fallback_exc),
                    },
                )
