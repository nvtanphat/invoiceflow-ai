from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int
    description: str
    unit: Optional[str] = None
    qty: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal("0.0000")
    tax_rate: Optional[Decimal] = None
    line_amount: Decimal


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_tax_id: Optional[str] = None
    supplier_name: Optional[str] = None
    buyer_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_series: Optional[str] = None
    issue_date: Optional[str] = None
    currency: str = "VND"
    subtotal: Decimal = Decimal("0.0000")
    tax_total: Decimal = Decimal("0.0000")
    amount_payable: Decimal = Decimal("0.0000")
    line_items: List[ExtractedLine] = Field(default_factory=list)
    raw_response: dict = Field(default_factory=dict)
    prompt_version: str = "2026.11.1"


class LLMProviderPort(ABC):
    @abstractmethod
    async def extract_invoice_data(
        self,
        document_text: str,
        budget_usd: float = 0.05,
        request_id: Optional[str] = None,
    ) -> ExtractionResult:
        pass
