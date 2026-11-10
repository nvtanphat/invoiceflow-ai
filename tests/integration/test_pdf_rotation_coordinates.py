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


@pytest.mark.asyncio
async def test_page_render_uses_the_orientation_evidence_coordinates_refer_to(tmp_path):
    """Regression (case_07): evidence bboxes are computed on the rotation-normalised page, but
    the viewer drew the /Rotate-applied page and rotated it again in CSS, so boxes drifted."""
    import uuid

    from httpx import ASGITransport, AsyncClient

    from invoiceflow.api.dependencies import create_access_token
    from invoiceflow.api.main import create_app
    from invoiceflow.config import get_settings
    from invoiceflow.infrastructure.database.models import (
        DocumentORM,
        MembershipORM,
        TenantORM,
        UserORM,
    )
    from invoiceflow.infrastructure.database.session import DatabaseSessionManager
    from invoiceflow.infrastructure.storage.service import LocalStorageService

    storage = LocalStorageService(base_dir=str(tmp_path))
    uri = await storage.save("t", "rotated.pdf", create_sample_pdf(rotation=90, is_scanned=True))
    db_manager = DatabaseSessionManager(database_url="sqlite+aiosqlite:///:memory:", echo=False)
    await db_manager.create_tables()
    async with db_manager.session() as session:
        tenant = TenantORM(name="Rot")
        user = UserORM(email="rot@vn.vn", hashed_password="x", full_name="R")
        session.add_all([tenant, user])
        await session.flush()
        session.add(MembershipORM(tenant_id=tenant.id, user_id=user.id, role="viewer"))
        doc = DocumentORM(
            tenant_id=tenant.id,
            filename="rotated.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            sha256=uuid.uuid4().hex,
            storage_uri=uri,
        )
        session.add(doc)
        await session.flush()
        ids = (tenant.id, user.id, doc.id)

    token = create_access_token(
        user_id=ids[1], tenant_id=ids[0], role="viewer", email="rot@vn.vn", settings=get_settings()
    )
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:", db_manager=db_manager, storage=storage
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            f"/api/v1/documents/{ids[2]}/pages/0/render",
            headers={"Authorization": f"Bearer {token}"},
        )
    await db_manager.close()

    assert res.status_code == 200
    assert res.headers["X-Page-Rotation"] == "0"
    assert (float(res.headers["X-Page-Width"]), float(res.headers["X-Page-Height"])) == (
        595.0,
        842.0,
    )
