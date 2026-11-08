from abc import ABC, abstractmethod
import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from typing import Any, List, Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import defusedxml.ElementTree as DefusedET
from lxml import etree

from invoiceflow.domain.invoices.models import VerificationStatus

logger = logging.getLogger(__name__)

DS_NS = "http://www.w3.org/2000/09/xmldsig#"


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
    """Cryptographic and structural verifier for XMLDSig signatures on Vietnamese e-invoices.

    Implements W3C XML Signature syntax & processing, strict algorithm allowlisting,
    anti-wrapping (XSW) guards, signed-scope containment, and X.509 certificate validation.
    """

    ALLOWED_SIGNATURE_ALGORITHMS = {
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256": hashes.SHA256(),
    }

    ALLOWED_DIGEST_ALGORITHMS = {
        "http://www.w3.org/2001/04/xmlenc#sha256": hashlib.sha256,
    }

    ALLOWED_TRANSFORMS = {
        "http://www.w3.org/2000/09/xmldsig#enveloped-signature",
        "http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
        "http://www.w3.org/2001/10/xml-exc-c14n#",
    }

    def __init__(
        self,
        trusted_ca_certs: Optional[List[x509.Certificate]] = None,
        allow_sha1: bool = False,
    ):
        self.trusted_ca_certs = trusted_ca_certs or []
        self.allow_sha1 = allow_sha1

    def verify_xml_signature(self, xml_bytes: bytes) -> SignatureVerificationResult:
        if not xml_bytes or not xml_bytes.strip():
            return SignatureVerificationResult(
                status=VerificationStatus.NOT_CHECKED,
                is_valid=False,
                details="Empty document stream.",
            )

        # 1. Defused XML safety parse to block XXE / entity expansion
        try:
            DefusedET.fromstring(xml_bytes)
        except Exception as exc:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details=f"Malformed or unsafe XML payload: {exc}",
            )

        # 2. Parse into lxml with strict security restrictions (no network, no entities)
        try:
            parser = etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                dtd_validation=False,
                load_dtd=False,
            )
            root = etree.fromstring(xml_bytes, parser=parser)
        except Exception as exc:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details=f"LXML parser failed: {exc}",
            )

        # Locate all XMLDSig Signature elements (support multiple signatures: seller, buyer)
        sig_nodes = root.findall(f".//{{{DS_NS}}}Signature")
        if not sig_nodes:
            sig_nodes = root.findall(".//Signature")

        if not sig_nodes:
            return SignatureVerificationResult(
                status=VerificationStatus.NOT_CHECKED,
                is_valid=False,
                details="Tài liệu không chứa khối chữ ký số điện tử (No <Signature> element found).",
            )

        results: List[SignatureVerificationResult] = []
        for sig_node in sig_nodes:
            res = self._verify_single_signature(root, sig_node)
            results.append(res)
            # Fail-fast on any tampered/forged signature
            if res.status == VerificationStatus.FAILED:
                return res

        # Strict Multi-Signature Policy:
        # 1. Any FAILED signature fails the whole document.
        failed = [r for r in results if r.status == VerificationStatus.FAILED]
        if failed:
            return failed[0]

        # 2. If any signature is UNVERIFIED, the document cannot be marked fully VERIFIED.
        unverified = [r for r in results if r.status == VerificationStatus.UNVERIFIED]
        if unverified:
            return unverified[0]

        # 3. All signatures must be VERIFIED for the document to be VERIFIED.
        verified = [r for r in results if r.status == VerificationStatus.VERIFIED]
        if verified and len(verified) == len(results):
            return verified[0]

        return results[0]

    def _verify_single_signature(
        self, root: etree._Element, sig_node: etree._Element
    ) -> SignatureVerificationResult:
        si_node = sig_node.find(f"{{{DS_NS}}}SignedInfo")
        if si_node is None:
            si_node = sig_node.find("SignedInfo")
        if si_node is None:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details="Khối chữ ký số không hợp lệ: thiếu thẻ <SignedInfo>.",
            )

        sig_val_text = self._find_text(sig_node, "SignatureValue")
        cert_text = self._find_text(sig_node, "X509Certificate")

        if not sig_val_text:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details="Khối chữ ký số không hợp lệ: thiếu SignatureValue.",
            )

        if not cert_text:
            return SignatureVerificationResult(
                status=VerificationStatus.UNVERIFIED,
                is_valid=False,
                details="Chữ ký số thiếu chứng thư số công khai X.509.",
            )

        # Parse X.509 Certificate
        try:
            cert_der = base64.b64decode("".join(cert_text.split()))
            cert = x509.load_der_x509_certificate(cert_der)
            public_key = cert.public_key()
        except Exception as exc:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                details=f"Chứng thư số X.509 không hợp lệ hoặc bị lỗi định dạng DER: {exc}",
            )

        signer_name = cert.subject.rfc4514_string()
        issuer = cert.issuer.rfc4514_string()
        serial = hex(cert.serial_number)
        now = datetime.now(timezone.utc)
        valid_from = cert.not_valid_before_utc
        valid_to = cert.not_valid_after_utc

        # Check Certificate Expiration
        if now < valid_from or now > valid_to:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details=f"Chứng thư số đã hết hạn hoặc chưa tới thời hạn hiệu lực ({valid_from} đến {valid_to}).",
            )

        # Check KeyUsage Extension (must include digital_signature or content_commitment)
        try:
            ku_ext = cert.extensions.get_extension_for_oid(x509.OID_KEY_USAGE)
            ku = ku_ext.value
            if not (ku.digital_signature or ku.content_commitment):
                return SignatureVerificationResult(
                    status=VerificationStatus.FAILED,
                    is_valid=False,
                    signer_name=signer_name,
                    issuer=issuer,
                    certificate_serial=serial,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    details="Chứng thư số không hợp lệ: KeyUsage không cho phép ký số (thiếu digitalSignature / contentCommitment).",
                )
        except x509.ExtensionNotFound:
            pass

        # Verify Signature Algorithm
        sig_algo, algo_err = self._get_signature_algorithm(si_node)
        if algo_err:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                details=algo_err,
            )

        # 3. Check All Signed References
        ref_nodes = si_node.findall(f"{{{DS_NS}}}Reference")
        if not ref_nodes:
            ref_nodes = si_node.findall("Reference")
        if not ref_nodes:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                details="SignedInfo thiếu phần tử <Reference>.",
            )

        for ref_node in ref_nodes:
            digest_ok, digest_err = self._verify_reference_digest(root, ref_node)
            if not digest_ok:
                return SignatureVerificationResult(
                    status=VerificationStatus.FAILED,
                    is_valid=False,
                    signer_name=signer_name,
                    issuer=issuer,
                    certificate_serial=serial,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    details=digest_err,
                )

        # 4. Cryptographic Signature Verification over Canonicalized SignedInfo
        try:
            c14n_signed_info = etree.tostring(si_node, method="c14n")
            sig_bytes = base64.b64decode("".join(sig_val_text.split()))
            public_key.verify(sig_bytes, c14n_signed_info, padding.PKCS1v15(), sig_algo)
        except InvalidSignature:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details="Chữ ký số mật mã không hợp lệ: SignatureValue không khớp với SignedInfo (chữ ký giả mạo hoặc dữ liệu bị sửa đổi).",
            )
        except Exception as exc:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details=f"Lỗi kiểm tra mật mã chữ ký số: {exc}",
            )

        # 5. CA Trust Chain Verification
        return self._evaluate_ca_trust(cert, signer_name, issuer, serial, valid_from, valid_to)

    def _verify_reference_digest(
        self, root: etree._Element, ref_node: etree._Element
    ) -> tuple[bool, Optional[str]]:
        uri = (ref_node.get("URI") or "").strip()

        # Security check: Block external URI resolution
        if ":" in uri and not uri.startswith("#"):
            return False, "Bảo mật vi phạm: tham chiếu URI bên ngoài bị chặn hoàn toàn."

        # Anti-wrapping & target element resolution
        if uri.startswith("#"):
            target_id = uri.lstrip("#")
            import re

            if not re.match(r"^[A-Za-z0-9_-]+$", target_id):
                return (
                    False,
                    f"Bảo mật vi phạm: id tham chiếu '{target_id}' không hợp lệ hoặc chứa ký tự đặc biệt.",
                )
            candidates = root.xpath("//*[@id=$tid or @Id=$tid or @ID=$tid]", tid=target_id)
            if len(candidates) == 0:
                return (
                    False,
                    f"Cảnh báo cấu trúc: không tìm thấy phần tử được ký có id '{target_id}'.",
                )
            if len(candidates) > 1:
                return (
                    False,
                    f"Cảnh báo XML Signature Wrapping: phát hiện {len(candidates)} phần tử trùng lặp id '{target_id}'.",
                )
            target_el = candidates[0]
        else:
            # Empty URI refers to root document
            target_el = root

        # Scope Verification: Target MUST contain or be the invoice data
        dlhdon_node = root.find(".//DLHDon")
        if dlhdon_node is None:
            dlhdon_node = root.find(".//HDon") or root.find(".//Invoice")

        if dlhdon_node is not None:
            # Check if target_el encloses or is the invoice data node
            is_valid_scope = (
                target_el == root
                or target_el == dlhdon_node
                or dlhdon_node in target_el.iterdescendants()
            )
            if not is_valid_scope:
                return (
                    False,
                    "Cảnh báo bảo mật: Dữ liệu hóa đơn không nằm trong phạm vi được bảo vệ bởi chữ ký số (Detached target mismatch).",
                )

        # Check Transforms
        is_enveloped = False
        transforms = ref_node.findall(f".//{{{DS_NS}}}Transform") or ref_node.findall(
            ".//Transform"
        )
        for tr in transforms:
            algo = tr.get("Algorithm", "")
            if algo not in self.ALLOWED_TRANSFORMS:
                return False, f"Thuật toán biến đổi Transform '{algo}' không được phê duyệt."
            if "enveloped-signature" in algo:
                is_enveloped = True

        # Copy target element and strip Signature if enveloped
        work_node = copy.deepcopy(target_el)
        if is_enveloped:
            for s in work_node.xpath(f".//{{{DS_NS}}}Signature | .//Signature"):
                parent = s.getparent()
                if parent is not None:
                    parent.remove(s)

        # Canonicalize target element
        c14n_bytes = etree.tostring(work_node, method="c14n")

        # Extract and compare digest
        expected_digest = self._find_text(ref_node, "DigestValue")
        if not expected_digest:
            return False, "Thiếu thẻ DigestValue trong Reference."

        digest_algo, digest_err = self._get_digest_algorithm(ref_node)
        if digest_err:
            return False, digest_err

        computed_digest = base64.b64encode(digest_algo(c14n_bytes).digest()).decode("ascii")

        if computed_digest != "".join(expected_digest.split()):
            return (
                False,
                f"Giá trị DigestValue không khớp (Computed: {computed_digest}, Expected: {expected_digest}): Dữ liệu hóa đơn đã bị chỉnh sửa sau khi ký.",
            )

        return True, None

    def _evaluate_ca_trust(
        self,
        cert: x509.Certificate,
        signer_name: str,
        issuer: str,
        serial: str,
        valid_from: datetime,
        valid_to: datetime,
    ) -> SignatureVerificationResult:
        if not self.trusted_ca_certs:
            return SignatureVerificationResult(
                status=VerificationStatus.UNVERIFIED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details="Chữ ký số mật mã và Digest hợp lệ, nhưng chưa thể thẩm định chuỗi tin cậy CA (Cần cấu hình CA Trust Anchor theo quy định).",
            )

        matched_ca = None
        for ca_cert in self.trusted_ca_certs:
            if ca_cert.subject == cert.issuer:
                try:
                    ca_pub = ca_cert.public_key()
                    ca_pub.verify(
                        cert.signature,
                        cert.tbs_certificate_bytes,
                        padding.PKCS1v15(),
                        cert.signature_hash_algorithm,
                    )
                    matched_ca = ca_cert
                    break
                except Exception:
                    continue

        if matched_ca is not None:
            return SignatureVerificationResult(
                status=VerificationStatus.VERIFIED,
                is_valid=True,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details=f"Chữ ký số và chuỗi tin cậy X.509 hợp lệ (Xác thực bởi CA tin cậy: {matched_ca.subject.rfc4514_string()}).",
            )
        else:
            return SignatureVerificationResult(
                status=VerificationStatus.FAILED,
                is_valid=False,
                signer_name=signer_name,
                issuer=issuer,
                certificate_serial=serial,
                valid_from=valid_from,
                valid_to=valid_to,
                details="Chứng thư số tự ký hoặc không thuộc danh sách các Tổ chức chứng thực chữ ký số (CA) được tin cậy.",
            )

    def _get_signature_algorithm(
        self, si_node: etree._Element
    ) -> tuple[Optional[hashes.HashAlgorithm], Optional[str]]:
        sm_node = si_node.find(f"{{{DS_NS}}}SignatureMethod")
        if sm_node is None:
            sm_node = si_node.find("SignatureMethod")
        if sm_node is None:
            return None, "Thiếu thẻ <SignatureMethod> trong SignedInfo."

        algo_uri = sm_node.get("Algorithm", "").strip()
        if "rsa-sha1" in algo_uri.lower():
            if not self.allow_sha1:
                return (
                    None,
                    "Thuật toán chữ ký SHA-1 bị từ chối theo chính sách bảo mật production.",
                )
            return hashes.SHA1(), None

        if algo_uri in self.ALLOWED_SIGNATURE_ALGORITHMS:
            return self.ALLOWED_SIGNATURE_ALGORITHMS[algo_uri], None

        return None, f"Thuật toán chữ ký không được hỗ trợ hoặc không an toàn: '{algo_uri}'."

    def _get_digest_algorithm(
        self, ref_node: etree._Element
    ) -> tuple[Optional[Any], Optional[str]]:
        dm_node = ref_node.find(f"{{{DS_NS}}}DigestMethod")
        if dm_node is None:
            dm_node = ref_node.find("DigestMethod")
        if dm_node is None:
            return None, "Thiếu thẻ <DigestMethod> trong Reference."

        algo_uri = dm_node.get("Algorithm", "").strip()
        if "sha1" in algo_uri.lower():
            if not self.allow_sha1:
                return (
                    None,
                    "Thuật toán DigestMethod SHA-1 bị từ chối theo chính sách bảo mật production.",
                )
            return hashlib.sha1, None

        if algo_uri in self.ALLOWED_DIGEST_ALGORITHMS:
            return self.ALLOWED_DIGEST_ALGORITHMS[algo_uri], None

        return None, f"Thuật toán DigestMethod không được hỗ trợ hoặc không an toàn: '{algo_uri}'."

    def _find_text(self, parent: etree._Element, tag_name: str) -> Optional[str]:
        el = parent.find(f".//{{{DS_NS}}}{tag_name}")
        if el is None:
            el = parent.find(f".//{tag_name}")
        if el is not None and el.text:
            return el.text.strip()
        return None
