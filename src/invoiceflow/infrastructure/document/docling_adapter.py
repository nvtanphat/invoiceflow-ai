import hashlib
import logging
import os
import time
from typing import Any, List, Optional
from uuid import UUID

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


class DoclingAdapter:
    """Infrastructure adapter converting PDF documents to CanonicalDocument using Docling.

    Provides lazy-loading, environment isolation, and graceful fallback to PyMuPDF
    when running on resource-constrained hardware (e.g. CPU-only, 16GB RAM) or when
    Docling dependencies are unavailable.
    """

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

    def _normalize_page_rotation(self, pdf_bytes: bytes) -> bytes:
        """Bakes each page's /Rotate metadata into its raster content.

        RapidOCR's PP-OCRv4 pipeline includes a per-text-region angle
        classifier that corrects rotated text internally, but Docling's
        EasyOCR integration does not expose EasyOCR's own rotation_info
        capability -- fed a page whose /Rotate flag says 90 but whose
        underlying content is physically unrotated (a real scanner/phone
        capture commonly produces exactly this), it reads the page as-is
        and sees vertical text, producing near-total garbage (verified:
        CER jumped from 7% to 93% on a 90-degree rotated fixture). Since
        the orientation problem is about what pixels face which direction,
        not which OCR engine is used, it is fixed once here rather than
        inside each engine.
        """
        import fitz

        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if not any(page.rotation != 0 for page in src):
                return pdf_bytes

            normalized = fitz.open()
            for page_index in range(src.page_count):
                page = src.load_page(page_index)
                if page.rotation == 0:
                    normalized.insert_pdf(src, from_page=page_index, to_page=page_index)
                    continue
                # get_pixmap() renders "as displayed" (rotation applied), which
                # is exactly backwards for this: the physical content is
                # already upright, and /Rotate is a display-time instruction to
                # turn it -- so render with rotation un-set to get the content
                # in its native, horizontal orientation.
                page.set_rotation(0)
                pix = page.get_pixmap(dpi=self._ocr_dpi)
                new_page = normalized.new_page(width=pix.width, height=pix.height)
                new_page.insert_image(new_page.rect, pixmap=pix)
            return normalized.tobytes()
        finally:
            src.close()

    def extract_canonical(
        self,
        tenant_id: UUID | str,
        document_id: UUID | str,
        pdf_bytes: bytes,
        do_ocr: bool = False,
    ) -> CanonicalDocument:
        """Extracts structured elements, tables, and provenance from a PDF document into CanonicalDocument."""
        start_time = time.perf_counter()

        if do_ocr:
            pdf_bytes = self._normalize_page_rotation(pdf_bytes)

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
