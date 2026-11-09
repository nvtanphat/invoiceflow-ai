import fitz
import pytest

from invoiceflow.domain.documents.models import CoordinateSystem
from invoiceflow.infrastructure.document.docling_adapter import DoclingAdapter


@pytest.fixture
def docling_adapter():
    return DoclingAdapter()


def create_sample_pdf(text: str = "", rotation: int = 0, is_scanned: bool = False) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if is_scanned:
        pix = fitz.Pixmap(fitz.csRGB, (0, 0, 200, 200), 1)
        page.insert_image(fitz.Rect(50, 50, 350, 350), pixmap=pix)
    if text:
        page.insert_text((50, 100), text, fontsize=14)
    if rotation != 0:
        page.set_rotation(rotation)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_normalize_page_rotation_preserves_digital_vector_text(docling_adapter):
    """Rotated digital PDFs must preserve their native vector text layer and never be rasterized."""
    text_content = "CONG TY TNHH PHAT TRIEN CONG NGHE ALPHA - SO HOA DON INV-2026-001"
    for rot in (90, 180, 270):
        pdf_bytes = create_sample_pdf(text=text_content, rotation=rot, is_scanned=False)
        normalized = docling_adapter._normalize_page_rotation(
            pdf_bytes, page_classifications={0: "digital"}
        )

        doc = fitz.open(stream=normalized, filetype="pdf")
        page = doc.load_page(0)
        extracted = page.get_text()
        images = page.get_images()
        doc.close()

        # Vector text must still be present and no raster images introduced
        assert "ALPHA" in extracted
        assert "INV-2026-001" in extracted
        assert len(images) == 0


def test_normalize_page_rotation_rasterizes_scanned_page_upright(docling_adapter):
    """Scanned pages with /Rotate metadata must be normalized upright to rotation=0."""
    for rot in (90, 180, 270):
        pdf_bytes = create_sample_pdf(rotation=rot, is_scanned=True)
        normalized = docling_adapter._normalize_page_rotation(
            pdf_bytes, page_classifications={0: "scanned"}
        )

        doc = fitz.open(stream=normalized, filetype="pdf")
        page = doc.load_page(0)
        assert page.rotation == 0
        images = page.get_images()
        assert len(images) > 0
        doc.close()


def test_unrotated_page_remains_unchanged(docling_adapter):
    """Pages with rotation=0 should pass through without modification."""
    pdf_bytes = create_sample_pdf(text="STANDARD UPRIGHT PAGE", rotation=0)
    normalized = docling_adapter._normalize_page_rotation(pdf_bytes)
    assert normalized == pdf_bytes


def test_bounding_box_coordinates_origin_and_bounds():
    """Verify BoundingBox objects use standardized top-left PDF points coordinate system."""
    from invoiceflow.domain.documents.models import BoundingBox

    # Simulating a cell on an A4 page (595 x 842 points)
    page_height = 842.0
    bbox = BoundingBox(
        page_index=0,
        x0=50.0,
        y0=100.0,
        x1=250.0,
        y1=150.0,
        coordinate_system=CoordinateSystem.PDF_POINTS,
    )

    assert bbox.x0 < bbox.x1
    assert bbox.y0 < bbox.y1
    assert 0 <= bbox.x0 <= 595.0
    assert 0 <= bbox.y0 <= page_height
    assert bbox.coordinate_system == CoordinateSystem.PDF_POINTS
