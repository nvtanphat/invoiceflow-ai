from typing import Dict, NamedTuple
import fitz


class PDFInspectionError(Exception):
    pass


class PDFInspectionReport(NamedTuple):
    page_count: int
    is_encrypted: bool
    classification: str  # "pdf_digital", "pdf_scan", "mixed"
    has_sufficient_text: bool
    extracted_sample_text: str
    page_classifications: Dict[int, str]
    page_rotations: Dict[int, int]
    has_rotated_pages: bool
    table_count: int = 0


class PDFInspector:
    def __init__(self, min_char_threshold_per_page: int = 50):
        self.min_char_threshold_per_page = min_char_threshold_per_page

    def inspect(self, pdf_bytes: bytes) -> PDFInspectionReport:
        if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
            raise PDFInspectionError("Invalid PDF header.")

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise PDFInspectionError(f"Corrupted or invalid PDF document: {str(e)}") from e

        try:
            if doc.is_encrypted:
                return PDFInspectionReport(
                    page_count=doc.page_count,
                    is_encrypted=True,
                    classification="pdf_encrypted",
                    has_sufficient_text=False,
                    extracted_sample_text="",
                    page_classifications={},
                    page_rotations={},
                    has_rotated_pages=False,
                )

            page_count = doc.page_count
            if page_count == 0:
                raise PDFInspectionError("PDF has 0 pages.")

            digital_pages = 0
            sample_text_parts = []
            page_classifications: Dict[int, str] = {}
            page_rotations: Dict[int, int] = {}
            total_tables = 0

            for i in range(page_count):
                page = doc.load_page(i)
                text = page.get_text().strip()
                rot = page.rotation
                page_rotations[i] = rot

                try:
                    tabs = page.find_tables().tables
                    total_tables += len(tabs)
                except Exception:
                    pass

                if len(text) >= self.min_char_threshold_per_page:
                    digital_pages += 1
                    page_classifications[i] = "native_text"
                elif len(page.get_images()) > 0:
                    page_classifications[i] = "scanned_image"
                else:
                    page_classifications[i] = "blank"

                if i < 2 and text:
                    sample_text_parts.append(text[:200])

            has_sufficient = digital_pages == page_count
            if digital_pages == page_count:
                classification = "pdf_digital"
            elif digital_pages == 0:
                classification = "pdf_scan"
            else:
                classification = "mixed"

            has_rotated_pages = any(r != 0 for r in page_rotations.values())

            return PDFInspectionReport(
                page_count=page_count,
                is_encrypted=False,
                classification=classification,
                has_sufficient_text=has_sufficient,
                extracted_sample_text="\n".join(sample_text_parts),
                page_classifications=page_classifications,
                page_rotations=page_rotations,
                has_rotated_pages=has_rotated_pages,
                table_count=total_tables,
            )
        finally:
            doc.close()
