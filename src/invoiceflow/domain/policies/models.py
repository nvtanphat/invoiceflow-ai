from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TolerancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Union[UUID, str] = Field(default_factory=uuid4)
    tenant_id: Union[UUID, str]
    vendor_tax_id: Optional[str] = None
    version: int = 1

    price_tolerance_pct: Decimal = Field(
        default=Decimal("0.0200"), description="Relative price tolerance, e.g. 0.02 = 2%"
    )
    qty_tolerance_pct: Decimal = Field(
        default=Decimal("0.0000"), description="Quantity tolerance, e.g. 0.00 = 0%"
    )
    max_amount_delta: Decimal = Field(
        default=Decimal("50000.0000"), description="Absolute amount deviation limit"
    )
    auto_approve_threshold: Decimal = Field(
        default=Decimal("10000000.0000"), description="Max invoice amount allowed for auto-approve"
    )
    separation_of_duties_required: bool = True
    effective_from: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())

    @field_validator(
        "price_tolerance_pct",
        "qty_tolerance_pct",
        "max_amount_delta",
        "auto_approve_threshold",
        mode="before",
    )
    @classmethod
    def enforce_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            raise ValueError("Float values forbidden in TolerancePolicy.")
        return Decimal(str(v))

    def is_price_within_tolerance(self, expected: Decimal, actual: Decimal) -> bool:
        if expected == Decimal("0.0000"):
            return actual == Decimal("0.0000")
        diff_pct = abs(actual - expected) / expected
        return diff_pct <= self.price_tolerance_pct

    def is_qty_within_tolerance(self, expected: Decimal, actual: Decimal) -> bool:
        if expected == Decimal("0.0000"):
            return actual == Decimal("0.0000")
        diff_pct = abs(actual - expected) / expected
        return diff_pct <= self.qty_tolerance_pct
