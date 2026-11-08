import hashlib
from typing import List
from uuid import UUID
import fitz

from invoiceflow.domain.documents.models import (
    BoundingBox,
    CanonicalDocument,
    CoordinateSystem,
    DocumentCell,
    DocumentElement,
    DocumentTable,
)
from invoiceflow.infrastructure.document.text_normalization import normalize_extracted_text


class LayoutExtractor:
    def extract_canonical(
        self,
        tenant_id: UUID | str,
        document_id: UUID | str,
        pdf_bytes: bytes,
    ) -> CanonicalDocument:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        elements: List[DocumentElement] = []
        tables: List[DocumentTable] = []
        el_counter = 1
        table_counter = 1

        try:
            page_count = doc.page_count
            for p_idx in range(page_count):
                page = doc.load_page(p_idx)

                # 1. Extract tables
                try:
                    tabs = page.find_tables()
                    for t_idx, tab in enumerate(tabs):
                        cells = []
                        df_rows = tab.extract()
                        row_cnt = len(df_rows)
                        col_cnt = len(df_rows[0]) if row_cnt > 0 else 0
                        table_id = f"table-{p_idx}-{table_counter}"

                        for r_idx, row in enumerate(df_rows):
                            for c_idx, cell_text in enumerate(row):
                                cells.append(
                                    DocumentCell(
                                        id=f"{table_id}-r{r_idx}-c{c_idx}",
                                        table_id=table_id,
                                        row_index=r_idx,
                                        col_index=c_idx,
                                        text=normalize_extracted_text(str(cell_text or "").strip()),
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
                        table_counter += 1
                except Exception:
                    pass  # table finding is best-effort fallback

                # 2. Extract text blocks with coordinates
                text_page = page.get_text("blocks")
                for block in text_page:
                    if len(block) >= 5:
                        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
                        clean_text = normalize_extracted_text(text.strip())
                        if clean_text:
                            elements.append(
                                DocumentElement(
                                    id=f"elem-{p_idx}-{el_counter}",
                                    page_index=p_idx,
                                    kind="text",
                                    text=clean_text,
                                    reading_order=el_counter,
                                    bbox=BoundingBox(
                                        page_index=p_idx,
                                        x0=float(x0),
                                        y0=float(y0),
                                        x1=float(x1),
                                        y1=float(y1),
                                        coordinate_system=CoordinateSystem.PDF_POINTS,
                                    ),
                                )
                            )
                            el_counter += 1

            config_hash = hashlib.sha256(b"pymupdf-layout-v1").hexdigest()

            return CanonicalDocument(
                document_id=document_id,
                tenant_id=tenant_id,
                source_format="pdf",
                parser_name="pymupdf",
                parser_version=fitz.__version__,
                config_hash=config_hash,
                page_count=page_count,
                elements=elements,
                tables=tables,
                metadata={"title": doc.metadata.get("title", "") if doc.metadata else ""},
            )
        finally:
            doc.close()
