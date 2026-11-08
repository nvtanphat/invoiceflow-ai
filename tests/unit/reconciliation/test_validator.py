from decimal import Decimal
from datetime import date
import uuid
from invoiceflow.domain.invoices.models import (
    InvoiceAggregate,
    InvoiceLine,
    InvoiceStatus,
)


def test_validator_detects_arithmetic_discrepancy():
    from invoiceflow.application.reconciliation.validator import InvoiceValidator

    validator = InvoiceValidator()

    # Invoice where line amount does not equal qty * price - discount
    bad_line = InvoiceLine(
        line_no=1,
        description="Mặt hàng sai số tiền",
        qty=Decimal("2.0000"),
        unit_price=Decimal("100000.0000"),
        discount=Decimal("0.0000"),
        line_amount=Decimal("300000.0000"),  # Expected 200,000
    )

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        revision=1,
        status=InvoiceStatus.RECEIVED,
        supplier_tax_id="0101234567",
        invoice_number="INV-001",
        issue_date=date(2026, 11, 8),
        subtotal=Decimal("300000.0000"),
        amount_payable=Decimal("300000.0000"),
        lines=[bad_line],
    )

    issues = validator.validate(inv)
    issue_codes = [issue.code for issue in issues]
    assert "LINE_ARITHMETIC_MISMATCH" in issue_codes


def test_validator_detects_missing_mandatory_fields():
    from invoiceflow.application.reconciliation.validator import InvoiceValidator

    validator = InvoiceValidator()
    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        revision=1,
        status=InvoiceStatus.RECEIVED,
        supplier_tax_id=None,  # Missing supplier tax id
        invoice_number=None,  # Missing invoice number
        amount_payable=Decimal("0.0000"),
    )

    issues = validator.validate(inv)
    issue_codes = [issue.code for issue in issues]
    assert "MISSING_SUPPLIER_TAX_ID" in issue_codes
    assert "MISSING_INVOICE_NUMBER" in issue_codes
