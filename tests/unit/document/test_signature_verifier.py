import base64
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from invoiceflow.domain.invoices.models import VerificationStatus
from invoiceflow.infrastructure.document.signature_verifier import XMLSignatureVerifier


def _generate_test_certificate(valid_days: int = 365, expired: bool = False) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "VN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cong ty Co phan Dau tu Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, "MST:0101234567"),
    ])

    now = datetime.now(timezone.utc)
    if expired:
        not_before = now - timedelta(days=valid_days + 10)
        not_after = now - timedelta(days=1)
    else:
        not_before = now - timedelta(days=1)
        not_after = now + timedelta(days=valid_days)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return base64.b64encode(cert.public_bytes(Encoding.DER)).decode("ascii")


def test_empty_xml_stream():
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(b"")
    assert res.status == VerificationStatus.NOT_CHECKED
    assert not res.is_valid


def test_malformed_xml():
    verifier = XMLSignatureVerifier()
    res = verifier.verify_xml_signature(b"<not closed")
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "Malformed XML" in (res.details or "")


def test_xml_without_signature():
    verifier = XMLSignatureVerifier()
    xml_data = b"<HDon><TTChung><KHMSHDon>1</KHMSHDon></TTChung></HDon>"
    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.NOT_CHECKED
    assert not res.is_valid


def test_signature_missing_digest_or_signature_value():
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
          <DigestValue>dGVzdA==</DigestValue>
        </SignedInfo>
        <SignatureValue>c2ln</SignatureValue>
      </Signature>
    </HDon>"""
    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.UNVERIFIED
    assert not res.is_valid


def test_valid_xml_signature_and_certificate():
    verifier = XMLSignatureVerifier()
    cert_b64 = _generate_test_certificate(valid_days=30, expired=False)
    xml_data = f"""<HDon>
      <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
        <SignedInfo>
          <DigestValue>dGVzdGRpZ2VzdA==</DigestValue>
        </SignedInfo>
        <SignatureValue>dGVzdHNpZ25hdHVyZQ==</SignatureValue>
        <KeyInfo>
          <X509Data>
            <X509Certificate>{cert_b64}</X509Certificate>
          </X509Data>
        </KeyInfo>
      </Signature>
    </HDon>""".encode("utf-8")

    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.VERIFIED
    assert res.is_valid
    assert "MST:0101234567" in (res.signer_name or "")
    assert res.certificate_serial is not None


def test_expired_xml_signature_certificate():
    verifier = XMLSignatureVerifier()
    cert_b64 = _generate_test_certificate(valid_days=30, expired=True)
    xml_data = f"""<HDon>
      <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
        <SignedInfo>
          <DigestValue>dGVzdGRpZ2VzdA==</DigestValue>
        </SignedInfo>
        <SignatureValue>dGVzdHNpZ25hdHVyZQ==</SignatureValue>
        <KeyInfo>
          <X509Data>
            <X509Certificate>{cert_b64}</X509Certificate>
          </X509Data>
        </KeyInfo>
      </Signature>
    </HDon>""".encode("utf-8")

    res = verifier.verify_xml_signature(xml_data)
    assert res.status == VerificationStatus.FAILED
    assert not res.is_valid
    assert "hết hạn" in (res.details or "")
