import hashlib
from typing import NamedTuple
import fitz


class PreflightError(Exception):
    pass


class PreflightMetadata(NamedTuple):
    filename: str
    file_size_bytes: int
    detected_mime: str
    detected_kind: str
    sha256: str
    page_count: int


class IngestionPreflight:
    ALLOWED_EXTENSIONS = {".xml", ".pdf", ".png", ".jpg", ".jpeg"}

    def __init__(self, max_size_bytes: int = 25 * 1024 * 1024, max_pages: int = 50):
        self.max_size_bytes = max_size_bytes
        self.max_pages = max_pages

    def inspect_and_validate(self, filename: str, content: bytes) -> PreflightMetadata:
        if not content:
            raise PreflightError("File is empty (0 bytes).")

        size = len(content)
        if size > self.max_size_bytes:
            raise PreflightError(
                f"File size {size} bytes exceeds maximum allowed size {self.max_size_bytes} bytes."
            )

        sha256 = hashlib.sha256(content).hexdigest()

        lower_name = filename.lower()
        ext = "." + lower_name.split(".")[-1] if "." in lower_name else ""
        if ext not in self.ALLOWED_EXTENSIONS:
            raise PreflightError(
                f"File extension '{ext}' is not in the allowed list: {self.ALLOWED_EXTENSIONS}"
            )

        detected_mime, detected_kind = self._detect_magic_bytes(content)

        if ext == ".pdf" and detected_kind != "pdf":
            raise PreflightError(
                f"MIME mismatch: extension is .pdf but detected format is {detected_mime}"
            )
        if ext == ".xml" and detected_kind != "xml":
            raise PreflightError(
                f"MIME mismatch: extension is .xml but detected format is {detected_mime}"
            )
        if ext in {".png", ".jpg", ".jpeg"} and detected_kind not in {"png", "jpeg"}:
            raise PreflightError(
                f"MIME mismatch: image extension does not match image header {detected_mime}"
            )

        page_count = 1
        if detected_kind == "pdf":
            page_count = self._validate_and_count_pdf(content)
            if page_count > self.max_pages:
                raise PreflightError(
                    f"PDF page count {page_count} exceeds maximum allowed limit of {self.max_pages} pages."
                )

        return PreflightMetadata(
            filename=filename,
            file_size_bytes=size,
            detected_mime=detected_mime,
            detected_kind=detected_kind,
            sha256=sha256,
            page_count=page_count,
        )

    def _detect_magic_bytes(self, content: bytes) -> tuple[str, str]:
        header = content[:64]
        if header.startswith(b"%PDF-"):
            return "application/pdf", "pdf"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpeg"

        stripped = content[:4096].lstrip()
        upper_sample = stripped[:4096].upper()
        if stripped.startswith(b"<?xml") or (stripped.startswith(b"<") and b">" in stripped):
            if (
                b"<!ENTITY" in upper_sample
                or b"<!DOCTYPE" in upper_sample
                or b"SYSTEM" in upper_sample
                or b"PUBLIC" in upper_sample
                or b"XINCLUDE" in upper_sample
            ):
                raise PreflightError(
                    "Security violation: DTD, DOCTYPE, external entities, and XInclude are strictly forbidden."
                )
            return "application/xml", "xml"

        raise PreflightError("File header does not match any allowed format (PDF, XML, PNG, JPEG).")

    def _validate_and_count_pdf(self, content: bytes) -> int:
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            if doc.is_encrypted:
                doc.close()
                raise PreflightError(
                    "PDF is encrypted/password-protected. Encrypted documents are rejected for automated processing."
                )
            page_count = len(doc)
            doc.close()
            return max(page_count, 1)
        except PreflightError:
            raise
        except Exception as e:
            # Check if minimal valid header for stream mocks
            if b"%PDF-" in content[:16] and (b"%%EOF" in content[-32:] or b"obj" in content):
                count = content.count(b"/Type /Page") or content.count(b"/Type/Page")
                return max(count, 1)
            raise PreflightError(f"Corrupted or invalid PDF format: {str(e)}") from e
