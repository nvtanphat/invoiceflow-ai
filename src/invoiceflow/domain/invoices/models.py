from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from invoiceflow.domain.documents.models import BoundingBox


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    MATCHING = "MATCHING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPORTED = "EXPORTED"


class VerificationStatus(str, Enum):
    NOT_CHECKED = "not_checked"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FieldVerificationState(str, Enum):
    VALID = "valid"
    ZERO = "zero"
    MISSING = "missing"
    INVALID = "invalid"
    UNCERTAIN = "uncertain"
    CONFLICT = "conflict"
    ARITHMETICALLY_CONSISTENT = "arithmetically_consistent"
    MODEL_PROPOSED = "model_proposed"
    HUMAN_APPROVED = "human_approved"


class TaxBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_rate: Decimal = Field(..., description="e.g. 8.00, 10.00")
    taxable_amount: Decimal
    tax_amount: Decimal

    @field_validator("tax_rate", "taxable_amount", "tax_amount", mode="before")
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float amounts are forbidden for financial data. Use Decimal or str.")
        return Decimal(str(v))


class FieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    source_kind: str
    page_index: Optional[int] = None
    bbox: Optional[BoundingBox] = None
    table_id: Optional[str] = None
    cell_id: Optional[str] = None
    raw_value: Optional[str] = None
    normalized_value: Optional[str] = None
    confidence: Optional[float] = None
    extractor: str = "deterministic"
    verification_state: Union[FieldVerificationState, str] = FieldVerificationState.MODEL_PROPOSED
    review_reason: Optional[str] = None


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_no: int = Field(..., ge=1)
    sku_ref: Optional[str] = None
    description: str
    unit: Optional[str] = None
    qty: Decimal = Field(..., ge=Decimal("0.0000"))
    unit_price: Decimal = Field(..., ge=Decimal("0.0000"))
    discount: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0.0000"))
    tax_rate: Optional[Decimal] = None
    tax: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0.0000"))
    line_amount: Decimal = Field(..., ge=Decimal("0.0000"))
    purchase_order_line_id: Optional[Union[UUID, str]] = None
    raw_qty: Optional[str] = None
    raw_unit_price: Optional[str] = None
    raw_line_amount: Optional[str] = None
    issues: List[str] = Field(default_factory=list)

    @field_validator("qty", "unit_price", "discount", "tax", "line_amount", mode="before")
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float values are forbidden in InvoiceLine. Use Decimal or str.")
        return Decimal(str(v))


class InvoiceAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Union[UUID, str] = Field(default_factory=uuid4)
    tenant_id: Union[UUID, str]
    document_id: Union[UUID, str]
    revision: int = 1
    status: InvoiceStatus = InvoiceStatus.RECEIVED

    supplier_tax_id: Optional[str] = None
    supplier_name: Optional[str] = None
    buyer_tax_id: Optional[str] = None
    buyer_name: Optional[str] = None

    invoice_number: Optional[str] = None
    invoice_series: Optional[str] = None
    issue_date: Optional[date] = None
    currency: str = "VND"
    exchange_rate: Optional[Decimal] = None

    subtotal: Decimal = Field(default=Decimal("0.0000"))
    discount_total: Decimal = Field(default=Decimal("0.0000"))
    tax_total: Decimal = Field(default=Decimal("0.0000"))
    amount_payable: Decimal = Field(default=Decimal("0.0000"))
    rounding_adjustment: Decimal = Field(default=Decimal("0.0000"))

    tax_breakdown: List[TaxBreakdown] = Field(default_factory=list)
    lines: List[InvoiceLine] = Field(default_factory=list)
    evidence: List[FieldEvidence] = Field(default_factory=list)
    parser_issues: List[str] = Field(default_factory=list)

    signature_status: VerificationStatus = VerificationStatus.NOT_CHECKED
    tax_authority_status: VerificationStatus = VerificationStatus.NOT_CHECKED

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "subtotal",
        "discount_total",
        "tax_total",
        "amount_payable",
        "rounding_adjustment",
        mode="before",
    )
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float values are forbidden in InvoiceAggregate. Use Decimal or str.")
        return Decimal(str(v))

    @property
    def calculated_line_total(self) -> Decimal:
        return sum((line.line_amount for line in self.lines), Decimal("0.0000"))

    @property
    def is_arithmetic_balanced(self) -> bool:
        expected_total = (
            self.subtotal - self.discount_total + self.tax_total + self.rounding_adjustment
        )
        return abs(self.amount_payable - expected_total) < Decimal("0.0100")
