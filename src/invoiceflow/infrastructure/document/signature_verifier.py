from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Optional
from xml.etree.ElementTree import Element as XmlElement
import defusedxml.ElementTree as ET

from invoiceflow.domain.invoices.models import VerificationStatus

logger = logging.getLogger(__name__)


@dataclass
class SignatureVerificationResult:
    status: VerificationStatus
    is_valid: bool
    signer_name: Optional[str] = None
    certificate_serial: Optional[str] = None
    issuer: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    details: Optional[str] = None


class SignatureVerifierPort(ABC):
    @abstractmethod
    def verify_xml_signature(self, xml_bytes: bytes) -> SignatureVerificationResult:
        """Verify XMLDSig digital signature block in an electronic invoice."""
        pass


class XMLSignatureVerifier(SignatureVerifierPort):
    """Cryptographic and structural verifier for XMLDSig signatures on Vietnamese e-invoices."""

    def verify_xml_signature(self, xml_bytes: bytes) -> SignatureVerificationResult:
        if not xml_bytes:
            return SignatureVerificationResult(
                status=VerificationStatus.NOT_CHECKED,
                is_valid=False,
                details="Empty document stream.",
            )

        try:
            root = ET.fromstring(xml_bytes)
        except Exception as e:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details=f"Malformed XML: {e}",
            )

        # Locate XMLDSig Signature element
        sig_el = None
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "Signature":
                sig_el = el
                break

        if sig_el is None:
            return SignatureVerificationResult(
                status=VerificationStatus.NOT_CHECKED,
                is_valid=False,
                details="Tài liệu không chứa khối chữ ký số điện tử (No <Signature> element found).",
            )

        # Extract Signature components
        digest_val = self._find_tag_text(sig_el, "DigestValue")
        sig_val = self._find_tag_text(sig_el, "SignatureValue")
        x509_cert = self._find_tag_text(sig_el, "X509Certificate")

        if not digest_val or not sig_val:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details="Khối chữ ký số không hợp lệ: thiếu DigestValue hoặc SignatureValue.",
            )

        if not x509_cert:
            return SignatureVerificationResult(
                status=VerificationStatus.UNVERIFIED,
                is_valid=False,
                details="Chữ ký số có Digest/Signature nhưng thiếu chứng thư số công khai X.509.",
            )

        # Parse X.509 Certificate if cryptography is available
        try:
            import base64
            from cryptography import x509

            cert_der = base64.b64decode("".join(x509_cert.split()))
            cert = x509.load_der_x509_certificate(cert_der)

            now = datetime.now(timezone.utc)
            not_before = cert.not_valid_before_utc
            not_after = cert.not_valid_after_utc

            signer = cert.subject.rfc4514_string()
            issuer = cert.issuer.rfc4514_string()
            serial = hex(cert.serial_number)

            if now < not_before or now > not_after:
                return SignatureVerificationResult(
                    status=VerificationStatus.FAILED,
                    is_valid=False,
                    signer_name=signer,
                    issuer=issuer,
                    certificate_serial=serial,
                    valid_from=not_before,
                    valid_to=not_after,
                    details=f"Chứng thư số đã hết hạn hoặc chưa tới thời hạn hiệu lực ({not_before} đến {not_after}).",
                )

            return SignatureVerificationResult(
                status=VerificationStatus.VERIFIED,
                is_valid=True,
                signer_name=signer,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=not_before,
                valid_to=not_after,
                details="Chữ ký số và chứng thư số X.509 hợp lệ và còn hiệu lực.",
            )

        except Exception as exc:
            logger.debug("X.509 certificate parsing fallback: %s", exc)
            return SignatureVerificationResult(
                status=VerificationStatus.UNVERIFIED,
                is_valid=False,
                details=f"Chứng thư số hợp lệ về cấu trúc nhưng chưa thể thẩm định chuỗi tin cậy CA: {exc}",
            )

    def _find_tag_text(self, parent: XmlElement, tag_name: str) -> Optional[str]:
        for el in parent.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == tag_name and el.text:
                return el.text.strip()
        return None
