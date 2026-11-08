import json
import re
from decimal import Decimal
from typing import Any, Optional
from invoiceflow.infrastructure.llm.provider import (
    ExtractedLine,
    ExtractionResult,
    LLMProviderPort,
)
from invoiceflow.prompts.invoice_extraction import (
    INVOICE_EXTRACTION_SYSTEM_PROMPT,
    PROMPT_VERSION,
)


class OpenAIAdapter(LLMProviderPort):
    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.modelapi.vn/v1",
        model_id: str = "gpt-6.1-sol",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self._client = None

        if api_key and api_key != "mock-key":
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    default_headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InvoiceFlow-AI/1.0"
                    },
                )
            except Exception:
                self._client = None

    async def extract_invoice_data(
        self,
        document_text: str,
        budget_usd: float = 0.05,
        request_id: Optional[str] = None,
    ) -> ExtractionResult:
        raw_dict = await self._call_openai_api(document_text)
        return self._map_to_result(raw_dict)

    async def _call_openai_api(self, document_text: str) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("OpenAI/ModelAPI client is not configured or missing API key.")

        messages = [
            {"role": "system", "content": INVOICE_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"DOCUMENT CONTENT TO EXTRACT:\n{document_text}\n"},
        ]

        response = await self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _map_to_result(self, data: dict[str, Any]) -> ExtractionResult:
        lines = []
        for raw_line in data.get("line_items", []):
            lines.append(
                ExtractedLine(
                    line_no=int(raw_line.get("line_no", 1)),
                    description=str(raw_line.get("description", "")),
                    unit=raw_line.get("unit"),
                    qty=self._parse_decimal(raw_line.get("qty")),
                    unit_price=self._parse_decimal(raw_line.get("unit_price")),
                    discount=self._parse_decimal(raw_line.get("discount")),
                    tax_rate=self._parse_decimal(raw_line.get("tax_rate")) if raw_line.get("tax_rate") else None,
                    line_amount=self._parse_decimal(raw_line.get("line_amount")),
                )
            )

        return ExtractionResult(
            supplier_tax_id=str(data["supplier_tax_id"]).strip() if data.get("supplier_tax_id") else None,
            supplier_name=str(data["supplier_name"]).strip() if data.get("supplier_name") else None,
            buyer_tax_id=str(data["buyer_tax_id"]).strip() if data.get("buyer_tax_id") else None,
            buyer_name=str(data["buyer_name"]).strip() if data.get("buyer_name") else None,
            invoice_number=str(data["invoice_number"]).strip() if data.get("invoice_number") else None,
            invoice_series=str(data["invoice_series"]).strip() if data.get("invoice_series") else None,
            issue_date=str(data["issue_date"]).strip() if data.get("issue_date") else None,
            currency=data.get("currency", "VND"),
            subtotal=self._parse_decimal(data.get("subtotal")),
            tax_total=self._parse_decimal(data.get("tax_total")),
            amount_payable=self._parse_decimal(data.get("amount_payable")),
            line_items=lines,
            raw_response=data,
            prompt_version=PROMPT_VERSION,
        )

    def _parse_decimal(self, val: Any) -> Decimal:
        if val is None or val == "":
            return Decimal("0.0000")
        clean = re.sub(r"[^\d.-]", "", str(val).replace(",", "."))
        try:
            return Decimal(clean)
        except Exception:
            return Decimal("0.0000")
