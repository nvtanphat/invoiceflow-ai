from decimal import Decimal
from datetime import date
import uuid
from invoiceflow.domain.invoices.models import InvoiceAggregate, InvoiceLine
from invoiceflow.domain.policies.models import TolerancePolicy
from invoiceflow.domain.purchasing.models import (
    GoodsReceipt,
    GRNLine,
    MatchStatus,
    POLine,
    PurchaseOrder,
)


def test_3_way_matching_exact():
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    tenant_id = uuid.uuid4()
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()
    grn_id = uuid.uuid4()

    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        vendor_tax_id="0101234567",
        vendor_name="Nhà cung cấp chuẩn",
        po_number="PO-2026-001",
        order_date=date(2026, 11, 1),
        subtotal=Decimal("1000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                sku="SKU-01",
                description="Hàng hóa A",
                ordered_qty=Decimal("10.0000"),
                unit_price=Decimal("100000.0000"),
                line_total=Decimal("1000000.0000"),
            )
        ],
    )

    grn = GoodsReceipt(
        id=grn_id,
        tenant_id=tenant_id,
        po_id=po_id,
        grn_number="GRN-2026-001",
        receipt_date=date(2026, 11, 5),
        lines=[
            GRNLine(
                id=uuid.uuid4(),
                grn_id=grn_id,
                po_line_id=po_line_id,
                line_no=1,
                received_qty=Decimal("10.0000"),
            )
        ],
    )

    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-001",
        issue_date=date(2026, 11, 8),
        subtotal=Decimal("1000000.0000"),
        amount_payable=Decimal("1000000.0000"),
        lines=[
            InvoiceLine(
                line_no=1,
                sku_ref="SKU-01",
                description="Hàng hóa A",
                qty=Decimal("10.0000"),
                unit_price=Decimal("100000.0000"),
                line_amount=Decimal("1000000.0000"),
                purchase_order_line_id=po_line_id,
            )
        ],
    )

    policy = TolerancePolicy(tenant_id=tenant_id, price_tolerance_pct=Decimal("0.02"))
    engine = MatchingEngine()
    report = engine.match_3_way(invoice=inv, po=po, receipts=[grn], policy=policy)

    assert report.is_matched is True
    assert report.status == MatchStatus.MATCHED_EXACT
    assert report.requires_review is False


def test_3_way_matching_quantity_variance():
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    tenant_id = uuid.uuid4()
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()
    grn_id = uuid.uuid4()

    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        vendor_tax_id="0101234567",
        vendor_name="Nhà cung cấp",
        po_number="PO-2026-002",
        order_date=date(2026, 11, 1),
        subtotal=Decimal("1000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                description="Hàng hóa A",
                ordered_qty=Decimal("10.0000"),
                unit_price=Decimal("100000.0000"),
                line_total=Decimal("1000000.0000"),
            )
        ],
    )

    # Received only 6 out of 10
    grn = GoodsReceipt(
        id=grn_id,
        tenant_id=tenant_id,
        po_id=po_id,
        grn_number="GRN-002",
        receipt_date=date(2026, 11, 5),
        lines=[
            GRNLine(
                id=uuid.uuid4(),
                grn_id=grn_id,
                po_line_id=po_line_id,
                line_no=1,
                received_qty=Decimal("6.0000"),
            )
        ],
    )

    # Invoiced 10
    inv = InvoiceAggregate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        lines=[
            InvoiceLine(
                line_no=1,
                description="Hàng hóa A",
                qty=Decimal("10.0000"),
                unit_price=Decimal("100000.0000"),
                line_amount=Decimal("1000000.0000"),
                purchase_order_line_id=po_line_id,
            )
        ],
    )

    policy = TolerancePolicy(tenant_id=tenant_id)
    engine = MatchingEngine()
    report = engine.match_3_way(invoice=inv, po=po, receipts=[grn], policy=policy)

    assert report.is_matched is False
    assert report.status == MatchStatus.QUANTITY_VARIANCE
    assert report.requires_review is True
    assert any(i.code == "QUANTITY_VARIANCE" for i in report.issues)
