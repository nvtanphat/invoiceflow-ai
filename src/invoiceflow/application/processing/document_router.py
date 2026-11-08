from enum import Enum
from typing import Optional


class ProcessingRoute(str, Enum):
    XML_DETERMINISTIC = "xml_deterministic"
    PDF_DIGITAL = "pdf_digital"
    VISION_FALLBACK = "vision_fallback"
    MANUAL_REVIEW = "manual_review"


class DocumentRouter:
    def decide_route(
        self,
        detected_kind: str,
        file_size_bytes: int,
        pdf_classification: Optional[str] = None,
    ) -> ProcessingRoute:
        if detected_kind == "xml":
            return ProcessingRoute.XML_DETERMINISTIC

        if detected_kind == "pdf":
            if pdf_classification == "pdf_digital":
                return ProcessingRoute.PDF_DIGITAL
            if pdf_classification == "pdf_scan":
                return ProcessingRoute.VISION_FALLBACK
            if pdf_classification == "mixed":
                return ProcessingRoute.PDF_DIGITAL

        return ProcessingRoute.VISION_FALLBACK
