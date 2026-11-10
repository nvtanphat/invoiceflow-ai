import pytest
import cv2
import fitz
import numpy as np

from invoiceflow.infrastructure.document.image_preprocessor import (
    GeometryTransform,
    ImagePreprocessor,
    ImageQualityMetrics,
    PreprocessedImageResult,
)


def _create_synthetic_invoice_image(
    width: int = 800,
    height: int = 1100,
    bg_color: int = 250,
) -> np.ndarray:
    img = np.full((height, width, 3), bg_color, dtype=np.uint8)

    # Title
    cv2.putText(
        img, "HOA DON GIA TRI GIA TANG", (180, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2
    )
    cv2.putText(img, "Mau so: 1C26TAA", (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1)
    cv2.putText(img, "So: 0001234", (550, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1)

    # Supplier info
    cv2.putText(
        img,
        "Don vi ban: Cong ty Co phan Thuong mai Alpha",
        (50, 190),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 0),
        1,
    )
    cv2.putText(
        img, "Ma so thue: 0101234567", (50, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1
    )

    # Table Header
    cv2.rectangle(img, (40, 270), (760, 310), (220, 220, 220), -1)
    cv2.rectangle(img, (40, 270), (760, 310), (0, 0, 0), 1)
    cv2.putText(img, "STT", (50, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(
        img, "Ten hang hoa, dich vu", (120, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
    )
    cv2.putText(img, "So luong", (450, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Don gia", (550, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "Thanh tien", (660, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Table Row
    cv2.rectangle(img, (40, 310), (760, 360), (0, 0, 0), 1)
    cv2.putText(img, "1", (55, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(
        img, "Laptop Dell Precision 5520", (120, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1
    )
    cv2.putText(img, "2", (470, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "25,000,000", (540, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.putText(img, "50,000,000", (650, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Totals
    cv2.putText(
        img, "Tong cong: 50,000,000 VND", (480, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2
    )
    return img


def test_image_quality_assessment_clean_vs_blurry():
    preprocessor = ImagePreprocessor(blur_threshold=65.0)
    clean_img = _create_synthetic_invoice_image()

    metrics_clean = preprocessor.assess_quality(clean_img)
    assert isinstance(metrics_clean, ImageQualityMetrics)
    assert not metrics_clean.is_blurry
    assert metrics_clean.blur_score > 65.0
    assert not metrics_clean.is_low_contrast

    # Heavy blur simulation
    blurry_img = cv2.GaussianBlur(clean_img, (25, 25), 10.0)
    metrics_blurry = preprocessor.assess_quality(blurry_img)
    assert metrics_blurry.is_blurry
    assert metrics_blurry.blur_score < 65.0


def test_image_quality_assessment_shadow_and_low_contrast():
    preprocessor = ImagePreprocessor()
    img = _create_synthetic_invoice_image()

    # Apply synthetic dark shadow gradient across top-left to bottom-right
    h, w = img.shape[:2]
    y, x = np.mgrid[0:h, 0:w]
    gradient = ((x + y) / float(w + h) * 180).astype(np.uint8)
    shadowed_img = np.clip(img.astype(np.int32) - gradient[:, :, None], 0, 255).astype(np.uint8)

    metrics = preprocessor.assess_quality(shadowed_img)
    assert metrics.is_uneven_illumination


def test_boundary_detection_and_perspective_correction():
    preprocessor = ImagePreprocessor()

    # Place an invoice page onto a larger dark background with perspective warp
    canvas_w, canvas_h = 1200, 1600
    canvas = np.full((canvas_h, canvas_w, 3), 40, dtype=np.uint8)  # dark desk background

    invoice = _create_synthetic_invoice_image(width=600, height=850)
    ih, iw = invoice.shape[:2]

    # Source points (corners of invoice)
    src_pts = np.array([[0, 0], [iw, 0], [iw, ih], [0, ih]], dtype="float32")

    # Tilted quadrilateral on desk (perspective projection simulation)
    dst_pts = np.array(
        [[200, 250], [950, 180], [900, 1350], [150, 1400]],
        dtype="float32",
    )
    m = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped_invoice = cv2.warpPerspective(invoice, m, (canvas_w, canvas_h))

    # Mask and paste onto canvas
    mask = cv2.warpPerspective(np.full((ih, iw), 255, dtype=np.uint8), m, (canvas_w, canvas_h))
    canvas[mask > 0] = warped_invoice[mask > 0]

    # Detect boundary
    quad = preprocessor.detect_document_boundary(canvas)
    assert quad is not None
    assert quad.shape == (4, 2)

    # Correct perspective
    rectified, matrix, inv_matrix = preprocessor.correct_perspective(canvas, quad)
    assert rectified.shape[0] > 700
    assert rectified.shape[1] > 500

    # Verify bidirectional point mapping
    geom = GeometryTransform(
        applied_perspective=True,
        perspective_matrix=matrix.flatten().tolist(),
        inverse_perspective_matrix=inv_matrix.flatten().tolist(),
    )
    # The origin (0, 0) of the rectified document should map close to top-left of quad in canvas
    orig_x, orig_y = geom.map_point_to_original(0.0, 0.0)
    assert abs(orig_x - quad[0][0]) < 15.0
    assert abs(orig_y - quad[0][1]) < 15.0


def test_shadow_removal_enhancement():
    preprocessor = ImagePreprocessor()
    img = _create_synthetic_invoice_image(width=600, height=800)

    # Inject shadow
    h, w = img.shape[:2]
    shadow_mask = np.zeros((h, w), dtype=np.float32)
    cv2.circle(shadow_mask, (w // 2, h // 2), 250, 0.7, -1)
    shadow_mask = cv2.GaussianBlur(shadow_mask, (81, 81), 40.0)
    shadowed = (img * (1.0 - shadow_mask[:, :, None])).astype(np.uint8)

    enhanced = preprocessor.enhance_lighting_and_shadows(shadowed)
    assert enhanced.shape == shadowed.shape

    # The background in the shadowed center should be brightened back up
    center_val_before = np.mean(shadowed[h // 2 - 20 : h // 2 + 20, w // 2 - 20 : w // 2 + 20])
    center_val_after = np.mean(enhanced[h // 2 - 20 : h // 2 + 20, w // 2 - 20 : w // 2 + 20])
    assert center_val_after > center_val_before + 30.0


def test_deskew_correction():
    preprocessor = ImagePreprocessor()
    img = _create_synthetic_invoice_image(width=600, height=800)

    # Rotate by 3 degrees
    h, w = img.shape[:2]
    rot_mat = cv2.getRotationMatrix2D((w // 2, h // 2), 3.0, 1.0)
    rotated = cv2.warpAffine(img, rot_mat, (w, h), borderValue=(250, 250, 250))

    deskewed, angle = preprocessor.estimate_and_correct_skew(rotated)
    assert abs(angle) >= 0.5
    assert deskewed.shape == rotated.shape


def _straight_page_with_diagonal_strokes() -> np.ndarray:
    img = np.full((1200, 900), 255, np.uint8)
    for y in range(100, 1100, 40):
        cv2.line(img, (60, y), (840, y), 0, 2)
    # A signature-like diagonal stroke must not drive the skew estimate.
    cv2.line(img, (600, 900), (800, 928), 0, 3)
    cv2.line(img, (600, 960), (800, 988), 0, 3)
    return img


def test_deskew_leaves_straight_page_with_diagonal_strokes_unrotated():
    deskewed, angle = ImagePreprocessor.estimate_and_correct_skew(
        _straight_page_with_diagonal_strokes()
    )
    assert angle == 0.0


def test_deskew_accepts_flat_hough_segment_array(monkeypatch):
    # OpenCV builds disagree on HoughLinesP output: (N, 1, 4) or (N, 4).
    flat_segments = np.array([[0, 0, 400, 21], [0, 100, 400, 121]], dtype=np.int32)
    monkeypatch.setattr(cv2, "HoughLinesP", lambda *args, **kwargs: flat_segments)

    _, angle = ImagePreprocessor.estimate_and_correct_skew(np.full((300, 500), 255, np.uint8))

    assert abs(angle - 3.0) < 0.1


def test_deskew_correction_on_real_skewed_lowlight_image():
    from pathlib import Path

    fixture_path = Path("benchmarks/fixtures/real_world_eval/aug_07_skew_lowlight.png")
    if not fixture_path.exists():
        return
    img = cv2.imread(str(fixture_path))
    preprocessor = ImagePreprocessor()
    deskewed, angle = preprocessor.estimate_and_correct_skew(img)
    assert abs(angle) >= 4.0
    assert abs(abs(angle) - 7.0) < 2.0


def test_end_to_end_preprocess_generates_valid_pdf():
    preprocessor = ImagePreprocessor()
    img = _create_synthetic_invoice_image()

    _, enc = cv2.imencode(".png", img)
    raw_bytes = enc.tobytes()

    result = preprocessor.preprocess(raw_bytes)
    assert isinstance(result, PreprocessedImageResult)
    assert len(result.processed_image_bytes) > 0
    assert len(result.pdf_bytes) > 0
    assert result.pdf_bytes.startswith(b"%PDF-")

    # Validate that PDF can be parsed by fitz
    doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    assert len(doc) == 1
    page = doc.load_page(0)
    assert page.rect.width > 200
    assert page.rect.height > 200
    doc.close()


def test_processed_page_bbox_maps_back_through_deskew_perspective_and_pdf_scale():
    """Regression: image evidence bboxes stayed in processed-PDF points while the viewer
    shows the original photo, so boxes drifted after crop/perspective/deskew."""
    from invoiceflow.domain.documents.models import BoundingBox, CoordinateSystem

    crop = np.array([[1, 0, -120], [0, 1, -80], [0, 0, 1]], dtype=np.float64)
    rotation = cv2.getRotationMatrix2D((300, 400), 7.0, 1.0)
    points_per_pixel = 72.0 / 150.0
    geom = GeometryTransform(
        applied_perspective=True,
        applied_deskew=True,
        deskew_angle=7.0,
        original_width=900,
        original_height=1200,
        perspective_matrix=crop.flatten().tolist(),
        inverse_perspective_matrix=np.linalg.inv(crop).flatten().tolist(),
        deskew_matrix=rotation.flatten().tolist(),
        pdf_points_per_pixel=points_per_pixel,
    )

    original_corners = np.array([[[300.0, 500.0]], [[420.0, 540.0]]])
    warped = cv2.perspectiveTransform(original_corners, crop)
    deskewed = cv2.transform(warped, rotation)
    page = deskewed[:, 0, :] * points_per_pixel
    processed_bbox = BoundingBox(
        page_index=0,
        x0=float(page[:, 0].min()),
        y0=float(page[:, 1].min()),
        x1=float(page[:, 0].max()),
        y1=float(page[:, 1].max()),
    )

    mapped = geom.map_page_bbox_to_original(processed_bbox)

    assert mapped.coordinate_system == CoordinateSystem.PIXELS
    assert (mapped.page_width, mapped.page_height) == (900, 1200)
    # The axis-aligned hull of the rotated box must still contain both original corners.
    assert mapped.x0 <= 300.0 + 1e-6 and mapped.y0 <= 500.0 + 1e-6
    assert mapped.x1 >= 420.0 - 1e-6 and mapped.y1 >= 540.0 - 1e-6
    assert mapped.x1 - mapped.x0 < 200 and mapped.y1 - mapped.y0 < 120


def _encoded_page(width: int, height: int) -> bytes:
    img = np.full((height, width, 3), 250, dtype=np.uint8)
    cv2.putText(img, "TOTAL 978,12", (40, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    return cv2.imencode(".png", img)[1].tobytes()


def test_large_photo_page_is_sized_so_ocr_does_not_upsample_beyond_the_cap():
    from invoiceflow.infrastructure.document.image_preprocessor import DOCLING_OCR_RENDER_DPI

    # An A4 scan at 300 DPI used to become an A2-sized page that Docling OCR re-rendered
    # at 216 DPI: ~18 MP per page, roughly twice the source pixels, for no extra detail.
    result = ImagePreprocessor(max_ocr_side_px=3000).preprocess(_encoded_page(2481, 3508))

    page = fitz.open(stream=result.pdf_bytes, filetype="pdf").load_page(0)
    ocr_long_side = max(page.rect.width, page.rect.height) * DOCLING_OCR_RENDER_DPI / 72.0
    assert ocr_long_side <= 3000 + 1
    assert result.transform.pdf_points_per_pixel * result.transform.processed_height == (
        pytest.approx(page.rect.height)
    )


def test_small_photo_keeps_the_default_page_scale():
    result = ImagePreprocessor(max_ocr_side_px=3000).preprocess(_encoded_page(420, 740))

    assert result.transform.pdf_points_per_pixel == pytest.approx(72.0 / 150.0)
