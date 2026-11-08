import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_gemini_adapter_conformance_with_mock_client():
    from invoiceflow.infrastructure.llm.gemini_adapter import GeminiAdapter, ExtractionResult

    # Mock response payload conforming to strict JSON schema
    mock_json_response = {
        "supplier_tax_id": "0101234567",
        "supplier_name": "Công ty Test AI",
        "invoice_number": "INV-777",
        "invoice_series": "1C26TAA",
        "issue_date": "2026-11-08",
        "currency": "VND",
        "subtotal": "5000000.00",
        "tax_total": "500000.00",
        "amount_payable": "5500000.00",
        "line_items": [
            {
                "line_no": 1,
                "description": "Máy chủ AI",
                "qty": "1.00",
                "unit_price": "5000000.00",
                "line_amount": "5000000.00",
                "tax_rate": "10.00",
            }
        ],
    }

    adapter = GeminiAdapter(api_key="mock-key", model_id="gemini-2.5-flash")
    adapter._client = MagicMock()

    # Stub the internal generation method
    adapter._call_genai_api = AsyncMock(return_value=mock_json_response)  # type: ignore

    res = await adapter.extract_invoice_data(
        document_text="Sample document OCR text with INV-777",
        budget_usd=0.05,
    )
    assert res.supplier_tax_id == "0101234567"
    assert res.invoice_number == "INV-777"
    assert res.amount_payable == Decimal("5500000.00")
    assert len(res.line_items) == 1
    assert res.line_items[0].line_amount == Decimal("5000000.00")
