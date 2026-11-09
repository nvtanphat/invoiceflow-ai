from decimal import Decimal
import logging
import re
from typing import Any, Optional, Tuple
import cv2
import fitz
import numpy as np

from invoiceflow.domain.documents.models import BoundingBox

logger = logging.getLogger(__name__)


class RegionOCRRecoverer:
    """Targeted region-level OCR recoverer for problematic invoice zones.

    Locates missing/uncertain fields by bounding box or spatial zone,
    renders a high-resolution crop, enhances local contrast, and attempts
    targeted OCR retry without re-OCR-ing the entire document.
    """

    def __init__(self, high_dpi: int = 250):
        self._high_dpi = high_dpi
        self._reader = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            try:
                import easyocr

                self._reader = easyocr.Reader(["vi", "en"], gpu=False)
            except Exception as e:
                logger.warning("Could not initialize EasyOCR reader for region recovery: %s", e)
        return self._reader

    @staticmethod
    def _crop_and_enhance(
        page: fitz.Page,
        rect: fitz.Rect,
        dpi: int = 250,
    ) -> Optional[np.ndarray]:
        try:
            pix = page.get_pixmap(clip=rect, dpi=dpi)
            nparr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                (pix.height, pix.width, pix.n)
            )
            if pix.n == 4:
                bgr = cv2.cvtColor(nparr, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                bgr = cv2.cvtColor(nparr, cv2.COLOR_RGB2BGR)
            elif pix.n == 1:
                bgr = cv2.cvtColor(nparr, cv2.COLOR_GRAY2BGR)
            else:
                bgr = nparr

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            # Local adaptive contrast enhancement for small text patches
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            return enhanced
        except Exception as e:
            logger.debug("Failed to crop and enhance page region %s: %s", rect, e)
            return None

    def recover_line_quantity(
        self,
        doc_pdf: fitz.Document,
        page_index: int,
        line_bbox: Optional[BoundingBox],
        unit_price: Decimal,
        line_amount: Decimal,
        discount: Decimal = Decimal("0.0000"),
    ) -> Optional[Tuple[Decimal, float]]:
        """Attempts to recover missing line quantity by cropping the line region,
        enhancing it, and checking arithmetic consistency against line_amount.
        """
        if line_amount <= Decimal("0.0000") or unit_price <= Decimal("0.0000"):
            return None
        if page_index >= len(doc_pdf):
            return None

        page = doc_pdf.load_page(page_index)
        page_rect = page.rect

        if line_bbox is not None and line_bbox.x0 is not None:
            # Expand line bbox slightly to ensure digits aren't clipped
            pad_x = 10.0
            pad_y = 5.0
            rect = fitz.Rect(
                max(0.0, line_bbox.x0 - pad_x),
                max(0.0, line_bbox.y0 - pad_y),
                min(page_rect.width, line_bbox.x1 + pad_x),
                min(page_rect.height, line_bbox.y1 + pad_y),
            )
        else:
            return None

        enhanced_crop = self._crop_and_enhance(page, rect, dpi=self._high_dpi)
        if enhanced_crop is None:
            return None

        reader = self._get_reader()
        if reader is None:
            return None

        try:
            results = reader.readtext(enhanced_crop)
            for _, text, conf in results:
                # Find all potential numeric tokens
                tokens = re.findall(r"[\d.,]+", text)
                for tok in tokens:
                    clean = re.sub(r"[^\d.]", "", tok.replace(",", "."))
                    if not clean:
                        continue
                    try:
                        cand_qty = Decimal(clean)
                        if cand_qty <= Decimal("0.0000"):
                            continue
                        exp_amt = (cand_qty * unit_price) - discount
                        if abs(line_amount - exp_amt) < Decimal("0.0100"):
                            logger.info(
                                "Successfully recovered line quantity %s with region OCR (conf=%.2f)",
                                cand_qty,
                                conf,
                            )
                            return cand_qty, float(conf)
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Exception in region OCR quantity recovery: %s", e)

        return None

    def recover_missing_header_field(
        self,
        doc_pdf: fitz.Document,
        page_index: int,
        field_name: str,
    ) -> Optional[Tuple[str, float]]:
        """Recovers missing supplier tax ID or invoice number from the top 35% of the page."""
        if page_index >= len(doc_pdf):
            return None

        page = doc_pdf.load_page(page_index)
        # Header region is in the top 35% of page
        rect = fitz.Rect(0.0, 0.0, page.rect.width, page.rect.height * 0.35)

        enhanced_crop = self._crop_and_enhance(page, rect, dpi=self._high_dpi)
        if enhanced_crop is None:
            return None

        reader = self._get_reader()
        if reader is None:
            return None

        try:
            results = reader.readtext(enhanced_crop)
            full_crop_text = " ".join([r[1] for r in results])
            crop_conf = sum([r[2] for r in results]) / max(len(results), 1)

            if field_name == "supplier_tax_id":
                m = re.search(r"\b(\d{10}(?:-\d{3})?)\b", full_crop_text)
                if m:
                    tax_id = m.group(1)
                    return tax_id, float(crop_conf)

            elif field_name == "invoice_number":
                m = re.search(
                    r"(?:So|Số|No\.?|HD)\s*[:\s]+(\d{6,8})\b", full_crop_text, re.IGNORECASE
                )
                if m:
                    inv_no = m.group(1)
                    return inv_no, float(crop_conf)
        except Exception as e:
            logger.debug("Exception in region OCR header recovery for %s: %s", field_name, e)

        return None
