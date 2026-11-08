import hashlib
import logging
import os
import time
from typing import List, Optional
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

logger = logging.getLogger(__name__)


class DoclingAdapter:
    """Infrastructure adapter converting PDF documents to CanonicalDocument using Docling.

    Provides lazy-loading, environment isolation, and graceful fallback to PyMuPDF
    when running on resource-constrained hardware (e.g. CPU-only, 16GB RAM) or when
    Docling dependencies are unavailable.
    """

    def __init__(self, fallback_extractor: Optional[LayoutExtractor] = None):
        self._fallback_extractor = fallback_extractor or LayoutExtractor()
        self._converter = None

    def _get_converter(self, do_ocr: bool = False):
        if self._converter is not None:
            return self._converter

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
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = do_ocr
        pipeline_options.do_table_structure = True

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        return self._converter

    def extract_canonical(
        self,
        tenant_id: UUID | str,
        document_id: UUID | str,
        pdf_bytes: bytes,
        do_ocr: bool = False,
    ) -> CanonicalDocument:
        """Extracts structured elements, tables, and provenance from a PDF document into CanonicalDocument."""
        start_time = time.perf_counter()

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

                    cells.append(
                        DocumentCell(
                            row_index=cell.start_row_offset_idx,
                            col_index=cell.start_col_offset_idx,
                            text=str(cell.text or "").strip(),
                            rowspan=cell.end_row_offset_idx - cell.start_row_offset_idx,
                            colspan=cell.end_col_offset_idx - cell.start_col_offset_idx,
                            bbox=cell_bbox,
                        )
                    )

                tables.append(
                    DocumentTable(
                        id=f"docling-table-{p_idx}-{table_counter}",
                        page_index=p_idx,
                        row_count=row_cnt,
                        column_count=col_cnt,
                        cells=cells,
                    )
                )

                # Add non-header table row cells as document elements for extraction & evidence mapping
                for cell in tab.data.table_cells:
                    txt = str(cell.text or "").strip()
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
                        elements.append(
                            DocumentElement(
                                id=f"docling-cell-{p_idx}-{table_counter}-{cell.start_row_offset_idx}-{cell.start_col_offset_idx}",
                                page_index=p_idx,
                                kind="table_cell",
                                text=txt,
                                reading_order=el_counter,
                                bbox=cell_bbox,
                            )
                        )
                        el_counter += 1

                table_counter += 1

            # 2. Extract textual elements (paragraphs, headings, text)
            for item in doc.texts:
                clean_text = str(item.text or "").strip()
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

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            config_hash = hashlib.sha256(f"docling-v2-ocr={do_ocr}".encode()).hexdigest()

            import importlib.metadata
            try:
                version = importlib.metadata.version("docling")
            except Exception:
                version = "2.87.0"

            return CanonicalDocument(
                document_id=UUID(str(document_id)),
                tenant_id=UUID(str(tenant_id)),
                source_format="pdf",
                parser_name="docling",
                parser_version=version,
                config_hash=config_hash,
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
