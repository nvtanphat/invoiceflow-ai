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


class GeminiAdapter(LLMProviderPort):
    def __init__(
        self,
        api_key: str = "",
        model_id: str = "gemini-2.5-flash",
    ):
        self.api_key = api_key
        self.model_id = model_id
        self._client = None
        if api_key and api_key != "mock-key":
            try:
                from google import genai

                self._client = genai.Client(api_key=api_key)
            except Exception:
                self._client = None

    async def extract_invoice_data(
        self,
        document_text: str,
        image_bytes: Optional[bytes] = None,
        budget_usd: float = 0.05,
        request_id: Optional[str] = None,
    ) -> ExtractionResult:
        raw_dict = await self._call_genai_api(document_text, image_bytes)
        return self._map_to_result(raw_dict)

    async def _call_genai_api(
        self, document_text: str, image_bytes: Optional[bytes] = None
    ) -> dict[str, Any]:
        """Calls Gemini API or raises exception if not configured."""
        if not self._client:
            raise RuntimeError("Gemini API client is not configured or missing API key.")

        prompt = (
            f"{INVOICE_EXTRACTION_SYSTEM_PROMPT}\n\nDOCUMENT CONTENT TO EXTRACT:\n{document_text}\n"
        )
        contents = [prompt]
        if image_bytes:
            from google.genai import types

            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))

        response = self._client.models.generate_content(
            model=self.model_id,
            contents=contents,
            config={
                "response_mime_type": "application/json",
            },
        )
        return json.loads(response.text)

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
                    tax_rate=self._parse_decimal(raw_line.get("tax_rate"))
                    if raw_line.get("tax_rate")
                    else None,
                    line_amount=self._parse_decimal(raw_line.get("line_amount")),
                )
            )

        return ExtractionResult(
            supplier_tax_id=data.get("supplier_tax_id"),
            supplier_name=data.get("supplier_name"),
            buyer_tax_id=data.get("buyer_tax_id"),
            buyer_name=data.get("buyer_name"),
            invoice_number=data.get("invoice_number"),
            invoice_series=data.get("invoice_series"),
            issue_date=data.get("issue_date"),
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
