from enum import Enum
from typing import Optional


class ProcessingRoute(str, Enum):
    XML_DETERMINISTIC = "xml_deterministic"
    PDF_DIGITAL = "pdf_digital"
    DOCLING_OCR_STRUCTURED = "docling_ocr_structured"
    VISION_FALLBACK = "vision_fallback"
    MANUAL_REVIEW = "manual_review"


class DocumentRouter:
    """Multi-signal intelligent router deciding the most cost-effective and accurate processing path.

    Evaluates text density, table completeness, document classification,
    and difficulty signals to minimize unnecessary LLM token spend.
    """

    def decide_route(
        self,
        detected_kind: str,
        file_size_bytes: int,
        pdf_classification: Optional[str] = None,
        table_count: int = 0,
        text_coverage_ratio: float = 1.0,
        has_rotated_pages: bool = False,
        is_difficult: bool = False,
        budget_available: bool = True,
    ) -> ProcessingRoute:
        if detected_kind == "xml":
            return ProcessingRoute.XML_DETERMINISTIC

        if detected_kind == "pdf":
            if is_difficult and budget_available:
                return ProcessingRoute.VISION_FALLBACK

            if pdf_classification == "pdf_digital":
                return ProcessingRoute.PDF_DIGITAL

            if pdf_classification == "pdf_scan":
                # If document has table structure detected or is standard size, try Docling OCR first
                if table_count > 0 or not is_difficult:
                    return ProcessingRoute.DOCLING_OCR_STRUCTURED
                if budget_available:
                    return ProcessingRoute.VISION_FALLBACK
                return ProcessingRoute.DOCLING_OCR_STRUCTURED

            if pdf_classification == "mixed":
                return ProcessingRoute.PDF_DIGITAL

        return (
            ProcessingRoute.VISION_FALLBACK if budget_available else ProcessingRoute.MANUAL_REVIEW
        )
