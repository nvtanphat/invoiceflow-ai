import uuid
import cv2
import numpy as np
import pytest

from invoiceflow.application.processing.document_router import ProcessingRoute
from invoiceflow.application.processing.service import DocumentAIService
from invoiceflow.infrastructure.document.image_preprocessor import ImagePreprocessor


def _create_synthetic_invoice_image_bytes() -> bytes:
    img = np.full((1200, 850, 3), 250, dtype=np.uint8)

    cv2.putText(
        img, "HOA DON GIA TRI GIA TANG", (190, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2
    )
    cv2.putText(img, "Ky hieu: 1C26TAA", (60, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.putText(img, "So hoa don: 0005678", (550, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.putText(img, "Ngay: 2026-03-15", (60, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

    cv2.putText(
        img,
        "Don vi ban: Cong ty Co phan Giay Mien Nam",
        (60, 230),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img, "Ma so thue: 0309876543", (60, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1
    )

    cv2.putText(
        img,
        "Don vi mua: Cong ty TNHH Thuong mai Dich vu Beta",
        (60, 310),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img, "Ma so thue: 0109998888", (60, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1
    )

    # Table
    y_table = 400
    cv2.rectangle(img, (50, y_table), (800, y_table + 35), (220, 220, 220), -1)
    cv2.rectangle(img, (50, y_table), (800, y_table + 35), (0, 0, 0), 1)
    cv2.putText(img, "STT", (60, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(
        img,
        "Ten hang hoa, dich vu",
        (130, y_table + 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 0),
        1,
    )
    cv2.putText(img, "So luong", (480, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Don gia", (580, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Thanh tien", (690, y_table + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Row 1
    y_r1 = y_table + 35
    cv2.rectangle(img, (50, y_r1), (800, y_r1 + 45), (0, 0, 0), 1)
    cv2.putText(img, "1", (65, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(
        img,
        "Giay in A4 Double A 70gsm",
        (130, y_r1 + 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 0),
        1,
    )
    cv2.putText(img, "10", (500, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "85,000", (580, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "850,000", (690, y_r1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Summary
    cv2.putText(
        img, "Cong tien hang: 850,000", (480, 530), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )
    cv2.putText(
        img, "Tien thue GTGT (8%): 68,000", (480, 560), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1
    )
    cv2.putText(
        img,
        "Tong cong tien thanh toan: 918,000 VND",
        (420, 600),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        2,
    )

    _, enc = cv2.imencode(".png", img)
    return enc.tobytes()


@pytest.mark.asyncio
async def test_document_ai_service_processes_image_upload():
    service = DocumentAIService()
    image_bytes = _create_synthetic_invoice_image_bytes()

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    result = await service.process_document(
        tenant_id=tenant_id,
        document_id=doc_id,
        filename="camera_captured_invoice.png",
        content=image_bytes,
        mime_type="image/png",
    )

    assert result.route == ProcessingRoute.IMAGE_PREPROCESSED_OCR
    assert result.invoice_aggregate is not None
    assert result.invoice_aggregate.document_id == doc_id

    # Verify that image preprocessing evidence was attached
    evidence_paths = [ev.field_path for ev in result.invoice_aggregate.evidence]
    assert "image_preprocessing.quality" in evidence_paths

    # Verify supplier tax ID or invoice number extraction
    assert result.invoice_aggregate.supplier_tax_id == "0309876543" or any(
        "0309876543" in ev.raw_value for ev in result.invoice_aggregate.evidence if ev.raw_value
    )


@pytest.mark.asyncio
async def test_image_preprocessing_with_perspective_distortion():
    preprocessor = ImagePreprocessor()
    service = DocumentAIService(image_preprocessor=preprocessor)

    # Create tilted invoice in camera frame
    canvas = np.full((1400, 1000, 3), 35, dtype=np.uint8)
    invoice_bytes = _create_synthetic_invoice_image_bytes()
    invoice_img = cv2.imdecode(np.frombuffer(invoice_bytes, np.uint8), cv2.IMREAD_COLOR)

    ih, iw = invoice_img.shape[:2]
    src_pts = np.array([[0, 0], [iw, 0], [iw, ih], [0, ih]], dtype="float32")
    dst_pts = np.array([[120, 160], [880, 110], [820, 1280], [80, 1310]], dtype="float32")
    m = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(invoice_img, m, (1000, 1400))
    mask = cv2.warpPerspective(np.full((ih, iw), 255, dtype=np.uint8), m, (1000, 1400))
    canvas[mask > 0] = warped[mask > 0]

    _, enc = cv2.imencode(".jpg", canvas)
    tilted_photo_bytes = enc.tobytes()

    result = await service.process_document(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="phone_capture_tilted.jpg",
        content=tilted_photo_bytes,
        mime_type="image/jpeg",
    )

    assert result.route == ProcessingRoute.IMAGE_PREPROCESSED_OCR
    evidence_paths = [ev.field_path for ev in result.invoice_aggregate.evidence]
    assert "image_preprocessing.perspective_correction" in evidence_paths
