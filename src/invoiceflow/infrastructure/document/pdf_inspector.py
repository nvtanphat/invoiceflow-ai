from typing import Dict, NamedTuple
import fitz


class PDFInspectionError(Exception):
    pass


class ClassificationStr(str):
    """String subclass providing transparent bidirectional compatibility between canonical
    classification names (e.g. digital_pdf, scanned_pdf, mixed_pdf) and legacy aliases (e.g. pdf_digital, pdf_scan, mixed).
    """

    _ALIASES = {
        "digital_pdf": "pdf_digital",
        "pdf_digital": "digital_pdf",
        "scanned_pdf": "pdf_scan",
        "pdf_scan": "scanned_pdf",
        "mixed_pdf": "mixed",
        "mixed": "mixed_pdf",
        "xml_invoice": "xml_standard",
        "xml_standard": "xml_invoice",
        "invalid_document": "pdf_encrypted",
        "pdf_encrypted": "invalid_document",
        "digital": "native_text",
        "native_text": "digital",
        "scanned": "scanned_image",
        "scanned_image": "scanned",
        "blank": "empty",
        "empty": "blank",
    }

    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if isinstance(other, str):
            return self._ALIASES.get(str(self)) == other or self._ALIASES.get(other) == str(self)
        return False

    def __hash__(self) -> int:
        return super().__hash__()


class PDFInspectionReport(NamedTuple):
    page_count: int
    is_encrypted: bool
    classification: str  # "digital_pdf", "scanned_pdf", "mixed_pdf", "invalid_document"
    has_sufficient_text: bool
    extracted_sample_text: str
    page_classifications: Dict[int, str]
    page_rotations: Dict[int, int]
    has_rotated_pages: bool
    table_count: int = 0

    @property
    def is_digital(self) -> bool:
        return self.classification in ("digital_pdf", "pdf_digital")

    @property
    def is_scanned(self) -> bool:
        return self.classification in ("scanned_pdf", "pdf_scan")

    @property
    def is_mixed(self) -> bool:
        return self.classification in ("mixed_pdf", "mixed")


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
                    classification=ClassificationStr("invalid_document"),
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
            scanned_pages = 0
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
                    page_classifications[i] = ClassificationStr("digital")
                elif len(page.get_images()) > 0:
                    scanned_pages += 1
                    page_classifications[i] = ClassificationStr("scanned")
                else:
                    page_classifications[i] = ClassificationStr("blank")

                if i < 2 and text:
                    sample_text_parts.append(text[:200])

            has_sufficient = digital_pages == page_count
            if digital_pages == page_count:
                classification = ClassificationStr("digital_pdf")
            elif digital_pages == 0:
                classification = ClassificationStr("scanned_pdf")
            else:
                classification = ClassificationStr("mixed_pdf")

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
