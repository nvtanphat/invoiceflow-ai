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
                    timeout=45.0,
                    default_headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InvoiceFlow-AI/1.0"
                    },
                )
            except Exception:
                self._client = None

    async def extract_invoice_data(
        self,
        document_text: str,
        image_bytes: Optional[bytes | list[bytes]] = None,
        budget_usd: float = 0.05,
        request_id: Optional[str] = None,
    ) -> ExtractionResult:
        if not self._client:
            return ExtractionResult(
                supplier_name=None,
                supplier_tax_id=None,
                raw_response={"error": "OpenAI client not configured or missing API key"},
            )
        raw_dict = await self._call_openai_api(document_text, image_bytes)
        return self._map_to_result(raw_dict)

    async def _call_openai_api(
        self, document_text: str, image_bytes: Optional[bytes | list[bytes]] = None
    ) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("OpenAI/ModelAPI client is not configured or missing API key.")

        import base64
        user_msg: list[dict[str, Any]] = [{"type": "text", "text": f"DOCUMENT CONTENT TO EXTRACT:\n{document_text}\n"}]
        if image_bytes:
            imgs = image_bytes if isinstance(image_bytes, list) else [image_bytes]
            for img in imgs:
                b64_img = base64.b64encode(img).decode("utf-8")
                user_msg.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_img}"},
                })

        messages = [
            {"role": "system", "content": INVOICE_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        response = await self._client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except Exception:
            data = {}

        usage = getattr(response, "usage", None)
        if usage:
            data["_usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
        return data

    def _map_to_result(self, data: dict[str, Any]) -> ExtractionResult:
        lines = []
        raw_lines = data.get("line_items") or data.get("items") or []
        for idx, raw_line in enumerate(raw_lines, start=1):
            desc_val = str(raw_line.get("description") or raw_line.get("item_name") or "")
            sku_val = raw_line.get("sku") or raw_line.get("sku_ref")
            if not sku_val and "[" in desc_val:
                m_sku = re.search(r"\[([A-Z0-9_-]+)\]", desc_val)
                if m_sku:
                    sku_val = m_sku.group(1)

            lines.append(
                ExtractedLine(
                    line_no=int(raw_line.get("line_no", idx)),
                    sku=str(sku_val).strip() if sku_val else None,
                    description=desc_val,
                    unit=raw_line.get("unit"),
                    qty=self._parse_decimal(raw_line.get("qty") or raw_line.get("quantity")),
                    unit_price=self._parse_decimal(raw_line.get("unit_price") or raw_line.get("price")),
                    discount=self._parse_decimal(raw_line.get("discount")),
                    tax_rate=self._parse_decimal(raw_line.get("tax_rate")) if raw_line.get("tax_rate") else None,
                    line_amount=self._parse_decimal(raw_line.get("line_amount") or raw_line.get("amount")),
                )
            )

        s_tax = data.get("supplier_tax_id") or data.get("tax_code") or data.get("seller_tax_id")
        s_name = data.get("supplier_name") or data.get("seller_name")
        b_tax = data.get("buyer_tax_id") or data.get("customer_tax_id")
        b_name = data.get("buyer_name") or data.get("customer_name")
        inv_no = data.get("invoice_number") or data.get("invoice_no")
        inv_series = data.get("invoice_series") or data.get("series") or data.get("invoice_template")
        i_date = data.get("issue_date") or data.get("invoice_date") or data.get("date")

        usage = data.get("_usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        # Precise token-based cost accounting ($0.15/1M prompt, $0.60/1M completion)
        cost_usd = (prompt_tokens * 0.00000015) + (completion_tokens * 0.0000006)
        if cost_usd == 0 and (prompt_tokens > 0 or completion_tokens > 0):
            cost_usd = 0.0001

        return ExtractionResult(
            supplier_tax_id=str(s_tax).strip() if s_tax else None,
            supplier_name=str(s_name).strip() if s_name else None,
            buyer_tax_id=str(b_tax).strip() if b_tax else None,
            buyer_name=str(b_name).strip() if b_name else None,
            invoice_number=str(inv_no).strip() if inv_no else None,
            invoice_series=str(inv_series).strip() if inv_series else None,
            issue_date=str(i_date).strip() if i_date else None,
            currency=data.get("currency", "VND"),
            subtotal=self._parse_decimal(data.get("subtotal") or data.get("pre_tax_amount")),
            tax_total=self._parse_decimal(data.get("tax_total") or data.get("vat_amount")),
            amount_payable=self._parse_decimal(data.get("amount_payable") or data.get("total_amount")),
            line_items=lines,
            raw_response=data,
            prompt_version=PROMPT_VERSION,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost_usd, 6),
        )

    def _parse_decimal(self, val: Any) -> Decimal:
        if val is None or val == "":
            return Decimal("0.0000")
        clean = re.sub(r"[^\d.-]", "", str(val).replace(",", "."))
        try:
            return Decimal(clean)
        except Exception:
            return Decimal("0.0000")
