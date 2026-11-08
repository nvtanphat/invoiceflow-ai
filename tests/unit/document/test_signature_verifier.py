import base64
from datetime import datetime, timedelta, timezone
import hashlib
from lxml import etree
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from invoiceflow.domain.invoices.models import VerificationStatus
from invoiceflow.infrastructure.document.signature_verifier import XMLSignatureVerifier


def _generate_ca_and_cert(expired: bool = False):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Root CA Quoc Gia"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Vietnam National Root CA"),
    ])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    cert_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert_subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cong ty Co phan Thuong mai Alpha VN"),
        x509.NameAttribute(NameOID.COMMON_NAME, "MST:0109998888"),
    ])

    if expired:
        not_before = now - timedelta(days=60)
        not_after = now - timedelta(days=1)
    else:
        not_before = now - timedelta(days=1)
        not_after = now + timedelta(days=180)

    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(cert_subject)
        .issuer_name(ca_name)
        .public_key(cert_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(ca_key, hashes.SHA256())
    )

    return ca_cert, leaf_cert, cert_key


def _build_signed_xml(
    leaf_cert: x509.Certificate,
    cert_key: rsa.RSAPrivateKey,
    doc_id: str = "data",
    data_content: str = "<TTChung><So>0008899</So></TTChung>",
    tamper_data_after_digest: bool = False,
    tamper_signature_value: bool = False,
    external_uri: bool = False,
    duplicate_id: bool = False,
) -> bytes:
    root = etree.Element("HDon")
    data_el = etree.SubElement(root, "DLHDon", id=doc_id)
    sub = etree.fromstring(f"<data>{data_content}</data>")
    for child in sub:
        data_el.append(child)

    if duplicate_id:
        # Signature wrapping attack: inject duplicate element with same id
        etree.SubElement(root, "EvilWrap", id=doc_id)

    # Compute genuine digest
    ref_uri = "https://external.com/invoice" if external_uri else f"#{doc_id}"
    c14n_data = etree.tostring(data_el, method="c14n")
    digest_val = base64.b64encode(hashlib.sha256(c14n_data).digest()).decode("ascii")

    if tamper_data_after_digest:
        # Mutate data inside node after digest was computed
        sub_mut = data_el.find(".//So")
        if sub_mut is not None:
            sub_mut.text = "9999999"

    sig_el = etree.SubElement(root, "{http://www.w3.org/2000/09/xmldsig#}Signature")
    si_el = etree.SubElement(sig_el, "{http://www.w3.org/2000/09/xmldsig#}SignedInfo")
    etree.SubElement(si_el, "{http://www.w3.org/2000/09/xmldsig#}CanonicalizationMethod", Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    etree.SubElement(si_el, "{http://www.w3.org/2000/09/xmldsig#}SignatureMethod", Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")
    ref_el = etree.SubElement(si_el, "{http://www.w3.org/2000/09/xmldsig#}Reference", URI=ref_uri)
    etree.SubElement(ref_el, "{http://www.w3.org/2000/09/xmldsig#}DigestMethod", Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
    dv_el = etree.SubElement(ref_el, "{http://www.w3.org/2000/09/xmldsig#}DigestValue")
    dv_el.text = digest_val

    # Sign canonical SignedInfo
    si_c14n = etree.tostring(si_el, method="c14n")
    sig_bytes = cert_key.sign(si_c14n, padding.PKCS1v15(), hashes.SHA256())
    if tamper_signature_value:
        sig_bytes = b"bad_signature_bytes_that_are_forged"

    sv_el = etree.SubElement(sig_el, "{http://www.w3.org/2000/09/xmldsig#}SignatureValue")
    sv_el.text = base64.b64encode(sig_bytes).decode("ascii")

    ki_el = etree.SubElement(sig_el, "{http://www.w3.org/2000/09/xmldsig#}KeyInfo")
    xd_el = etree.SubElement(ki_el, "{http://www.w3.org/2000/09/xmldsig#}X509Data")
    xc_el = etree.SubElement(xd_el, "{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
    xc_el.text = base64.b64encode(leaf_cert.public_bytes(Encoding.DER)).decode("ascii")

    return etree.tostring(root)


def test_empty_xml_stream():
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(b"")
    assert res.status == VerificationStatus.NOT_CHECKED
    assert not res.is_valid


def test_malformed_xml():
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(b"<HDon><unclosed>")
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid


def test_xml_without_signature():
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(b"<HDon><DLHDon><So>1</So></DLHDon></HDon>")
    assert res.status == VerificationStatus.NOT_CHECKED
    assert not res.is_valid


def test_signature_missing_signature_value():
    verifier = XMLSignatureVerifier()
    xml_data = b"""<HDon>
      <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
        <SignedInfo></SignedInfo>
      </Signature>
    </HDon>"""
    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid


def test_signature_missing_x509_certificate():
    verifier = XMLSignatureVerifier()
    xml_data = b"""<HDon>
      <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
        <SignedInfo>
          <Reference URI="#data"><DigestValue>dGVzdA==</DigestValue></Reference>
        </SignedInfo>
        <SignatureValue>c2ln</SignatureValue>
      </Signature>
    </HDon>"""
    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.UNVERIFIED
    assert not res.is_valid


def test_expired_xml_signature_certificate():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=True)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key)
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "hết hạn" in (res.details or "")


def test_external_uri_reference_rejected():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key, external_uri=True)
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "tham chiếu URI bên ngoài bị chặn" in (res.details or "")


def test_xml_signature_wrapping_duplicate_id_rejected():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key, duplicate_id=True)
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "XML Signature Wrapping" in (res.details or "")


def test_tampered_xml_content_detected_by_digest_mismatch():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key, tamper_data_after_digest=True)
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "DigestValue không khớp" in (res.details or "")


def test_tampered_signature_value_cryptographic_failure():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key, tamper_signature_value=True)
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "Chữ ký số mật mã không hợp lệ" in (res.details or "")


def test_valid_signature_unverified_ca_without_trust_anchor():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key)
    # Default verifier has no trusted CA anchors configured
    verifier = XMLSignatureVerifier(trusted_ca_certs=[])
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.UNVERIFIED
    assert not res.is_valid
    assert "chưa thể thẩm định chuỗi tin cậy CA" in (res.details or "")
    assert "MST:0109998888" in (res.signer_name or "")


def test_valid_signature_verified_with_configured_trusted_ca():
    ca_cert, leaf_cert, cert_key = _generate_ca_and_cert(expired=False)
    xml_bytes = _build_signed_xml(leaf_cert, cert_key)
    # Verifier with trusted CA provisioned
    verifier = XMLSignatureVerifier(trusted_ca_certs=[ca_cert])
    res = verifier.verify_xml_signature(xml_bytes)
    assert res.status == VerificationStatus.VERIFIED
    assert res.is_valid is True
    assert "MST:0109998888" in (res.signer_name or "")
    assert "Xác thực bởi CA tin cậy" in (res.details or "")
