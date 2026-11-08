from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED_EXACT = "MATCHED_EXACT"
    MATCHED_WITHIN_TOLERANCE = "MATCHED_WITHIN_TOLERANCE"
    PRICE_VARIANCE = "PRICE_VARIANCE"
    QUANTITY_VARIANCE = "QUANTITY_VARIANCE"
    MISSING_PO = "MISSING_PO"
    MISSING_GRN = "MISSING_GRN"
    EXCEPTION = "EXCEPTION"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class POLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    po_id: UUID
    line_no: int
    sku: Optional[str] = None
    description: str
    unit: Optional[str] = None
    ordered_qty: Decimal = Field(..., ge=Decimal("0.0000"))
    unit_price: Decimal = Field(..., ge=Decimal("0.0000"))
    line_total: Decimal = Field(..., ge=Decimal("0.0000"))

    @field_validator("ordered_qty", "unit_price", "line_total", mode="before")
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float amounts forbidden in POLine.")
        return Decimal(str(v))


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    vendor_tax_id: str
    vendor_name: str
    po_number: str
    order_date: date
    currency: str = "VND"
    subtotal: Decimal
    lines: List[POLine] = Field(default_factory=list)

    @field_validator("subtotal", mode="before")
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float amounts forbidden in PurchaseOrder.")
        return Decimal(str(v))


class GRNLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    grn_id: UUID
    po_line_id: UUID
    line_no: int
    received_qty: Decimal = Field(..., ge=Decimal("0.0000"))
    rejected_qty: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0.0000"))

    @field_validator("received_qty", "rejected_qty", mode="before")
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float amounts forbidden in GRNLine.")
        return Decimal(str(v))


class GoodsReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    po_id: UUID
    grn_number: str
    receipt_date: date
    lines: List[GRNLine] = Field(default_factory=list)


class MatchIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: IssueSeverity = IssueSeverity.WARNING
    message: str
    line_no: Optional[int] = None
    field_path: Optional[str] = None
    actual_value: Optional[str] = None
    expected_value: Optional[str] = None


class MatchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    status: MatchStatus
    is_matched: bool
    requires_review: bool
    issues: List[MatchIssue] = Field(default_factory=list)
    reconciled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
