from decimal import Decimal
from datetime import date
import uuid
import pytest


def test_matching_tolerance_policy():
    from invoiceflow.domain.policies.models import TolerancePolicy
    from invoiceflow.domain.purchasing.models import (
        PurchaseOrder,
        POLine,
        GoodsReceipt,
        GRNLine,
        MatchStatus,
    )

    policy = TolerancePolicy(
        tenant_id=uuid.uuid4(),
        price_tolerance_pct=Decimal("0.02"),  # 2%
        qty_tolerance_pct=Decimal("0.00"),    # 0%
        auto_approve_threshold=Decimal("5000000.0000"),
    )
    assert policy.is_price_within_tolerance(
        expected=Decimal("100.0000"), actual=Decimal("101.5000")
    )
    assert not policy.is_price_within_tolerance(
        expected=Decimal("100.0000"), actual=Decimal("103.0000")
    )
