from dataclasses import dataclass
from typing import Optional, Tuple
import cv2
import fitz
import numpy as np

from invoiceflow.domain.documents.models import BoundingBox, CoordinateSystem

# Processed images are embedded at a 150 DPI page equivalent (72 PDF points per inch).
PDF_POINTS_PER_PIXEL = 72.0 / 150.0


@dataclass
class ImageQualityMetrics:
    blur_score: float
    brightness_mean: float
    contrast_std: float
    is_blurry: bool
    is_low_contrast: bool
    is_uneven_illumination: bool


@dataclass
class GeometryTransform:
    applied_crop: bool = False
    applied_perspective: bool = False
    applied_deskew: bool = False
    deskew_angle: float = 0.0
    applied_enhancement: bool = False
    original_width: int = 0
    original_height: int = 0
    processed_width: int = 0
    processed_height: int = 0
    perspective_matrix: Optional[list[float]] = None
    inverse_perspective_matrix: Optional[list[float]] = None
    deskew_matrix: Optional[list[float]] = None
    pdf_points_per_pixel: float = PDF_POINTS_PER_PIXEL

    def map_point_to_original(self, x: float, y: float) -> Tuple[float, float]:
        """Processed-image pixel -> original-image pixel (undo deskew, then perspective)."""
        pt = np.array([[[x, y]]], dtype=np.float64)
        if self.applied_deskew and self.deskew_matrix is not None:
            forward = np.array(self.deskew_matrix, dtype=np.float64).reshape((2, 3))
            pt = cv2.transform(pt, cv2.invertAffineTransform(forward))
        if self.applied_perspective and self.inverse_perspective_matrix is not None:
            m = np.array(self.inverse_perspective_matrix, dtype=np.float64).reshape((3, 3))
            pt = cv2.perspectiveTransform(pt, m)
        return float(pt[0, 0, 0]), float(pt[0, 0, 1])

    def map_page_bbox_to_original(self, bbox: BoundingBox) -> BoundingBox:
        """Bbox on the generated processed PDF page -> original image pixels for the viewer."""
        scale = 1.0 / self.pdf_points_per_pixel
        x0, y0, x1, y1 = self.map_bbox_to_original(
            bbox.x0 * scale, bbox.y0 * scale, bbox.x1 * scale, bbox.y1 * scale
        )
        return bbox.model_copy(
            update={
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "coordinate_system": CoordinateSystem.PIXELS,
                "page_width": self.original_width,
                "page_height": self.original_height,
                "rotation": 0,
            }
        )

    def map_bbox_to_original(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> Tuple[float, float, float, float]:
        pts = [
            self.map_point_to_original(x0, y0),
            self.map_point_to_original(x1, y0),
            self.map_point_to_original(x1, y1),
            self.map_point_to_original(x0, y1),
        ]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class PreprocessedImageResult:
    original_image_bytes: bytes
    processed_image_bytes: bytes
    pdf_bytes: bytes
    quality: ImageQualityMetrics
    transform: GeometryTransform
    mime_type: str = "image/png"


class ImagePreprocessor:
    """Production-grade CPU-friendly image preprocessing using OpenCV.

    Handles real-world mobile capture artifacts: perspective distortion,
    complex backgrounds, shadows, uneven illumination, noise, and skew.
    Preserves original image bytes and bidirectional BBox mapping.
    """

    def __init__(
        self,
        blur_threshold: float = 65.0,
        min_document_area_ratio: float = 0.15,
        max_processing_dim: int = 2400,
    ):
        self._blur_threshold = blur_threshold
        self._min_document_area_ratio = min_document_area_ratio
        self._max_processing_dim = max_processing_dim

    def assess_quality(self, image: np.ndarray) -> ImageQualityMetrics:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness_mean = float(np.mean(gray))
        contrast_std = float(np.std(gray))

        # Check local illumination variance across 8x8 blocks
        h, w = gray.shape
        block_h = max(h // 8, 1)
        block_w = max(w // 8, 1)
        block_means = [
            float(np.mean(gray[r : r + block_h, c : c + block_w]))
            for r in range(0, h, block_h)
            for c in range(0, w, block_w)
        ]
        illumination_std = float(np.std(block_means)) if block_means else 0.0

        is_blurry = blur_score < self._blur_threshold
        is_low_contrast = contrast_std < 20.0
        is_uneven = illumination_std > 35.0 or brightness_mean < 50.0

        return ImageQualityMetrics(
            blur_score=round(blur_score, 2),
            brightness_mean=round(brightness_mean, 2),
            contrast_std=round(contrast_std, 2),
            is_blurry=is_blurry,
            is_low_contrast=is_low_contrast,
            is_uneven_illumination=is_uneven,
        )

    @staticmethod
    def _order_quad_points(pts: np.ndarray) -> np.ndarray:
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]  # top-left
        rect[2] = pts[np.argmax(s)]  # bottom-right

        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]  # top-right
        rect[3] = pts[np.argmax(diff)]  # bottom-left
        return rect

    def detect_document_boundary(self, image: np.ndarray) -> Optional[np.ndarray]:
        h, w = image.shape[:2]

        scale = 1.0
        max_dim = 1000
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            resized = cv2.resize(image, (int(w * scale), int(h * scale)))
        else:
            resized = image.copy()

        if len(resized.shape) == 3:
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        else:
            gray = resized

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area / (resized.shape[0] * resized.shape[1]) < self._min_document_area_ratio:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                scaled_pts = approx.reshape(4, 2).astype("float32") / scale
                return self._order_quad_points(scaled_pts)

        return None

    def correct_perspective(
        self, image: np.ndarray, quad_pts: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        tl, tr, br, bl = quad_pts

        width_a = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        width_b = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        max_w = max(int(width_a), int(width_b))

        height_a = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        height_b = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        max_h = max(int(height_a), int(height_b))

        dst = np.array(
            [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
            dtype="float32",
        )

        matrix = cv2.getPerspectiveTransform(quad_pts, dst)
        inv_matrix = np.linalg.inv(matrix)

        warped = cv2.warpPerspective(
            image, matrix, (max_w, max_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return warped, matrix, inv_matrix

    @staticmethod
    def estimate_and_correct_skew(image: np.ndarray) -> Tuple[np.ndarray, float]:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 100:
            return image, 0.0

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Only deskew if small noticeable skew between 0.5 and 15 degrees
        if abs(angle) < 0.5 or abs(angle) > 15.0:
            return image, 0.0

        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        deskewed = cv2.warpAffine(
            image, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return deskewed, float(angle)

    @staticmethod
    def enhance_lighting_and_shadows(image: np.ndarray) -> np.ndarray:
        """Removes harsh shadows and normalizes uneven lighting using background division."""
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        dilated = cv2.dilate(gray, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21)))
        bg = cv2.medianBlur(dilated, 21)
        diff = 255 - cv2.absdiff(gray, bg)
        norm = cv2.normalize(
            diff, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8UC1
        )

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(norm)

        if len(image.shape) == 3:
            # Reconstruct color image by blending normalized luminance
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            hsv[:, :, 2] = enhanced_gray
            return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return enhanced_gray

    def preprocess(
        self,
        image_bytes: bytes,
        force_enhancement: bool = False,
    ) -> PreprocessedImageResult:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image bytes. Unsupported or corrupted image file.")

        orig_h, orig_w = img.shape[:2]
        quality = self.assess_quality(img)

        transform = GeometryTransform(
            original_width=orig_w,
            original_height=orig_h,
            processed_width=orig_w,
            processed_height=orig_h,
        )

        curr_img = img

        # Step 1: Detect boundary & correct perspective if document does not cover whole frame
        quad = self.detect_document_boundary(curr_img)
        if quad is not None:
            warped, mat, inv_mat = self.correct_perspective(curr_img, quad)
            curr_img = warped
            transform.applied_crop = True
            transform.applied_perspective = True
            transform.perspective_matrix = mat.flatten().tolist()
            transform.inverse_perspective_matrix = inv_mat.flatten().tolist()

        # Step 2: Deskew if slightly tilted
        pre_deskew_h, pre_deskew_w = curr_img.shape[:2]
        deskewed, angle = self.estimate_and_correct_skew(curr_img)
        if abs(angle) >= 0.5:
            curr_img = deskewed
            transform.applied_deskew = True
            transform.deskew_angle = angle
            # Same rotation estimate_and_correct_skew applied, kept for mapping bboxes back.
            transform.deskew_matrix = (
                cv2.getRotationMatrix2D((pre_deskew_w // 2, pre_deskew_h // 2), angle, 1.0)
                .flatten()
                .tolist()
            )

        # Step 3: Enhance lighting and remove shadows conditionally
        if quality.is_uneven_illumination or quality.is_low_contrast or force_enhancement:
            curr_img = self.enhance_lighting_and_shadows(curr_img)
            transform.applied_enhancement = True

        proc_h, proc_w = curr_img.shape[:2]
        transform.processed_width = proc_w
        transform.processed_height = proc_h

        success, enc = cv2.imencode(".png", curr_img)
        processed_bytes = enc.tobytes() if success else image_bytes

        # Generate a clean single-page PDF containing the processed document image
        pdf_doc = fitz.open()
        page_w = proc_w * PDF_POINTS_PER_PIXEL
        page_h = proc_h * PDF_POINTS_PER_PIXEL
        page = pdf_doc.new_page(width=page_w, height=page_h)
        page.insert_image(fitz.Rect(0, 0, page_w, page_h), stream=processed_bytes)
        pdf_bytes = pdf_doc.tobytes(garbage=4, deflate=True)
        pdf_doc.close()

        return PreprocessedImageResult(
            original_image_bytes=image_bytes,
            processed_image_bytes=processed_bytes,
            pdf_bytes=pdf_bytes,
            quality=quality,
            transform=transform,
            mime_type="image/png",
        )
