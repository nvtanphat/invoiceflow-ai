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


def _po_grn_invoice(invoice_unit_price: str, invoice_unit: str = "cai"):
    tenant_id = uuid.uuid4()
    po_id = uuid.uuid4()
    po_line_id = uuid.uuid4()
    grn_id = uuid.uuid4()
    po = PurchaseOrder(
        id=po_id,
        tenant_id=tenant_id,
        vendor_tax_id="0101234567",
        vendor_name="Nhà cung cấp",
        po_number="PO-2026-777",
        order_date=date(2026, 11, 1),
        subtotal=Decimal("2000000.0000"),
        lines=[
            POLine(
                id=po_line_id,
                po_id=po_id,
                line_no=1,
                sku="SKU-77",
                description="Thiết bị B",
                unit="cai",
                ordered_qty=Decimal("2.0000"),
                unit_price=Decimal("1000000.0000"),
                line_total=Decimal("2000000.0000"),
            )
        ],
    )
    grn = GoodsReceipt(
        id=grn_id,
        tenant_id=tenant_id,
        po_id=po_id,
        grn_number="GRN-777",
        receipt_date=date(2026, 11, 3),
        lines=[
            GRNLine(
                grn_id=grn_id,
                po_line_id=po_line_id,
                line_no=1,
                received_qty=Decimal("2.0000"),
            )
        ],
    )
    unit_price = Decimal(invoice_unit_price)
    subtotal = unit_price * Decimal("2")
    invoice = InvoiceAggregate(
        tenant_id=tenant_id,
        document_id=uuid.uuid4(),
        supplier_tax_id="0101234567",
        invoice_number="INV-777",
        subtotal=subtotal,
        tax_total=subtotal / Decimal("10"),
        amount_payable=subtotal + subtotal / Decimal("10"),
        lines=[
            InvoiceLine(
                line_no=1,
                sku_ref="SKU-77",
                description="Thiết bị B",
                unit=invoice_unit,
                qty=Decimal("2.0000"),
                unit_price=unit_price,
                line_amount=subtotal,
            )
        ],
    )
    return po, grn, invoice, TolerancePolicy(tenant_id=tenant_id)


def test_amount_delta_compares_pre_tax_values():
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    po, grn, invoice, policy = _po_grn_invoice("1000000.0000")

    report = MatchingEngine().match_3_way(invoice, po, [grn], policy)

    assert "MAX_AMOUNT_DELTA_EXCEEDED" not in [i.code for i in report.issues]
    assert report.status == MatchStatus.MATCHED_EXACT


def test_amount_delta_beyond_policy_is_reported_on_pre_tax_subtotal():
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    po, grn, invoice, policy = _po_grn_invoice("1000000.0000")
    invoice.subtotal = Decimal("2100000.0000")

    report = MatchingEngine().match_3_way(invoice, po, [grn], policy)

    assert "MAX_AMOUNT_DELTA_EXCEEDED" in [i.code for i in report.issues]
    assert report.is_matched is False
    assert report.requires_review is True


def test_warning_issues_are_not_hidden_by_tolerated_price_variance():
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    po, grn, invoice, policy = _po_grn_invoice("1010000.0000", invoice_unit="kg")

    report = MatchingEngine().match_3_way(invoice, po, [grn], policy)

    assert "UOM_MISMATCH" in [i.code for i in report.issues]
    assert report.status == MatchStatus.EXCEPTION
    assert report.is_matched is False
    assert report.requires_review is True


def test_rejected_goods_do_not_count_as_received():
    """Regression: GRN rejected_qty was ignored, so an invoice billing rejected goods matched."""
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    po, grn, invoice, policy = _po_grn_invoice("1000000.0000")
    grn.lines[0].rejected_qty = Decimal("1.0000")

    report = MatchingEngine().match_3_way(invoice, po, [grn], policy)

    assert report.status == MatchStatus.QUANTITY_VARIANCE
    variance = next(i for i in report.issues if i.code == "QUANTITY_VARIANCE")
    assert variance.expected_value == "1.0000"


def test_invoice_line_is_not_matched_to_a_po_line_by_position_alone():
    """A dissimilar description must go to review instead of borrowing PO line N by index."""
    from invoiceflow.application.reconciliation.matching_engine import MatchingEngine

    po, grn, invoice, policy = _po_grn_invoice("1000000.0000")
    invoice.lines[0].sku_ref = None
    invoice.lines[0].description = "Phi van chuyen noi bo"

    report = MatchingEngine().match_3_way(invoice, po, [grn], policy)

    assert "UNMATCHED_LINE" in [i.code for i in report.issues]
    assert report.is_matched is False
