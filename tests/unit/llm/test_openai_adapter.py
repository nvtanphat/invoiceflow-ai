from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from invoiceflow.infrastructure.llm.openai_adapter import OpenAIAdapter


def test_openai_adapter_map_to_result():
    adapter = OpenAIAdapter(api_key="mock-key", model_id="gpt-6.1-sol")
    raw_dict = {
        "supplier_tax_id": "0101234567",
        "supplier_name": "Công ty TNHH Thăng Long",
        "invoice_number": "0001245",
        "invoice_series": "1C26TAA",
        "issue_date": "2026-03-02",
        "currency": "VND",
        "subtotal": "50000000",
        "tax_total": "5000000",
        "amount_payable": "55000000",
        "line_items": [
            {
                "line_no": 1,
                "description": "Máy tính Dell XPS",
                "qty": "5",
                "unit_price": "10000000",
                "line_amount": "50000000",
            }
        ],
    }

    res = adapter._map_to_result(raw_dict)
    assert res.supplier_tax_id == "0101234567"
    assert res.invoice_number == "0001245"
    assert res.supplier_name == "Công ty TNHH Thăng Long"
    assert res.amount_payable == Decimal("55000000.0000")
    assert len(res.line_items) == 1
    assert res.line_items[0].qty == Decimal("5.0000")
    assert res.line_items[0].unit_price == Decimal("10000000.0000")


@pytest.mark.asyncio
async def test_openai_adapter_extract_mock():
    adapter = OpenAIAdapter(api_key="mock-key", model_id="gpt-6.1-sol")
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content='{"supplier_tax_id": "0101234567", "amount_payable": "55000000", "line_items": []}'
            )
        )
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
    adapter._client = mock_client

    res = await adapter.extract_invoice_data("document text content")
    assert res.supplier_tax_id == "0101234567"
    assert res.amount_payable == Decimal("55000000.0000")
