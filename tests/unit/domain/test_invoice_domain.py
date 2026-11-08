from decimal import Decimal
from datetime import date
import uuid
import pytest
from pydantic import ValidationError


def test_invoice_aggregate_exact_arithmetic():
    from invoiceflow.domain.invoices.models import (
        InvoiceAggregate,
        InvoiceLine,
        InvoiceStatus,
        TaxBreakdown,
    )

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        revision=1,
        status=InvoiceStatus.RECEIVED,
        supplier_tax_id="0101234567",
        supplier_name="Công ty TNHH Mẫu A",
        invoice_number="INV-0001",
        invoice_series="1C26TAA",
        issue_date=date(2026, 11, 8),
        currency="VND",
        subtotal=Decimal("1000000.0000"),
        discount_total=Decimal("50000.0000"),
        tax_total=Decimal("95000.0000"),
        amount_payable=Decimal("1045000.0000"),
        tax_breakdown=[
            TaxBreakdown(
                tax_rate=Decimal("10.00"),
                taxable_amount=Decimal("950000.0000"),
                tax_amount=Decimal("95000.0000"),
            )
        ],
        lines=[
            InvoiceLine(
                line_no=1,
                description="Hàng hóa mẫu",
                unit="Cái",
                qty=Decimal("2.0000"),
                unit_price=Decimal("500000.0000"),
                discount=Decimal("50000.0000"),
                tax_rate=Decimal("10.00"),
                tax=Decimal("95000.0000"),
                line_amount=Decimal("950000.0000"),
            )
        ],
    )
    assert inv.amount_payable == Decimal("1045000.0000")
    assert inv.calculated_line_total == Decimal("950000.0000")
    assert inv.is_arithmetic_balanced is True


def test_invoice_aggregate_rejects_float_amounts():
    from invoiceflow.domain.invoices.models import InvoiceLine

    with pytest.raises(ValidationError):
        InvoiceLine(
            line_no=1,
            description="Mẫu",
            qty=2.5,  # type: ignore[arg-type]
            unit_price=100.0,  # type: ignore[arg-type]
            line_amount=250.0,  # type: ignore[arg-type]
        )
