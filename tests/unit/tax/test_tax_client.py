from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from invoiceflow.domain.invoices.models import VerificationStatus
from invoiceflow.infrastructure.tax.client import GeneralDepartmentOfTaxationClient


@pytest.mark.asyncio
async def test_gdt_client_blocks_when_no_credentials():
    client = GeneralDepartmentOfTaxationClient(api_token=None, client_cert_path=None)
    result = await client.verify_invoice_status(
        supplier_tax_id="0101234567",
        invoice_series="1C26TAA",
        invoice_number="0000001",
    )
    assert result.status == VerificationStatus.NOT_CHECKED
    assert not result.is_valid
    assert result.is_blocked is True
    assert result.blocker_code == "BLOCKED_EXTERNAL_DEPENDENCY"
    assert "Cần tài khoản kết nối TCT" in result.message


@pytest.mark.asyncio
async def test_gdt_client_verified_on_success():
    client = GeneralDepartmentOfTaxationClient(
        api_token="test-secret-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "valid": True,
        "tct_code": "TCT-VN-2026-9999",
        "message": "Hóa đơn hợp lệ theo dữ liệu TCT.",
    }

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.return_value = mock_response
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.VERIFIED
    assert result.is_valid is True
    assert result.tax_authority_code == "TCT-VN-2026-9999"
    assert not result.is_blocked


@pytest.mark.asyncio
async def test_gdt_client_failed_when_portal_reports_invalid():
    client = GeneralDepartmentOfTaxationClient(
        api_token="test-secret-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "valid": False,
        "message": "Hóa đơn không tồn tại trên hệ thống TCT.",
    }

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.return_value = mock_response
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.FAILED
    assert result.is_valid is False


@pytest.mark.asyncio
async def test_gdt_client_missing_valid_field_fails_closed():
    client = GeneralDepartmentOfTaxationClient(
        api_token="test-secret-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    # Response missing 'valid' boolean field
    mock_response.json.return_value = {"message": "Success without valid flag"}

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.return_value = mock_response
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.UNKNOWN
    assert result.is_valid is False
    assert "fail-closed" in result.message


@pytest.mark.asyncio
async def test_gdt_client_missing_tct_code_fails_closed():
    client = GeneralDepartmentOfTaxationClient(
        api_token="test-secret-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    # Valid is True but tct_code is missing
    mock_response.json.return_value = {"valid": True, "tct_code": None}

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.return_value = mock_response
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.UNKNOWN
    assert result.is_valid is False
    assert "thiếu mã cấp phép" in result.message


@pytest.mark.asyncio
async def test_gdt_client_unauthorized():
    client = GeneralDepartmentOfTaxationClient(
        api_token="invalid-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_response = MagicMock()
    mock_response.status_code = 401

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.return_value = mock_response
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.UNKNOWN
    assert result.is_valid is False
    assert "Unauthorized" in result.message


@pytest.mark.asyncio
async def test_gdt_client_handles_network_error():
    client = GeneralDepartmentOfTaxationClient(
        api_token="test-secret-token",
        api_url="https://hoadondientu.gdt.gov.vn/api/v1/lookup",
    )

    mock_httpx_client = AsyncMock()
    mock_httpx_client.get.side_effect = RuntimeError("Connection timed out")
    mock_httpx_client.__aenter__.return_value = mock_httpx_client

    with patch("httpx.AsyncClient", return_value=mock_httpx_client):
        result = await client.verify_invoice_status(
            supplier_tax_id="0101234567",
            invoice_series="1C26TAA",
            invoice_number="0000001",
        )

    assert result.status == VerificationStatus.UNKNOWN
    assert result.is_valid is False
    assert "Lỗi kết nối" in result.message
