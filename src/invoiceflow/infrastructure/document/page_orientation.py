"""Rotation normalisation shared by OCR processing and page rendering.

Evidence coordinates are produced on the normalised page, so the viewer must render that same
page; otherwise bounding boxes on rotated scans point at the wrong place.
"""

from typing import Optional

import fitz

_DIGITAL_CLASSES = ("digital", "native_text")
_MIN_TEXT_LAYER_CHARS = 50


def normalize_page_rotation(
    pdf_bytes: bytes,
    ocr_dpi: int,
    page_classifications: Optional[dict[int, str]] = None,
) -> bytes:
    """Bakes each scanned page's /Rotate metadata into its raster content while preserving
    native vector text layers on digital pages.
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if not any(page.rotation != 0 for page in src):
            return pdf_bytes

        normalized = fitz.open()
        for page_index in range(src.page_count):
            page = src.load_page(page_index)
            if page.rotation == 0 or _is_digital(page, page_index, page_classifications):
                normalized.insert_pdf(src, from_page=page_index, to_page=page_index)
                continue
            page.set_rotation(0)
            pix = page.get_pixmap(dpi=ocr_dpi)
            width, height = page.rect.width, page.rect.height
            new_page = normalized.new_page(width=width, height=height)
            new_page.insert_image(fitz.Rect(0, 0, width, height), pixmap=pix)
        return normalized.tobytes()
    finally:
        src.close()


def _is_digital(
    page: fitz.Page, page_index: int, page_classifications: Optional[dict[int, str]]
) -> bool:
    if page_classifications is not None:
        return page_classifications.get(page_index) in _DIGITAL_CLASSES
    return len(page.get_text().strip()) >= _MIN_TEXT_LAYER_CHARS
