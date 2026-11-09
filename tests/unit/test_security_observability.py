from unittest.mock import AsyncMock
import fitz
import pytest

from invoiceflow.api.routers.health import metrics, readiness
from invoiceflow.application.ingestion.preflight import IngestionPreflight, PreflightError
from invoiceflow.infrastructure.logging.observability import (
    PIIRedactingFilter,
    build_structured_log_payload,
)


def test_preflight_rejects_corrupted_pdf():
    preflight = IngestionPreflight()
    corrupted_pdf = b"%PDF-1.4\ncorrupted gibberish not a real pdf"
    with pytest.raises(PreflightError) as exc_info:
        preflight.inspect_and_validate(filename="bad.pdf", content=corrupted_pdf)
    assert "corrupted or invalid pdf format" in str(exc_info.value).lower()


def test_preflight_rejects_encrypted_pdf():
    preflight = IngestionPreflight()
    doc = fitz.open()
    doc.new_page()
    enc_bytes = doc.write(
        encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123"
    )
    doc.close()

    with pytest.raises(PreflightError) as exc_info:
        preflight.inspect_and_validate(filename="locked.pdf", content=enc_bytes)
    assert "encrypted/password-protected" in str(exc_info.value).lower()


def test_preflight_rejects_xml_xxe_and_dtd_case_insensitive():
    preflight = IngestionPreflight()

    # Lowercase doctype
    xxe1 = b"<?xml version='1.0'?><!doctype html system 'http://127.0.0.1/evil.dtd'><root/>"
    with pytest.raises(PreflightError) as exc1:
        preflight.inspect_and_validate(filename="xxe1.xml", content=xxe1)
    assert "security violation" in str(exc1.value).lower()

    # Mixed-case entity
    xxe2 = b"<?xml version='1.0'?><!Entity % test SYSTEM 'file:///etc/passwd'><root/>"
    with pytest.raises(PreflightError) as exc2:
        preflight.inspect_and_validate(filename="xxe2.xml", content=xxe2)
    assert "security violation" in str(exc2.value).lower()

    # XInclude
    xinclude = b"<?xml version='1.0'?><root><xinclude:include href='/etc/shadow'/></root>"
    with pytest.raises(PreflightError) as exc3:
        preflight.inspect_and_validate(filename="xi.xml", content=xinclude)
    assert "security violation" in str(exc3.value).lower()


def test_pii_redactor_masks_sensitive_data():
    sample_text = (
        "User logged in with Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test and "
        'credentials {"password": "SuperSecretPassword123!", "api_key": "sk-1234567890abcdef1234567890"} '
        "with credit card 4111-2222-3333-4444"
    )

    redacted = PIIRedactingFilter.redact(sample_text)

    assert "Bearer ***REDACTED***" in redacted
    assert "SuperSecretPassword123!" not in redacted
    assert "sk-1234567890abcdef1234567890" not in redacted
    assert "4111-2222-3333-4444" not in redacted
    assert "****-****-****-****" in redacted


def test_structured_log_payload_construction():
    payload = build_structured_log_payload(
        stage="EXTRACTION",
        tenant_id="tenant-123",
        document_id="doc-456",
        job_id="job-789",
        duration_ms=125.456,
        cost_usd=0.00234,
        error_code="NONE",
    )

    assert payload["stage"] == "EXTRACTION"
    assert payload["tenant_id"] == "tenant-123"
    assert payload["duration_ms"] == 125.46
    assert payload["cost_usd"] == 0.0023


@pytest.mark.asyncio
async def test_health_metrics_and_readiness():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    res_metrics = await metrics(session=mock_session)
    assert res_metrics["status"] == "healthy"
    assert res_metrics["memory"]["total_mb"] > 0
    assert res_metrics["memory"]["available_mb"] > 0

    res_ready = await readiness(session=mock_session)
    assert res_ready["status"] == "ready"
    assert res_ready["database"] == "connected"
